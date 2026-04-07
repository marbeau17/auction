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

logger = structlog.get_logger()
router = APIRouter(prefix="/api/v1/contracts", tags=["contracts"])


def _get_client():
    from app.db.supabase_client import get_supabase_client
    return get_supabase_client(service_role=True)


# GET /api/v1/contracts/mapper/{simulation_id}
@router.get("/mapper/{simulation_id}")
async def get_contract_mapper(simulation_id: str, request: Request):
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
async def save_stakeholder(request: Request):
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


# POST /api/v1/contracts/generate/{simulation_id}
@router.post("/generate/{simulation_id}")
async def generate_contracts(simulation_id: str, request: Request):
    """Generate all contract documents for a simulation."""
    client = _get_client()

    # Fetch all data
    sim = client.table("simulations").select("*").eq("id", simulation_id).maybe_single().execute()
    if not sim.data:
        return JSONResponse({"error": "Simulation not found"}, status_code=404)
    simulation = sim.data
    rsj = simulation.get("result_summary_json") or {}

    sh = client.table("deal_stakeholders").select("*").eq("simulation_id", simulation_id).execute()
    stakeholders = {s["role_type"]: s for s in (sh.data or [])}

    ct = client.table("contract_templates").select("*").eq("is_active", True).order("display_order").execute()
    templates = ct.data or []

    if not stakeholders:
        return HTMLResponse('<div class="alert alert--error">ステークホルダー情報を先に登録してください</div>')

    # Build context for templates
    context = _build_template_context(simulation, rsj, stakeholders)

    # Generate HTML contracts (since we don't have actual .docx templates, generate HTML→text)
    generated_docs = []
    for tmpl in templates:
        required = tmpl.get("required_roles", {})
        party_a_role = required.get("party_a", "")
        party_b_role = required.get("party_b", "")

        party_a = stakeholders.get(party_a_role, {})
        party_b = stakeholders.get(party_b_role, {})

        if not party_a.get("company_name") or not party_b.get("company_name"):
            continue

        doc_context = {
            **context,
            "party_a_name": party_a.get("company_name", ""),
            "party_a_representative": party_a.get("representative_name", ""),
            "party_a_address": party_a.get("address", ""),
            "party_b_name": party_b.get("company_name", ""),
            "party_b_representative": party_b.get("representative_name", ""),
            "party_b_address": party_b.get("address", ""),
            "contract_name": tmpl["contract_name"],
            "contract_date": datetime.now().strftime("%Y年%m月%d日"),
        }

        # Save to deal_contracts
        try:
            dc_data = {
                "simulation_id": simulation_id,
                "template_id": tmpl["id"],
                "contract_name": tmpl["contract_name"],
                "status": "generated",
                "generated_context": doc_context,
                "generated_at": datetime.utcnow().isoformat(),
            }
            client.table("deal_contracts").insert(dc_data).execute()
        except Exception:
            pass

        generated_docs.append({
            "name": tmpl["contract_name"],
            "context": doc_context,
        })

    if not generated_docs:
        return HTMLResponse('<div class="alert alert--error">生成可能な契約書がありません。全ステークホルダーの情報を入力してください。</div>')

    # Generate ZIP with text contracts
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for doc in generated_docs:
            content = _render_contract_text(doc["name"], doc["context"])
            filename = f"{doc['name']}_{simulation_id[:8]}.txt"
            zf.writestr(filename, content)

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="contracts_{simulation_id[:8]}.zip"'}
    )


# --- Helper functions ---

def _role_label(role: str) -> str:
    labels = {
        "spc": "SPC（特別目的会社）",
        "operator": "カーチス（オペレーター）",
        "investor": "投資家",
        "end_user": "運送事業者（エンドユーザー）",
        "guarantor": "連帯保証人",
        "trustee": "信託銀行",
    }
    return labels.get(role, role)


