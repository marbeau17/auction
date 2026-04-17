"""Repository for deal stakeholders and address book."""

from __future__ import annotations
from typing import Optional
from uuid import UUID

import structlog
from supabase import Client

logger = structlog.get_logger()

# All valid role types
VALID_ROLE_TYPES = [
    'spc', 'operator', 'investor', 'end_user', 'guarantor', 'trustee',
    'private_placement_agent', 'asset_manager', 'accounting_firm', 'accounting_delegate'
]

ROLE_TYPE_LABELS = {
    'spc': 'SPC（合同会社/営業者）',
    'operator': '賃借人兼車両管理事業者',
    'investor': '投資家（匿名組合員）',
    'end_user': 'エンドユーザー（運送会社）',
    'guarantor': '保証人',
    'trustee': '受託者',
    'private_placement_agent': '私募取扱業者',
    'asset_manager': 'アセットマネージャー',
    'accounting_firm': '会計事務所',
    'accounting_delegate': '会計事務委託先',
}


class StakeholderRepository:
    """CRUD for deal_stakeholders with address book support."""

    TABLE = "deal_stakeholders"

    def __init__(self, supabase: Client):
        self.supabase = supabase

    async def list_by_simulation(self, simulation_id: UUID) -> list[dict]:
        """Get all stakeholders for a simulation/deal."""
        result = self.supabase.table(self.TABLE).select("*").eq("simulation_id", str(simulation_id)).order("display_order").execute()
        return result.data

    async def get_by_id(self, stakeholder_id: UUID) -> Optional[dict]:
        result = self.supabase.table(self.TABLE).select("*").eq("id", str(stakeholder_id)).single().execute()
        return result.data

    async def get_by_role(self, simulation_id: UUID, role_type: str) -> Optional[dict]:
        """Get stakeholder by role for a simulation."""
        result = self.supabase.table(self.TABLE).select("*").eq("simulation_id", str(simulation_id)).eq("role_type", role_type).limit(1).execute()
        return result.data[0] if result.data else None

    async def create(self, data: dict) -> dict:
        """Create a new stakeholder."""
        if data.get("role_type") not in VALID_ROLE_TYPES:
            raise ValueError(f"Invalid role_type: {data.get('role_type')}")
        result = self.supabase.table(self.TABLE).insert(data).execute()
        return result.data[0]

    async def update(self, stakeholder_id: UUID, data: dict) -> dict:
        result = self.supabase.table(self.TABLE).update(data).eq("id", str(stakeholder_id)).execute()
        return result.data[0]

    async def delete(self, stakeholder_id: UUID) -> bool:
        result = self.supabase.table(self.TABLE).delete().eq("id", str(stakeholder_id)).execute()
        return len(result.data) > 0

    async def bulk_create(self, simulation_id: UUID, stakeholders: list[dict]) -> list[dict]:
        """Create multiple stakeholders at once."""
        for i, s in enumerate(stakeholders):
            s["simulation_id"] = str(simulation_id)
            s["display_order"] = i
        result = self.supabase.table(self.TABLE).insert(stakeholders).execute()
        return result.data

    async def copy_from_simulation(self, source_sim_id: UUID, target_sim_id: UUID) -> list[dict]:
        """Copy stakeholders from one simulation to another (address book reuse)."""
        source = await self.list_by_simulation(source_sim_id)
        copies = []
        for s in source:
            new_s = {k: v for k, v in s.items() if k not in ('id', 'created_at', 'updated_at')}
            new_s["simulation_id"] = str(target_sim_id)
            copies.append(new_s)
        if copies:
            result = self.supabase.table(self.TABLE).insert(copies).execute()
            return result.data
        return []

    async def get_address_book(self) -> list[dict]:
        """Get unique stakeholders across all simulations (address book).
        Returns the most recent entry for each unique company_name + role_type combination.
        """
        result = self.supabase.table(self.TABLE).select("*").order("updated_at", desc=True).execute()
        seen = set()
        unique = []
        for s in result.data:
            key = (s["company_name"], s["role_type"])
            if key not in seen:
                seen.add(key)
                unique.append(s)
        return unique

    async def search_address_book(self, query: str) -> list[dict]:
        """Search stakeholders by company name."""
        result = self.supabase.table(self.TABLE).select("*").ilike("company_name", f"%{query}%").order("updated_at", desc=True).execute()
        seen = set()
        unique = []
        for s in result.data:
            key = (s["company_name"], s["role_type"])
            if key not in seen:
                seen.add(key)
                unique.append(s)
        return unique

    def get_role_label(self, role_type: str) -> str:
        """Get Japanese label for a role type."""
        return ROLE_TYPE_LABELS.get(role_type, role_type)

    def get_all_role_types(self) -> list[dict]:
        """Get all role types with labels."""
        return [{"value": k, "label": v} for k, v in ROLE_TYPE_LABELS.items()]
