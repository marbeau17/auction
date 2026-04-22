"""Subscription-tier enum for 松プラン UI gating.

Spec: docs/uiux_migration_spec.md §5.
Migration: supabase/migrations/20260422000001_add_user_plan.sql.
"""

from __future__ import annotations

from enum import Enum


class UserPlan(str, Enum):
    ume = "ume"                # basic
    take = "take"              # standard (default for new users)
    matsu = "matsu"            # premium (松限定 features)
    enterprise = "enterprise"  # reserved extra capacity


# Numeric rank for >=/<= comparisons.
PLAN_RANK: dict[str, int] = {
    UserPlan.ume.value: 1,
    UserPlan.take.value: 2,
    UserPlan.matsu.value: 3,
    UserPlan.enterprise.value: 4,
}


def plan_rank(plan: str | None) -> int:
    """Return numeric rank for a plan identifier. Unknown plans rank 0."""
    if plan is None:
        return 0
    return PLAN_RANK.get(str(plan), 0)


def meets_plan(user_plan: str | None, required: str) -> bool:
    """True if the user's plan is >= the required tier."""
    return plan_rank(user_plan) >= plan_rank(required)