def _build_template_context(simulation: dict, rsj: dict, stakeholders: dict) -> dict:
    return {
        "purchase_price": f"¥{simulation.get('purchase_price_yen', 0):,}",
        "purchase_price_num": simulation.get("purchase_price_yen", 0),
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
    }


def _render_contract_text(contract_name: str, ctx: dict) -> str:
    """Render a contract as formatted text."""
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

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

上記条件にて、甲と乙は本契約を締結する。

甲（署名）: ____________________  印

乙（署名）: ____________________  印

{'=' * 60}
"""


def _build_mapper_html(simulation, stakeholders, sh_map, templates, contracts, rsj):
    """Build the visual scheme mapper HTML."""
    sim_id = simulation["id"]

    # Role definitions for the scheme
    roles = [
        ("investor", "投資家", "#10b981", "M 50 20 L 50 80"),
        ("spc", "SPC", "#2563eb", "M 200 50"),
        ("operator", "カーチス", "#f59e0b", "M 350 50"),
        ("end_user", "運送事業者", "#8b5cf6", "M 500 50"),
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
                        <div id="save-result-{role_key}"></div>
                    </div>
                </form>
            </div>
        </div>
        '''

    # Contract flow SVG
    svg_html = '''
    <svg viewBox="0 0 600 180" style="width:100%;max-width:600px;margin:0 auto;display:block" xmlns="http://www.w3.org/2000/svg">
        <!-- Nodes -->
        <rect x="10" y="60" width="120" height="50" rx="8" fill="#10b981" opacity="0.15" stroke="#10b981" stroke-width="2"/>
        <text x="70" y="90" text-anchor="middle" fill="#10b981" font-size="14" font-weight="600">投資家</text>

        <rect x="160" y="60" width="120" height="50" rx="8" fill="#2563eb" opacity="0.15" stroke="#2563eb" stroke-width="2"/>
        <text x="220" y="90" text-anchor="middle" fill="#2563eb" font-size="14" font-weight="600">SPC</text>

        <rect x="310" y="60" width="120" height="50" rx="8" fill="#f59e0b" opacity="0.15" stroke="#f59e0b" stroke-width="2"/>
        <text x="370" y="90" text-anchor="middle" fill="#f59e0b" font-size="14" font-weight="600">カーチス</text>

        <rect x="460" y="60" width="120" height="50" rx="8" fill="#8b5cf6" opacity="0.15" stroke="#8b5cf6" stroke-width="2"/>
        <text x="520" y="90" text-anchor="middle" fill="#8b5cf6" font-size="14" font-weight="600">運送事業者</text>

        <!-- Arrows -->
        <line x1="130" y1="85" x2="160" y2="85" stroke="#666" stroke-width="2" marker-end="url(#arrowhead)"/>
        <text x="145" y="75" text-anchor="middle" fill="#999" font-size="9">TK契約</text>

        <line x1="280" y1="85" x2="310" y2="85" stroke="#666" stroke-width="2" marker-end="url(#arrowhead)"/>
        <text x="295" y="75" text-anchor="middle" fill="#999" font-size="9">ML契約</text>

        <line x1="430" y1="85" x2="460" y2="85" stroke="#666" stroke-width="2" marker-end="url(#arrowhead)"/>
        <text x="445" y="75" text-anchor="middle" fill="#999" font-size="9">SL契約</text>

        <line x1="520" y1="110" x2="220" y2="140" stroke="#666" stroke-width="1.5" stroke-dasharray="5,3" marker-end="url(#arrowhead)"/>
        <text x="370" y="135" text-anchor="middle" fill="#999" font-size="9">売買契約</text>

        <!-- Arrow marker -->
        <defs>
            <marker id="arrowhead" markerWidth="10" markerHeight="7" refX="9" refY="3.5" orient="auto">
                <polygon points="0 0, 10 3.5, 0 7" fill="#666"/>
            </marker>
        </defs>
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
    '''
