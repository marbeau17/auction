"""Fixture fallback for vehicle master data (makers / models / body_types / categories).

Called from route handlers (see ``app/api/pages.py::simulation_new_page`` and
``app/api/masters.py`` endpoints) when the Supabase tables are empty or the
query raises. The shapes here mirror what the templates consume — see
``app/templates/pages/simulation.html`` for the canonical reference.

Data covers the four dominant Japanese commercial-vehicle OEMs with 3–4 models
each (light-truck / medium-truck / heavy-truck tiers) plus the common body
types and class buckets. IDs are hardcoded stable strings so repeated restarts
stay referentially consistent (HTMX chaining + prefill rely on this).
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Makers
# ---------------------------------------------------------------------------

_MAKERS: list[dict] = [
    {
        "id": "maker-isuzu-001",
        "name": "いすゞ",
        "name_en": "Isuzu",
        "code": "ISUZU",
        "display_order": 1,
        "is_active": True,
    },
    {
        "id": "maker-hino-002",
        "name": "日野",
        "name_en": "Hino",
        "code": "HINO",
        "display_order": 2,
        "is_active": True,
    },
    {
        "id": "maker-fuso-003",
        "name": "三菱ふそう",
        "name_en": "Mitsubishi Fuso",
        "code": "FUSO",
        "display_order": 3,
        "is_active": True,
    },
    {
        "id": "maker-toyota-004",
        "name": "トヨタ",
        "name_en": "Toyota",
        "code": "TOYOTA",
        "display_order": 4,
        "is_active": True,
    },
]


def get_makers() -> list[dict]:
    """Return list of {id, name, name_en, code, display_order, is_active}."""
    return [dict(m) for m in _MAKERS]


# ---------------------------------------------------------------------------
# Models (per maker)
# ---------------------------------------------------------------------------

# body_type values align with get_body_types().name so repositories that store
# body_type as a human label stay compatible.
_MODELS_BY_MAKER: dict[str, list[dict]] = {
    "いすゞ": [
        {
            "id": "model-isuzu-elf-001",
            "name": "エルフ",
            "maker_name": "いすゞ",
            "model_code": "ELF",
            "body_type": "平ボディ",
        },
        {
            "id": "model-isuzu-forward-002",
            "name": "フォワード",
            "maker_name": "いすゞ",
            "model_code": "FORWARD",
            "body_type": "ウイング",
        },
        {
            "id": "model-isuzu-giga-003",
            "name": "ギガ",
            "maker_name": "いすゞ",
            "model_code": "GIGA",
            "body_type": "ウイング",
        },
    ],
    "日野": [
        {
            "id": "model-hino-dutro-001",
            "name": "デュトロ",
            "maker_name": "日野",
            "model_code": "DUTRO",
            "body_type": "平ボディ",
        },
        {
            "id": "model-hino-ranger-002",
            "name": "レンジャー",
            "maker_name": "日野",
            "model_code": "RANGER",
            "body_type": "ウイング",
        },
        {
            "id": "model-hino-profia-003",
            "name": "プロフィア",
            "maker_name": "日野",
            "model_code": "PROFIA",
            "body_type": "ウイング",
        },
    ],
    "三菱ふそう": [
        {
            "id": "model-fuso-canter-001",
            "name": "キャンター",
            "maker_name": "三菱ふそう",
            "model_code": "CANTER",
            "body_type": "平ボディ",
        },
        {
            "id": "model-fuso-fighter-002",
            "name": "ファイター",
            "maker_name": "三菱ふそう",
            "model_code": "FIGHTER",
            "body_type": "ウイング",
        },
        {
            "id": "model-fuso-supergreat-003",
            "name": "スーパーグレート",
            "maker_name": "三菱ふそう",
            "model_code": "SUPER_GREAT",
            "body_type": "ウイング",
        },
    ],
    "トヨタ": [
        {
            "id": "model-toyota-dyna-001",
            "name": "ダイナ",
            "maker_name": "トヨタ",
            "model_code": "DYNA",
            "body_type": "平ボディ",
        },
        {
            "id": "model-toyota-hiace-002",
            "name": "ハイエース",
            "maker_name": "トヨタ",
            "model_code": "HIACE",
            "body_type": "バン",
        },
        {
            "id": "model-toyota-coaster-003",
            "name": "コースター",
            "maker_name": "トヨタ",
            "model_code": "COASTER",
            "body_type": "バン",
        },
    ],
}


def get_models_by_maker(maker_name: str) -> list[dict]:
    """Return list of {id, name, maker_name, model_code, body_type}.

    ``maker_name`` is matched against the Japanese ``name`` column used by the
    template dropdown (see ``simulation.html``). An unknown maker returns an
    empty list — callers fall through to whatever default HTMX placeholder they
    render.
    """
    return [dict(m) for m in _MODELS_BY_MAKER.get(maker_name, [])]


# ---------------------------------------------------------------------------
# Body types
# ---------------------------------------------------------------------------

_BODY_TYPES: list[dict] = [
    {
        "id": "body-flat-001",
        "name": "平ボディ",
        "code": "FLAT",
        "category_id": "cat-medium-002",
    },
    {
        "id": "body-wing-002",
        "name": "ウイング",
        "code": "WING",
        "category_id": "cat-large-003",
    },
    {
        "id": "body-van-003",
        "name": "バン",
        "code": "VAN",
        "category_id": "cat-small-001",
    },
    {
        "id": "body-refrigerated-004",
        "name": "冷凍車",
        "code": "REFRIGERATED",
        "category_id": "cat-medium-002",
    },
    {
        "id": "body-dump-005",
        "name": "ダンプ",
        "code": "DUMP",
        "category_id": "cat-medium-002",
    },
    {
        "id": "body-tank-006",
        "name": "タンク",
        "code": "TANK",
        "category_id": "cat-large-003",
    },
]


def get_body_types() -> list[dict]:
    """Return list of {id, name, code, category_id}."""
    return [dict(b) for b in _BODY_TYPES]


# ---------------------------------------------------------------------------
# Categories (vehicle class buckets)
# ---------------------------------------------------------------------------

_CATEGORIES: list[dict] = [
    {"id": "cat-small-001", "name": "小型", "code": "SMALL"},
    {"id": "cat-medium-002", "name": "中型", "code": "MEDIUM"},
    {"id": "cat-large-003", "name": "大型", "code": "LARGE"},
]


def get_categories() -> list[dict]:
    """Return list of {id, name, code}."""
    return [dict(c) for c in _CATEGORIES]
