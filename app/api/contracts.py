"""Contract management API - visual scheme mapper and document generation."""
from __future__ import annotations
import json
import io
import zipfile
from typing import Any
from datetime import datetime
import structlog
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse

from app.config import get_settings
from app.core.contract_generator import ContractGenerator
from app.core.http import content_disposition
from app.db.repositories.stakeholder_repo import (
    StakeholderRepository,
    ROLE_TYPE_LABELS,
    VALID_ROLE_TYPES,
)
from app.middleware.rbac import require_permission

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/contracts", tags=["contracts"])

# All 9 contract types
CONTRACT_TYPES = {
    "tk_agreement": {
        "name": "匿名組合契約書",
        "name_en": "TK Agreement",
        "party_a": "spc",
        "party_b": "investor",
        "variables": [],
    },
    "sales_agreement": {
        "name": "車両売買契約書",
        "name_en": "Sales Agreement",
        "party_a": "end_user",
        "party_b": "spc",
        "variables": [],
    },
    "master_lease": {
        "name": "マスターリース契約書",
        "name_en": "Master Lease",
        "party_a": "spc",
        "party_b": "operator",
        "variables": [],
    },
    "sublease_agreement": {
        "name": "サブリース契約書",
        "name_en": "Sub-lease",
        "party_a": "operator",
        "party_b": "end_user",
        "variables": [],
    },
    "private_placement": {
        "name": "私募取扱業務契約書",
        "name_en": "Private Placement",
        "party_a": "spc",
        "party_b": "private_placement_agent",
        "variables": ["placement_fee_rate", "total_placement_amount"],
    },
    "customer_referral": {
        "name": "顧客紹介業務契約書",
        "name_en": "Customer Referral",
        "party_a": "spc",
        "party_b": "asset_manager",
        "variables": ["referral_fee_rate"],
    },
    "asset_management": {
        "name": "アセットマネジメント契約書",
        "name_en": "Asset Management",
        "party_a": "spc",
        "party_b": "asset_manager",
        "variables": ["am_fee_rate", "managed_assets_value"],
    },
    "accounting_firm": {
        "name": "会計事務委託契約書①（会計事務所）",
        "name_en": "Accounting (Firm)",
        "party_a": "spc",
        "party_b": "accounting_firm",
        "variables": ["monthly_fee", "scope_of_work"],
    },
    "accounting_association": {
        "name": "会計事務委託契約書②（一般社団法人）",
        "name_en": "Accounting (Association)",
        "party_a": "spc",
        "party_b": "accounting_delegate",
        "variables": ["monthly_fee", "scope_of_work"],
    },
}


def _get_client():
    from app.db.supabase_client import get_supabase_client
    return get_supabase_client(service_role=True)


def _get_repo() -> StakeholderRepository:
    return StakeholderRepository(_get_client())


# GET /api/v1/contracts/mapper/{simulation_id}
@router.get("/mapper/{simulation_id}")
async def get_contract_mapper(
    simulation_id: str,
    request: Request,
    user: dict = Depends(require_permission("contracts", "read")),
):
    """Return the visual scheme mapper HTML fragment."""
    client = _get_client()

    # Fetch simulation
    sim = client.table("simulations").select("*").eq("id", simulation_id).maybe_single().execute()
    simulation = sim.data
    if not simulation:
        return HTMLResponse("<div class='alert alert--error'>シミュレーションが見つかりません</div>", status_code=404)

    # Fetch existing stakeholders
    sh = client.table("deal_stakeholders").select("*").eq("simulation_id", simulation_id).order("display_order").execute()
    stakeholders = sh.data or []

    # Fetch contract templates
    ct = client.table("contract_templates").select("*").eq("is_active", True).order("display_order").execute()
    templates = ct.data or []

    # Fetch generated contracts
    dc = client.table("deal_contracts").select("*").eq("simulation_id", simulation_id).order("created_at", desc=True).execute()
    contracts = dc.data or []

    # Build stakeholder map by role
    sh_map = {}
    for s in stakeholders:
        sh_map[s["role_type"]] = s

    rsj = simulation.get("result_summary_json") or {}

    return HTMLResponse(_build_mapper_html(simulation, stakeholders, sh_map, templates, contracts, rsj))


# POST /api/v1/contracts/stakeholders
@router.post("/stakeholders")
async def save_stakeholder(
    request: Request,
    user: dict = Depends(require_permission("stakeholders", "write")),
):
    """Save or update a stakeholder."""
    form = await request.form()
    client = _get_client()

    simulation_id = form.get("simulation_id")
    role_type = form.get("role_type")
    stakeholder_id = form.get("stakeholder_id")

    data = {
        "simulation_id": simulation_id,
        "role_type": role_type,
        "company_name": form.get("company_name", ""),
        "representative_name": form.get("representative_name", ""),
        "address": form.get("address", ""),
        "phone": form.get("phone", ""),
        "email": form.get("email_addr", ""),
        "registration_number": form.get("registration_number", ""),
        "seal_required": form.get("seal_required") == "on",
    }

    try:
        if stakeholder_id:
            client.table("deal_stakeholders").update(data).eq("id", stakeholder_id).execute()
        else:
            client.table("deal_stakeholders").insert(data).execute()

        return HTMLResponse(f'''
            <div class="alert alert--success">
                {_role_label(role_type)}の情報を保存しました
            </div>
        ''')
    except Exception as e:
        return HTMLResponse(f'<div class="alert alert--error">保存エラー: {str(e)[:100]}</div>')


