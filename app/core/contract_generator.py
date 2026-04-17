"""Contract document generator using docxtpl for variable substitution."""

from __future__ import annotations
from pathlib import Path
from datetime import date
from typing import Optional
import io
import zipfile
import shutil
import structlog

try:
    from docxtpl import DocxTemplate  # type: ignore
    HAS_DOCXTPL = True
except ImportError:  # pragma: no cover - deploy-time defensive guard
    DocxTemplate = None  # type: ignore
    HAS_DOCXTPL = False

try:
    from docx import Document  # type: ignore
    HAS_PYTHON_DOCX = True
except ImportError:  # pragma: no cover - deploy-time defensive guard
    Document = None  # type: ignore
    HAS_PYTHON_DOCX = False

logger = structlog.get_logger()

TEMPLATE_DIR = Path(__file__).parent.parent.parent / "templates" / "contracts"


class ContractGenerator:
    """Generates contract documents by filling DOCX templates with data."""

    # Template filename mapping
    TEMPLATES = {
        "tk_agreement": "tk_agreement.docx",
        "sales_agreement": "sales_agreement.docx",
        "master_lease": "master_lease.docx",
        "sublease_agreement": "sublease_agreement.docx",
        "private_placement": "private_placement_agreement.docx",
        "customer_referral": "customer_referral_agreement.docx",
        "asset_management": "asset_management_agreement.docx",
        "accounting_firm": "accounting_services_firm.docx",
        "accounting_association": "accounting_services_association.docx",
    }

    # Party role mapping: contract_type -> (party_a_role, party_b_role)
    PARTY_MAPPING = {
        "tk_agreement": ("spc", "investor"),
        "sales_agreement": ("end_user", "spc"),
        "master_lease": ("spc", "operator"),
        "sublease_agreement": ("operator", "end_user"),
        "private_placement": ("spc", "private_placement_agent"),
        "customer_referral": ("spc", "asset_manager"),
        "asset_management": ("spc", "asset_manager"),
        "accounting_firm": ("spc", "accounting_firm"),
        "accounting_association": ("spc", "accounting_delegate"),
    }

    # Japanese display names for contract types
    CONTRACT_NAMES = {
        "tk_agreement": "匿名組合契約書",
        "sales_agreement": "車両売買契約書",
        "master_lease": "マスターリース契約書",
        "sublease_agreement": "サブリース契約書",
        "private_placement": "私募取扱業務契約書",
        "customer_referral": "顧客紹介業務契約書",
        "asset_management": "アセットマネジメント契約書",
        "accounting_firm": "会計事務委託契約書①（会計事務所）",
        "accounting_association": "会計事務委託契約書②（一般社団法人）",
    }

    def __init__(self, template_dir: Optional[Path] = None):
        self.template_dir = template_dir or TEMPLATE_DIR

    def _get_template_path(self, contract_type: str) -> Optional[Path]:
        """Resolve the template file path, returning None if not found."""
        filename = self.TEMPLATES.get(contract_type)
        if not filename:
            logger.warning("unknown_contract_type", contract_type=contract_type)
            return None
        path = self.template_dir / filename
        if not path.exists():
            logger.warning("template_not_found", path=str(path))
            return None
        return path

    def generate_contract(self, contract_type: str, context: dict) -> bytes:
        """Generate a single contract DOCX with variables filled in.

        Args:
            contract_type: Key from TEMPLATES dict
            context: Dict of variables to substitute

        Returns:
            DOCX file bytes

        Raises:
            FileNotFoundError: If the template file does not exist.
        """
        template_path = self._get_template_path(contract_type)
        if template_path is None:
            raise FileNotFoundError(
                f"Template not found for contract type '{contract_type}'"
            )

        if HAS_DOCXTPL:
            return self._render_with_docxtpl(template_path, context)

        # docxtpl missing: attempt a safe fallback (plain copy of template
        # with no variable substitution). If even that fails we raise a
        # clean RuntimeError rather than leaking ImportError to the caller.
        logger.warning(
            "docxtpl_not_installed",
            has_python_docx=HAS_PYTHON_DOCX,
            message="Falling back to plain DOCX copy without variable substitution",
        )
        try:
            return self._copy_template(template_path)
        except Exception as exc:  # pragma: no cover - defensive
            raise RuntimeError(
                "Contract generation is unavailable: the 'docxtpl' package "
                "is not installed in this deployment. Please add 'docxtpl' "
                "(and 'python-docx') to the runtime dependencies."
            ) from exc

    def generate_all_contracts(
        self,
        stakeholders: dict,
        pricing_result: dict,
        fund_info: dict,
    ) -> bytes:
        """Generate all applicable contracts as a ZIP file.

        A contract is considered applicable when both party_a and party_b
        stakeholders have a non-empty ``company_name``.

        Args:
            stakeholders: Dict of role_type -> stakeholder data
            pricing_result: Pricing / simulation result data
            fund_info: Fund information (fund_name, etc.)

        Returns:
            ZIP file bytes containing all generated DOCXs
        """
        zip_buffer = io.BytesIO()
        generated_count = 0

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for contract_type in self.TEMPLATES:
                party_a_role, party_b_role = self.PARTY_MAPPING.get(
                    contract_type, ("spc", "operator")
                )
                party_a = stakeholders.get(party_a_role, {})
                party_b = stakeholders.get(party_b_role, {})

                # Skip if either party is not registered
                if not party_a.get("company_name") or not party_b.get("company_name"):
                    logger.info(
                        "skipping_contract",
                        contract_type=contract_type,
                        reason="missing_party",
                        party_a_role=party_a_role,
                        party_b_role=party_b_role,
                    )
                    continue

                context = self._build_context(
                    contract_type, stakeholders, pricing_result, fund_info
                )

                try:
                    docx_bytes = self.generate_contract(contract_type, context)
                except FileNotFoundError:
                    logger.warning(
                        "template_missing_skip",
                        contract_type=contract_type,
                    )
                    continue

                display_name = self.CONTRACT_NAMES.get(contract_type, contract_type)
                filename = f"{display_name}.docx"
                zf.writestr(filename, docx_bytes)
                generated_count += 1
                logger.info("contract_generated", contract_type=contract_type)

        logger.info("all_contracts_generated", count=generated_count)
        zip_buffer.seek(0)
        return zip_buffer.getvalue()

    # ------------------------------------------------------------------
    # Context building
    # ------------------------------------------------------------------

    def _build_context(
        self,
        contract_type: str,
        stakeholders: dict,
        pricing_result: dict,
        fund_info: dict,
    ) -> dict:
        """Build template context (variable mapping) for a specific contract type."""

        today_str = date.today().strftime("%Y年%m月%d日")

        # --- Common variables ---
        ctx: dict = {
            "contract_date": today_str,
            "effective_date": today_str,
            "fund_name": fund_info.get("fund_name", ""),
        }

        # --- Party variables ---
        party_a_role, party_b_role = self.PARTY_MAPPING.get(
            contract_type, ("spc", "operator")
        )
        party_a = stakeholders.get(party_a_role, {})
        party_b = stakeholders.get(party_b_role, {})

        ctx["party_a_name"] = party_a.get("company_name", "")
        ctx["party_a_address"] = party_a.get("address", "")
        ctx["party_a_representative"] = party_a.get("representative_name", "")
        ctx["party_b_name"] = party_b.get("company_name", "")
        ctx["party_b_address"] = party_b.get("address", "")
        ctx["party_b_representative"] = party_b.get("representative_name", "")

        # --- Vehicle variables ---
        ctx["vehicle_maker"] = pricing_result.get("maker", "")
        ctx["vehicle_model"] = pricing_result.get("model", "")
        ctx["vehicle_body_type"] = pricing_result.get("body_type", "")
        ctx["vehicle_year"] = pricing_result.get("vehicle_year", "")
        ctx["vehicle_mileage"] = self._fmt_mileage(
            pricing_result.get("target_mileage_km", 0)
        )
        ctx["vehicle_chassis_number"] = pricing_result.get(
            "vehicle_chassis_number", ""
        )
        ctx["vehicle_registration_number"] = pricing_result.get(
            "vehicle_registration_number", ""
        )

        # --- Pricing variables ---
        purchase_price = pricing_result.get("purchase_price_yen", 0)
        monthly_lease = pricing_result.get("lease_monthly_yen", 0)
        lease_term = pricing_result.get("lease_term_months", 0)
        total_lease = pricing_result.get("total_lease_revenue_yen", 0)

        ctx["purchase_price"] = f"{purchase_price:,}"
        ctx["purchase_price_num"] = purchase_price
        ctx["monthly_lease_fee"] = f"{monthly_lease:,}"
        ctx["monthly_lease_fee_num"] = monthly_lease
        ctx["lease_term_months"] = lease_term
        ctx["total_lease_revenue"] = f"{total_lease:,}"
        ctx["target_yield_rate"] = pricing_result.get("target_yield_rate", "")

        # Lease dates
        ctx["lease_start_date"] = pricing_result.get("lease_start_date", today_str)
        ctx["lease_end_date"] = pricing_result.get("lease_end_date", "")
        ctx["payment_day"] = pricing_result.get("payment_day", "末")

        # Sublease fee (may differ from master lease fee)
        ctx["sublease_fee"] = f"{pricing_result.get('sublease_fee_yen', monthly_lease):,}"

        # Warranty
        ctx["warranty_months"] = pricing_result.get("warranty_months", 3)

        # Payment bank details
        ctx["payment_bank_name"] = pricing_result.get("payment_bank_name", "")
        ctx["payment_branch_name"] = pricing_result.get("payment_branch_name", "")
        ctx["payment_account_type"] = pricing_result.get("payment_account_type", "普通")
        ctx["payment_account_number"] = pricing_result.get(
            "payment_account_number", ""
        )

        # --- Contract-type specific variables ---
        self._add_type_specific_vars(ctx, contract_type, pricing_result, fund_info)

        return ctx

    def _add_type_specific_vars(
        self,
        ctx: dict,
        contract_type: str,
        pricing_result: dict,
        fund_info: dict,
    ) -> None:
        """Mutate *ctx* in place, adding variables specific to a contract type."""

        purchase_price = pricing_result.get("purchase_price_yen", 0)

        if contract_type == "private_placement":
            fee_rate = pricing_result.get("placement_fee_rate", "3.0%")
            ctx["placement_fee_rate"] = fee_rate
            ctx["total_amount"] = f"{purchase_price:,}"
            ctx["total_placement_amount"] = f"{purchase_price:,}"
            # Calculate fee amount from rate
            try:
                rate_num = float(str(fee_rate).replace("%", "")) / 100
                ctx["placement_fee_amount"] = f"{int(purchase_price * rate_num):,}"
            except (ValueError, TypeError):
                ctx["placement_fee_amount"] = ""

        elif contract_type == "customer_referral":
            ctx["referral_fee_rate"] = pricing_result.get(
                "referral_fee_rate", "1.0%"
            )

        elif contract_type == "asset_management":
            am_fee_rate = pricing_result.get("am_fee_rate", "2.0%")
            ctx["am_fee_rate"] = am_fee_rate
            ctx["managed_assets_value"] = f"{purchase_price:,}"
            try:
                rate_num = float(str(am_fee_rate).replace("%", "")) / 100
                ctx["am_fee_amount"] = f"{int(purchase_price * rate_num):,}"
            except (ValueError, TypeError):
                ctx["am_fee_amount"] = ""

        elif contract_type in ("accounting_firm", "accounting_association"):
            ctx["monthly_fee"] = pricing_result.get("monthly_fee", "¥50,000")
            ctx["scope_of_work"] = pricing_result.get(
                "scope_of_work", "記帳代行、決算書作成、税務申告"
            )

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _render_with_docxtpl(template_path: Path, context: dict) -> bytes:
        """Render a DOCX template using docxtpl and return file bytes."""
        doc = DocxTemplate(str(template_path))
        doc.render(context)
        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        return buf.getvalue()

    @staticmethod
    def _copy_template(template_path: Path) -> bytes:
        """Return a raw copy of the template (no substitution)."""
        return template_path.read_bytes()

    @staticmethod
    def _fmt_mileage(km) -> str:
        try:
            return f"{int(km):,}km"
        except (ValueError, TypeError):
            return str(km) if km else ""