def _parse_types_param(types: str | None) -> set[str] | None:
    """Parse a comma-separated ``types`` query param into a set of display
    names.  Returns ``None`` when no filter is requested (generate all)."""
    if not types:
        return None
    selected = {t.strip() for t in types.split(",") if t.strip()}
    return selected or None


def _generate_docx_bytes(
    simulation_id: str,
    selected_display_names: set[str] | None = None,
    persist: bool = True,
):
    """Shared generation loop used by both ``POST /generate/{id}`` and
    ``GET /bulk-zip/{id}``.

    Returns a tuple ``(generated_entries, error_response)``.  When
    ``error_response`` is not None the caller should return it directly.

    ``selected_display_names`` optionally filters the contracts to generate
    by their display (Japanese) name.
    """
    client = _get_client()

    # --- Fetch simulation --------------------------------------------------
    sim = client.table("simulations").select("*").eq("id", simulation_id).maybe_single().execute()
    if not sim.data:
        return [], JSONResponse({"error": "Simulation not found"}, status_code=404)
    simulation = sim.data
    rsj = simulation.get("result_summary_json") or {}

    # --- Fetch stakeholders ------------------------------------------------
    sh = client.table("deal_stakeholders").select("*").eq("simulation_id", simulation_id).execute()
    stakeholders = {s["role_type"]: s for s in (sh.data or [])}

    if not stakeholders:
        return [], HTMLResponse(
            '<div class="alert alert--error">ステークホルダー情報を先に登録してください</div>'
        )

    # --- Fetch DB contract templates (for audit trail) --------------------
    ct = client.table("contract_templates").select("*").eq("is_active", True).order("display_order").execute()
    db_templates = ct.data or []
    db_template_by_name = {t["contract_name"]: t for t in db_templates}

    # --- Build pricing_result dict from simulation + rsj ------------------
    pricing_result = {
        "purchase_price_yen": simulation.get("purchase_price_yen", 0),
        "lease_monthly_yen": simulation.get("lease_monthly_yen", 0),
        "lease_term_months": simulation.get("lease_term_months", 0),
        "total_lease_revenue_yen": simulation.get("total_lease_revenue_yen", 0),
        "target_mileage_km": simulation.get("target_mileage_km", 0),
        "vehicle_year": simulation.get("target_model_year", ""),
        **rsj,
    }

    fund_info = {
        "fund_name": rsj.get("fund_name", simulation.get("fund_name", "")),
    }

    # --- Generate DOCX contracts via ContractGenerator --------------------
    generator = ContractGenerator()
    generated_entries: list[dict] = []

    for contract_type, template_file in generator.TEMPLATES.items():
        display_name = generator.CONTRACT_NAMES.get(contract_type, contract_type)

        # Filter by explicit type selection when provided
        if selected_display_names is not None and display_name not in selected_display_names:
            continue

        party_a_role, party_b_role = generator.PARTY_MAPPING.get(
            contract_type, ("spc", "operator")
        )
        party_a = stakeholders.get(party_a_role, {})
        party_b = stakeholders.get(party_b_role, {})

        if not party_a.get("company_name") or not party_b.get("company_name"):
            continue

        context = generator._build_context(
            contract_type, stakeholders, pricing_result, fund_info
        )

        try:
            docx_bytes = generator.generate_contract(contract_type, context)
        except FileNotFoundError:
            logger.warning("template_missing", contract_type=contract_type)
            continue

        # Persist to deal_contracts for audit (only for POST /generate)
        if persist:
            try:
                dc_data = {
                    "simulation_id": simulation_id,
                    "contract_name": display_name,
                    "status": "generated",
                    "generated_context": context,
                    "generated_at": datetime.utcnow().isoformat(),
                }
                db_tmpl = db_template_by_name.get(display_name)
                if db_tmpl:
                    dc_data["template_id"] = db_tmpl["id"]
                client.table("deal_contracts").insert(dc_data).execute()
            except Exception:
                pass

        generated_entries.append({
            "display_name": display_name,
            "docx_bytes": docx_bytes,
        })

    if not generated_entries:
        return [], HTMLResponse(
            '<div class="alert alert--error">'
            "生成可能な契約書がありません。全ステークホルダーの情報を入力してください。"
            "</div>"
        )

    return generated_entries, None


def _zip_entries(simulation_id: str, entries: list[dict]) -> io.BytesIO:
    """Package generated DOCX entries into a ZIP BytesIO."""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in entries:
            filename = f"{entry['display_name']}_{simulation_id[:8]}.docx"
            zf.writestr(filename, entry["docx_bytes"])
    zip_buffer.seek(0)
    return zip_buffer


# POST /api/v1/contracts/generate/{simulation_id}
@router.post("/generate/{simulation_id}")
async def generate_contracts(
    simulation_id: str,
    request: Request,
    types: str | None = None,
    user: dict = Depends(require_permission("contracts", "write")),
):
    """Generate all contract documents for a simulation.

    Uses ContractGenerator to produce real DOCX files (via docxtpl variable
    substitution) instead of plain-text fallbacks.  The generated context is
    also persisted to the ``deal_contracts`` table for audit/traceability.

    Accepts an optional ``types`` query/form param — comma-separated
    display names to filter which contracts to generate.
    """
    # Also accept selected types from form body (HTMX posts checkboxes by name)
    selected: set[str] | None = _parse_types_param(types)
    if selected is None:
        try:
            form = await request.form()
            form_types = form.getlist("contract_types") if hasattr(form, "getlist") else []
            if form_types:
                selected = {t.strip() for t in form_types if t and t.strip()}
        except Exception:
            selected = None

    entries, err = _generate_docx_bytes(
        simulation_id, selected_display_names=selected, persist=True
    )
    if err is not None:
        return err

    zip_buffer = _zip_entries(simulation_id, entries)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": content_disposition(
                f"contracts_{simulation_id[:8]}.zip"
            )
        },
    )


# GET /api/v1/contracts/bulk-zip/{simulation_id}
@router.get("/bulk-zip/{simulation_id}")
async def bulk_zip_contracts(
    simulation_id: str,
    types: str | None = None,
    user: dict = Depends(require_permission("contracts", "read")),
):
    """Generate all (or selected) contract DOCX files and return as a
    single ZIP. Does not persist audit rows (read-level endpoint)."""
    selected = _parse_types_param(types)
    entries, err = _generate_docx_bytes(
        simulation_id, selected_display_names=selected, persist=False
    )
    if err is not None:
        return err

    zip_buffer = _zip_entries(simulation_id, entries)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": content_disposition(
                f"contracts_{simulation_id[:8]}.zip"
            )
        },
    )


# GET /api/v1/contracts/addressbook
@router.get("/addressbook")
async def list_addressbook(
    role_type: str = "",
    user: dict = Depends(require_permission("stakeholders", "read")),
):
    """List address book entries, optionally filtered by role."""
    client = _get_client()
    q = client.table("stakeholder_addressbook").select("*").order("company_name")
    if role_type:
        q = q.eq("role_type", role_type)
    result = q.execute()
    return JSONResponse({"data": result.data or []})


# GET /api/v1/contracts/addressbook/options/{role_type}
@router.get("/addressbook/options/{role_type}")
async def addressbook_options(
    role_type: str,
    user: dict = Depends(require_permission("stakeholders", "read")),
):
    """Return <option> HTML elements for a role's address book entries."""
    client = _get_client()
    result = client.table("stakeholder_addressbook").select("*").eq("role_type", role_type).order("company_name").execute()
    entries = result.data or []

    html = '<option value="">-- アドレス帳から選択 --</option>\n'
    for e in entries:
        html += f'<option value="{e["id"]}" data-name="{e["company_name"]}" data-rep="{e.get("representative_name","")}" data-addr="{e.get("address","")}" data-phone="{e.get("phone","")}" data-reg="{e.get("registration_number","")}">{e["company_name"]}</option>\n'
    html += '<option value="__new__">＋ 新規入力</option>'
    return HTMLResponse(html)


# POST /api/v1/contracts/addressbook/save
@router.post("/addressbook/save")
async def save_to_addressbook(
    request: Request,
    user: dict = Depends(require_permission("stakeholders", "write")),
):
    """Save current stakeholder info to the address book."""
    form = await request.form()
    client = _get_client()

    data = {
        "role_type": form.get("role_type", ""),
        "company_name": form.get("company_name", ""),
        "representative_name": form.get("representative_name", ""),
        "address": form.get("address", ""),
        "phone": form.get("phone", ""),
        "email": form.get("email_addr", ""),
        "registration_number": form.get("registration_number", ""),
    }

    try:
        client.table("stakeholder_addressbook").insert(data).execute()
        return HTMLResponse('<span class="badge badge--success" style="font-size:0.75rem">アドレス帳に保存しました</span>')
    except Exception as e:
        return HTMLResponse(f'<span class="badge badge--danger" style="font-size:0.75rem">保存失敗</span>')


# GET /api/v1/contracts/stakeholder-roles
@router.get("/stakeholder-roles")
async def list_stakeholder_roles(
    user: dict = Depends(require_permission("stakeholders", "read")),
):
    """List all available role types with Japanese labels."""
    repo = _get_repo()
    return JSONResponse({"data": repo.get_all_role_types()})


# PUT /api/v1/contracts/stakeholders/{id}
@router.put("/stakeholders/{stakeholder_id}")
async def update_stakeholder(
    stakeholder_id: str,
    request: Request,
    user: dict = Depends(require_permission("stakeholders", "write")),
):
    """Update a stakeholder by ID."""
    repo = _get_repo()
    body = await request.json()

    allowed_fields = {
        "company_name", "representative_name", "address", "phone",
        "email", "registration_number", "seal_required", "role_type",
    }
    update_data = {k: v for k, v in body.items() if k in allowed_fields}

    if not update_data:
        return JSONResponse({"error": "No valid fields to update"}, status_code=400)

    try:
        result = await repo.update(stakeholder_id, update_data)
        return JSONResponse({"data": result})
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


# DELETE /api/v1/contracts/stakeholders/{id}
@router.delete("/stakeholders/{stakeholder_id}")
async def delete_stakeholder(
    stakeholder_id: str,
    user: dict = Depends(require_permission("stakeholders", "write")),
):
    """Delete a stakeholder by ID."""
    repo = _get_repo()
    try:
        deleted = await repo.delete(stakeholder_id)
        if deleted:
            return JSONResponse({"ok": True})
        return JSONResponse({"error": "Not found"}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


# GET /api/v1/contracts/address-book
@router.get("/address-book")
async def get_address_book(
    q: str = "",
    user: dict = Depends(require_permission("stakeholders", "read")),
):
    """Get reusable stakeholder address book (unique company+role combos)."""
    repo = _get_repo()
    try:
        if q:
            entries = await repo.search_address_book(q)
        else:
            entries = await repo.get_address_book()
        return JSONResponse({"data": entries})
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


# POST /api/v1/contracts/stakeholders/copy/{source_sim_id}/{target_sim_id}
@router.post("/stakeholders/copy/{source_sim_id}/{target_sim_id}")
async def copy_stakeholders(
    source_sim_id: str,
    target_sim_id: str,
    user: dict = Depends(require_permission("stakeholders", "write")),
):
    """Copy all stakeholders from one simulation to another."""
    repo = _get_repo()
    try:
        copies = await repo.copy_from_simulation(source_sim_id, target_sim_id)
        return JSONResponse({
            "ok": True,
            "copied": len(copies),
            "data": copies,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


# GET /api/v1/contracts/types
@router.get("/types")
async def list_contract_types(
    user: dict = Depends(require_permission("contracts", "read")),
):
    """List all 9 supported contract types."""
    result = []
    for key, ct in CONTRACT_TYPES.items():
        result.append({
            "key": key,
            "name": ct["name"],
            "name_en": ct["name_en"],
            "party_a_role": ct["party_a"],
            "party_b_role": ct["party_b"],
            "party_a_label": ROLE_TYPE_LABELS.get(ct["party_a"], ct["party_a"]),
            "party_b_label": ROLE_TYPE_LABELS.get(ct["party_b"], ct["party_b"]),
            "extra_variables": ct["variables"],
        })
    return JSONResponse({"data": result})


# --- Helper functions ---

def _role_label(role: str) -> str:
    return ROLE_TYPE_LABELS.get(role, role)


def _build_template_context(simulation: dict, rsj: dict, stakeholders: dict) -> dict:
    purchase_price = simulation.get("purchase_price_yen", 0)
    return {
        "purchase_price": f"¥{purchase_price:,}",
        "purchase_price_num": purchase_price,
        "monthly_lease_fee": f"¥{simulation.get('lease_monthly_yen', 0):,}",
        "monthly_lease_fee_num": simulation.get("lease_monthly_yen", 0),
        "lease_term_months": simulation.get("lease_term_months", 0),
        "total_lease_revenue": f"¥{simulation.get('total_lease_revenue_yen', 0):,}",
        "vehicle_maker": rsj.get("maker", ""),
        "vehicle_model": rsj.get("model", ""),
        "vehicle_body_type": rsj.get("body_type", ""),
        "vehicle_year": simulation.get("target_model_year", ""),
        "vehicle_mileage": f"{simulation.get('target_mileage_km', 0):,}km",
        "target_yield_rate": f"{rsj.get('target_yield_rate', 0)}%",
        "assessment": rsj.get("assessment", ""),
        "simulation_id": simulation.get("id", ""),
        "simulation_date": (simulation.get("created_at") or "")[:10],
        # Private Placement variables
        "placement_fee_rate": rsj.get("placement_fee_rate", "3.0%"),
        "total_placement_amount": f"¥{purchase_price:,}",
        # Customer Referral variables
        "referral_fee_rate": rsj.get("referral_fee_rate", "1.0%"),
        # Asset Management variables
        "am_fee_rate": rsj.get("am_fee_rate", "2.0%"),
        "managed_assets_value": f"¥{purchase_price:,}",
        # Accounting (Firm & Association) variables
        "monthly_fee": rsj.get("monthly_fee", "¥50,000"),
        "scope_of_work": rsj.get("scope_of_work", "記帳代行、決算書作成、税務申告"),
    }


def _render_contract_text(contract_name: str, ctx: dict) -> str:
    """Render a contract as formatted text."""

    # Build contract-type-specific section
    extra_section = _render_contract_specific_section(contract_name, ctx)

    return f"""
{'=' * 60}
{contract_name}
{'=' * 60}

契約日: {ctx.get('contract_date', '')}
シミュレーションID: {ctx.get('simulation_id', '')[:8]}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

甲（Party A）
  法人名: {ctx.get('party_a_name', '')}
  代表者: {ctx.get('party_a_representative', '')}
  住所:   {ctx.get('party_a_address', '')}

乙（Party B）
  法人名: {ctx.get('party_b_name', '')}
  代表者: {ctx.get('party_b_representative', '')}
  住所:   {ctx.get('party_b_address', '')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

【対象車両】
  メーカー: {ctx.get('vehicle_maker', '')}
  車種:     {ctx.get('vehicle_model', '')}
  年式:     {ctx.get('vehicle_year', '')}年
  走行距離: {ctx.get('vehicle_mileage', '')}

【取引条件】
  買取価格:     {ctx.get('purchase_price', '')}
  月額リース料: {ctx.get('monthly_lease_fee', '')}
  リース期間:   {ctx.get('lease_term_months', '')}ヶ月
  リース料総額: {ctx.get('total_lease_revenue', '')}
  目標利回り:   {ctx.get('target_yield_rate', '')}
{extra_section}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

上記条件にて、甲と乙は本契約を締結する。

甲（署名）: ____________________  印

乙（署名）: ____________________  印

{'=' * 60}
"""


def _render_contract_specific_section(contract_name: str, ctx: dict) -> str:
    """Return extra text section based on contract type."""
    if "私募取扱業務" in contract_name:
        return f"""
【私募取扱業務条件】
  取扱手数料率:   {ctx.get('placement_fee_rate', '')}
  募集総額:       {ctx.get('total_placement_amount', '')}
"""
    elif "顧客紹介業務" in contract_name:
        return f"""
【顧客紹介業務条件】
  紹介手数料率:   {ctx.get('referral_fee_rate', '')}
"""
    elif "アセットマネジメント" in contract_name:
        return f"""
【アセットマネジメント条件】
  AM手数料率:     {ctx.get('am_fee_rate', '')}
  管理資産額:     {ctx.get('managed_assets_value', '')}
"""
    elif "会計事務委託契約書①" in contract_name:
        return f"""
【会計事務委託条件（会計事務所）】
  月額報酬:       {ctx.get('monthly_fee', '')}
  業務範囲:       {ctx.get('scope_of_work', '')}
"""
    elif "会計事務委託契約書②" in contract_name:
        return f"""
【会計事務委託条件（一般社団法人）】
  月額報酬:       {ctx.get('monthly_fee', '')}
  業務範囲:       {ctx.get('scope_of_work', '')}
"""
    else:
        return ""


def _build_mapper_html(simulation, stakeholders, sh_map, templates, contracts, rsj):
    """Build the visual scheme mapper HTML."""
    sim_id = simulation["id"]

    # Role definitions for the scheme
    roles = [
        ("investor", "投資家", "#10b981", ""),
        ("spc", "SPC", "#2563eb", ""),
        ("operator", "カーチス", "#f59e0b", ""),
        ("end_user", "運送事業者", "#8b5cf6", ""),
        ("private_placement_agent", "私募取扱業者", "#ec4899", ""),
        ("asset_manager", "アセットマネージャー", "#06b6d4", ""),
        ("accounting_firm", "会計事務所", "#84cc16", ""),
        ("accounting_delegate", "会計事務委託先", "#f97316", ""),
        ("guarantor", "保証人", "#64748b", ""),
        ("trustee", "受託者", "#a855f7", ""),
    ]

    # Build stakeholder cards
    cards_html = ""
    for role_key, role_label, color, _ in roles:
        sh = sh_map.get(role_key, {})
        filled = bool(sh.get("company_name"))
        status_badge = f'<span class="badge badge--success" style="font-size:0.7rem">登録済</span>' if filled else f'<span class="badge badge--warning" style="font-size:0.7rem">未登録</span>'

        cards_html += f'''
        <div class="card" style="border-left: 4px solid {color}; margin-bottom: 16px;">
            <div class="card__header" style="display:flex;justify-content:space-between;align-items:center">
                <h4 style="margin:0">{role_label} {status_badge}</h4>
            </div>
            <div class="card__body">
                <!-- Address Book Selector -->
                <div class="form-group" style="margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid var(--border,#334155)">
                    <label class="form-label" style="font-size:0.8rem;color:var(--text-muted)">📒 アドレス帳から選択</label>
                    <select class="form-select" onchange="fillFromAddressbook(this, \'{role_key}\')" id="addressbook-{role_key}">
                        <option value="">-- アドレス帳から選択 --</option>
                    </select>
                    <script>
                    fetch('/api/v1/contracts/addressbook/options/{role_key}')
                        .then(r => r.text())
                        .then(html => document.getElementById('addressbook-{role_key}').innerHTML = html);
                    </script>
                </div>

                <form hx-post="/api/v1/contracts/stakeholders" hx-target="#save-result-{role_key}" hx-swap="innerHTML">
                    <input type="hidden" name="simulation_id" value="{sim_id}">
                    <input type="hidden" name="role_type" value="{role_key}">
                    <input type="hidden" name="stakeholder_id" value="{sh.get('id', '')}">
                    <div class="form-row">
                        <div class="form-group">
                            <label class="form-label">法人名 *</label>
                            <input type="text" name="company_name" class="form-input" value="{sh.get('company_name', '')}" required placeholder="例: 株式会社カーチス">
                        </div>
                        <div class="form-group">
                            <label class="form-label">代表者名</label>
                            <input type="text" name="representative_name" class="form-input" value="{sh.get('representative_name', '')}" placeholder="例: 山田太郎">
                        </div>
                    </div>
                    <div class="form-group">
                        <label class="form-label">住所</label>
                        <input type="text" name="address" class="form-input" value="{sh.get('address', '')}" placeholder="例: 東京都千代田区...">
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label class="form-label">電話番号</label>
                            <input type="text" name="phone" class="form-input" value="{sh.get('phone', '')}" placeholder="03-xxxx-xxxx">
                        </div>
                        <div class="form-group">
                            <label class="form-label">法人番号</label>
                            <input type="text" name="registration_number" class="form-input" value="{sh.get('registration_number', '')}" placeholder="1234567890123">
                        </div>
                    </div>
                    <div style="display:flex;gap:8px;align-items:center;margin-top:8px">
                        <button type="submit" class="btn btn--primary btn--sm">保存</button>
                        <button type="button" class="btn btn--outline btn--sm" onclick="saveToAddressbook(\'{role_key}\')">📒 アドレス帳に追加</button>
                        <div id="save-result-{role_key}"></div>
                        <div id="ab-save-result-{role_key}"></div>
                    </div>
                </form>
            </div>
        </div>
        '''

    # Contract flow SVG - large, bold, full-width
    svg_html = '''
    <svg viewBox="0 0 1000 420" style="width:100%;min-height:320px;display:block" xmlns="http://www.w3.org/2000/svg">
        <defs>
            <marker id="arrowhead" markerWidth="12" markerHeight="9" refX="11" refY="4.5" orient="auto">
                <polygon points="0 0, 12 4.5, 0 9" fill="#94a3b8"/>
            </marker>
            <marker id="arrowhead-green" markerWidth="12" markerHeight="9" refX="11" refY="4.5" orient="auto">
                <polygon points="0 0, 12 4.5, 0 9" fill="#10b981"/>
            </marker>
            <marker id="arrowhead-blue" markerWidth="12" markerHeight="9" refX="11" refY="4.5" orient="auto">
                <polygon points="0 0, 12 4.5, 0 9" fill="#2563eb"/>
            </marker>
            <filter id="shadow" x="-5%" y="-5%" width="110%" height="110%">
                <feDropShadow dx="2" dy="3" stdDeviation="4" flood-opacity="0.15"/>
            </filter>
        </defs>

        <!-- Title -->
        <text x="500" y="30" text-anchor="middle" fill="#e2e8f0" font-size="18" font-weight="700" letter-spacing="2">リースバック・スキーム構造</text>

        <!-- ===== TOP ROW: 4 Stakeholder Nodes ===== -->

        <!-- Investor -->
        <rect x="30" y="60" width="200" height="90" rx="16" fill="#10b981" opacity="0.12" stroke="#10b981" stroke-width="3" filter="url(#shadow)"/>
        <text x="130" y="100" text-anchor="middle" fill="#10b981" font-size="22" font-weight="700">投資家</text>
        <text x="130" y="125" text-anchor="middle" fill="#6ee7b7" font-size="13">Investor</text>

        <!-- SPC -->
        <rect x="280" y="60" width="200" height="90" rx="16" fill="#2563eb" opacity="0.12" stroke="#2563eb" stroke-width="3" filter="url(#shadow)"/>
        <text x="380" y="100" text-anchor="middle" fill="#60a5fa" font-size="22" font-weight="700">SPC</text>
        <text x="380" y="125" text-anchor="middle" fill="#93c5fd" font-size="13">特別目的会社</text>

        <!-- Carchs -->
        <rect x="530" y="60" width="200" height="90" rx="16" fill="#f59e0b" opacity="0.12" stroke="#f59e0b" stroke-width="3" filter="url(#shadow)"/>
        <text x="630" y="100" text-anchor="middle" fill="#fbbf24" font-size="22" font-weight="700">カーチス</text>
        <text x="630" y="125" text-anchor="middle" fill="#fcd34d" font-size="13">Operator / Asset Manager</text>

        <!-- Transport Company -->
        <rect x="780" y="60" width="200" height="90" rx="16" fill="#8b5cf6" opacity="0.12" stroke="#8b5cf6" stroke-width="3" filter="url(#shadow)"/>
        <text x="880" y="100" text-anchor="middle" fill="#a78bfa" font-size="22" font-weight="700">運送事業者</text>
        <text x="880" y="125" text-anchor="middle" fill="#c4b5fd" font-size="13">End User / Lessee</text>

        <!-- ===== ARROWS between nodes ===== -->

        <!-- Investor → SPC (TK Agreement) -->
        <line x1="230" y1="105" x2="280" y2="105" stroke="#10b981" stroke-width="3" marker-end="url(#arrowhead-green)"/>
        <rect x="232" y="70" width="68" height="24" rx="6" fill="#10b981" opacity="0.2"/>
        <text x="266" y="87" text-anchor="middle" fill="#10b981" font-size="12" font-weight="600">TK契約</text>

        <!-- SPC → Carchs (Master Lease) -->
        <line x1="480" y1="105" x2="530" y2="105" stroke="#2563eb" stroke-width="3" marker-end="url(#arrowhead-blue)"/>
        <rect x="481" y="70" width="68" height="24" rx="6" fill="#2563eb" opacity="0.2"/>
        <text x="515" y="87" text-anchor="middle" fill="#60a5fa" font-size="12" font-weight="600">ML契約</text>

        <!-- Carchs → Transport (Sublease) -->
        <line x1="730" y1="105" x2="780" y2="105" stroke="#f59e0b" stroke-width="3" marker-end="url(#arrowhead)"/>
        <rect x="731" y="70" width="68" height="24" rx="6" fill="#f59e0b" opacity="0.2"/>
        <text x="765" y="87" text-anchor="middle" fill="#fbbf24" font-size="12" font-weight="600">SL契約</text>

        <!-- ===== BOTTOM: Sale + Cash flows ===== -->

        <!-- Sale arrow: Transport → SPC (curved bottom) -->
        <path d="M 880 150 L 880 250 Q 880 280 850 280 L 410 280 Q 380 280 380 250 L 380 150" stroke="#8b5cf6" stroke-width="2.5" stroke-dasharray="8,4" fill="none" marker-end="url(#arrowhead)"/>
        <rect x="560" y="265" width="120" height="30" rx="8" fill="#8b5cf6" opacity="0.15"/>
        <text x="620" y="285" text-anchor="middle" fill="#a78bfa" font-size="14" font-weight="600">車両売買契約</text>

        <!-- Cash flow: SPC → Transport (instant cash) -->
        <path d="M 380 150 L 380 200 Q 380 220 400 220 L 860 220 Q 880 220 880 200 L 880 150" stroke="#10b981" stroke-width="2" stroke-dasharray="6,3" fill="none" marker-end="url(#arrowhead-green)"/>
        <rect x="560" y="205" width="100" height="26" rx="8" fill="#10b981" opacity="0.12"/>
        <text x="610" y="223" text-anchor="middle" fill="#6ee7b7" font-size="12" font-weight="500">即時現金化</text>

        <!-- ===== BOTTOM ROW: Flow labels ===== -->

        <text x="130" y="340" text-anchor="middle" fill="#94a3b8" font-size="13">出資金</text>
        <text x="130" y="360" text-anchor="middle" fill="#6ee7b7" font-size="15" font-weight="600">↑ 安定利回り</text>

        <text x="380" y="340" text-anchor="middle" fill="#94a3b8" font-size="13">車両保有</text>
        <text x="380" y="360" text-anchor="middle" fill="#60a5fa" font-size="15" font-weight="600">資産管理</text>

        <text x="630" y="340" text-anchor="middle" fill="#94a3b8" font-size="13">管理手数料</text>
        <text x="630" y="360" text-anchor="middle" fill="#fbbf24" font-size="15" font-weight="600">運営・仲介</text>

        <text x="880" y="340" text-anchor="middle" fill="#94a3b8" font-size="13">車両利用継続</text>
        <text x="880" y="360" text-anchor="middle" fill="#a78bfa" font-size="15" font-weight="600">オフバランス化</text>

        <!-- Legend -->
        <rect x="30" y="390" width="940" height="1" fill="#334155"/>
        <text x="50" y="412" fill="#64748b" font-size="11">━ 契約関係　┅ 資金・車両フロー　TK=匿名組合　ML=マスターリース　SL=サブリース</text>
    </svg>
    '''

    # Contract templates list
    templates_html = ""
    for t in templates:
        required = t.get("required_roles", {})
        pa = _role_label(required.get("party_a", ""))
        pb = _role_label(required.get("party_b", ""))
        templates_html += f'''
        <tr>
            <td>{t['contract_name']}</td>
            <td>{pa}</td>
            <td>{pb}</td>
            <td>{t.get('description', '')}</td>
        </tr>
        '''

    # Generated contracts history
    history_html = ""
    for c in contracts[:5]:
        status_class = {"draft":"warning","generated":"success","signed":"success"}.get(c["status"], "")
        history_html += f'''
        <tr>
            <td>{c['contract_name']}</td>
            <td><span class="badge badge--{status_class}">{c['status']}</span></td>
            <td>{(c.get('generated_at') or '')[:10]}</td>
        </tr>
        '''

    rsj_info = f"{rsj.get('maker','')} {rsj.get('model','')}" if rsj else ""

    return f'''
    <div class="page-header">
        <h2>契約書管理 — ビジュアル・スキーム・マッパー</h2>
        <p class="text-muted">{simulation.get('title', '')} | {rsj_info}</p>
    </div>

    <!-- Scheme Flow Diagram -->
    <div class="card">
        <div class="card__header"><h3>スキーム構造図</h3></div>
        <div class="card__body" style="text-align:center">
            {svg_html}
        </div>
    </div>

    <!-- Simulation Summary -->
    <div class="card" style="margin-top:16px">
        <div class="card__header"><h3>シミュレーション情報（自動転記）</h3></div>
        <div class="card__body">
            <div class="kpi-grid">
                <div class="kpi-card"><div class="kpi-card__label">買取価格</div><div class="kpi-card__value">¥{simulation.get('purchase_price_yen',0):,}</div></div>
                <div class="kpi-card"><div class="kpi-card__label">月額リース料</div><div class="kpi-card__value">¥{simulation.get('lease_monthly_yen',0):,}</div></div>
                <div class="kpi-card"><div class="kpi-card__label">リース期間</div><div class="kpi-card__value">{simulation.get('lease_term_months',0)}ヶ月</div></div>
                <div class="kpi-card"><div class="kpi-card__label">利回り</div><div class="kpi-card__value">{(simulation.get('expected_yield_rate',0) or 0)*100:.1f}%</div></div>
            </div>
        </div>
    </div>

    <!-- Stakeholder Forms -->
    <div class="card" style="margin-top:16px">
        <div class="card__header"><h3>ステークホルダー情報入力</h3></div>
        <div class="card__body">
            {cards_html}
        </div>
    </div>

    <!-- Contract Templates -->
    <div class="card" style="margin-top:16px">
        <div class="card__header"><h3>対象契約書一覧</h3></div>
        <div class="card__body card__body--flush">
            <table class="data-table">
                <thead><tr><th>契約名</th><th>甲（Party A）</th><th>乙（Party B）</th><th>概要</th></tr></thead>
                <tbody>{templates_html}</tbody>
            </table>
        </div>
    </div>

    <!-- Generate Button -->
    <div style="margin-top:24px;display:flex;gap:16px;align-items:center">
        <form action="/api/v1/contracts/generate/{sim_id}" method="post">
            <button type="submit" class="btn btn--primary btn--lg">📄 全契約書を一括生成（ZIP）</button>
        </form>
        <div id="generate-result"></div>
    </div>

    <!-- History -->
    {"" if not history_html else f"""
    <div class="card" style="margin-top:24px">
        <div class="card__header"><h3>生成済み契約書</h3></div>
        <div class="card__body card__body--flush">
            <table class="data-table">
                <thead><tr><th>契約名</th><th>ステータス</th><th>生成日</th></tr></thead>
                <tbody>{history_html}</tbody>
            </table>
        </div>
    </div>
    """}

    <script>
    function fillFromAddressbook(select, roleKey) {{
        var opt = select.options[select.selectedIndex];
        if (!opt || !opt.dataset.name) return;

        var card = select.closest('.card');
        var form = card.querySelector('form');

        form.querySelector('[name="company_name"]').value = opt.dataset.name || '';
        form.querySelector('[name="representative_name"]').value = opt.dataset.rep || '';
        form.querySelector('[name="address"]').value = opt.dataset.addr || '';
        form.querySelector('[name="phone"]').value = opt.dataset.phone || '';
        form.querySelector('[name="registration_number"]').value = opt.dataset.reg || '';
    }}

    function saveToAddressbook(roleKey) {{
        var card = document.querySelector('#addressbook-' + roleKey).closest('.card');
        var form = card.querySelector('form');
        var formData = new FormData(form);

        fetch('/api/v1/contracts/addressbook/save', {{
            method: 'POST',
            body: formData,
        }})
        .then(r => r.text())
        .then(html => {{
            document.getElementById('ab-save-result-' + roleKey).innerHTML = html;
            // Refresh the dropdown
            fetch('/api/v1/contracts/addressbook/options/' + roleKey)
                .then(r => r.text())
                .then(h => document.getElementById('addressbook-' + roleKey).innerHTML = h);
        }});
    }}
    </script>
    '''
