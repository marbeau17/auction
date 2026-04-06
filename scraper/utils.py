"""Utility functions for normalizing scraped vehicle data.

All public functions are pure (no side effects) and handle ``None`` /
empty-string inputs gracefully.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

# ======================================================================
# Normalization mapping dicts
# ======================================================================

MAKER_MAP: dict[str, str] = {
    # Japanese truck / commercial vehicle makers
    "いすゞ": "いすゞ",
    "いすず": "いすゞ",
    "イスズ": "いすゞ",
    "ISUZU": "いすゞ",
    "isuzu": "いすゞ",
    "日野": "日野",
    "ヒノ": "日野",
    "HINO": "日野",
    "hino": "日野",
    "三菱": "三菱ふそう",
    "三菱ふそう": "三菱ふそう",
    "ミツビシ": "三菱ふそう",
    "フソウ": "三菱ふそう",
    "FUSO": "三菱ふそう",
    "fuso": "三菱ふそう",
    "MITSUBISHI": "三菱ふそう",
    "mitsubishi": "三菱ふそう",
    "三菱フソウ": "三菱ふそう",
    "UDトラックス": "UDトラックス",
    "UD": "UDトラックス",
    "日産ディーゼル": "UDトラックス",
    "ニッサンディーゼル": "UDトラックス",
    "UD TRUCKS": "UDトラックス",
    "ud trucks": "UDトラックス",
    # Passenger / light commercial
    "トヨタ": "トヨタ",
    "TOYOTA": "トヨタ",
    "toyota": "トヨタ",
    "日産": "日産",
    "ニッサン": "日産",
    "NISSAN": "日産",
    "nissan": "日産",
    "マツダ": "マツダ",
    "MAZDA": "マツダ",
    "mazda": "マツダ",
    "スズキ": "スズキ",
    "SUZUKI": "スズキ",
    "suzuki": "スズキ",
    "ダイハツ": "ダイハツ",
    "DAIHATSU": "ダイハツ",
    "daihatsu": "ダイハツ",
    "ホンダ": "ホンダ",
    "HONDA": "ホンダ",
    "honda": "ホンダ",
    "スバル": "スバル",
    "SUBARU": "スバル",
    "subaru": "スバル",
    # Foreign
    "ベンツ": "メルセデス・ベンツ",
    "メルセデス": "メルセデス・ベンツ",
    "メルセデスベンツ": "メルセデス・ベンツ",
    "メルセデス・ベンツ": "メルセデス・ベンツ",
    "BENZ": "メルセデス・ベンツ",
    "MERCEDES": "メルセデス・ベンツ",
    "ボルボ": "ボルボ",
    "VOLVO": "ボルボ",
    "volvo": "ボルボ",
    "スカニア": "スカニア",
    "SCANIA": "スカニア",
    "scania": "スカニア",
}

MODEL_MAP: dict[str, str] = {
    # いすゞ
    "ギガ": "ギガ",
    "GIGA": "ギガ",
    "giga": "ギガ",
    "フォワード": "フォワード",
    "FORWARD": "フォワード",
    "forward": "フォワード",
    "エルフ": "エルフ",
    "ELF": "エルフ",
    "elf": "エルフ",
    # 日野
    "プロフィア": "プロフィア",
    "PROFIA": "プロフィア",
    "profia": "プロフィア",
    "レンジャー": "レンジャー",
    "RANGER": "レンジャー",
    "ranger": "レンジャー",
    "デュトロ": "デュトロ",
    "DUTRO": "デュトロ",
    "dutro": "デュトロ",
    # 三菱ふそう
    "スーパーグレート": "スーパーグレート",
    "SUPER GREAT": "スーパーグレート",
    "super great": "スーパーグレート",
    "ファイター": "ファイター",
    "FIGHTER": "ファイター",
    "fighter": "ファイター",
    "キャンター": "キャンター",
    "CANTER": "キャンター",
    "canter": "キャンター",
    # UDトラックス
    "クオン": "クオン",
    "QUON": "クオン",
    "quon": "クオン",
    "コンドル": "コンドル",
    "CONDOR": "コンドル",
    "condor": "コンドル",
    "カゼット": "カゼット",
    "KAZET": "カゼット",
    # トヨタ
    "ダイナ": "ダイナ",
    "DYNA": "ダイナ",
    "dyna": "ダイナ",
    "トヨエース": "トヨエース",
    "TOYOACE": "トヨエース",
    "toyoace": "トヨエース",
    "ハイエース": "ハイエース",
    "HIACE": "ハイエース",
    "hiace": "ハイエース",
    "コースター": "コースター",
    "COASTER": "コースター",
    "coaster": "コースター",
    # 日産
    "アトラス": "アトラス",
    "ATLAS": "アトラス",
    "atlas": "アトラス",
    # マツダ
    "タイタン": "タイタン",
    "TITAN": "タイタン",
    "titan": "タイタン",
}

BODY_TYPE_MAP: dict[str, str] = {
    # Large categories
    "平ボディ": "平ボディ",
    "平ボディー": "平ボディ",
    "平ボデー": "平ボディ",
    "平": "平ボディ",
    "フラットボディ": "平ボディ",
    "ウイング": "ウイング",
    "ウィング": "ウイング",
    "ウイングボディ": "ウイング",
    "ウィングボディ": "ウイング",
    "アルミウイング": "アルミウイング",
    "アルミウィング": "アルミウイング",
    "バン": "バン",
    "VAN": "バン",
    "van": "バン",
    "アルミバン": "アルミバン",
    "パネルバン": "パネルバン",
    "冷蔵冷凍車": "冷凍車",
    "冷凍車": "冷凍車",
    "冷蔵車": "冷凍車",
    "冷凍冷蔵車": "冷凍車",
    "保冷車": "保冷車",
    "ダンプ": "ダンプ",
    "ダンプカー": "ダンプ",
    "DUMP": "ダンプ",
    "dump": "ダンプ",
    "クレーン": "クレーン",
    "クレーン付き": "クレーン",
    "クレーン付": "クレーン",
    "ユニック": "クレーン",
    "UNIC": "クレーン",
    "トラクタ": "トラクタ",
    "トラクター": "トラクタ",
    "トラクターヘッド": "トラクタ",
    "トレーラーヘッド": "トラクタ",
    "ヘッド": "トラクタ",
    "セルフローダー": "セルフローダー",
    "セルフローダ": "セルフローダー",
    "セーフティーローダー": "セーフティローダー",
    "セーフティローダー": "セーフティローダー",
    "セーフティローダ": "セーフティローダー",
    "キャリアカー": "キャリアカー",
    "車両運搬車": "キャリアカー",
    "ミキサー": "ミキサー",
    "ミキサ": "ミキサー",
    "コンクリートミキサー": "ミキサー",
    "アジテータ": "ミキサー",
    "塵芥車": "塵芥車",
    "パッカー車": "塵芥車",
    "パッカー": "塵芥車",
    "ゴミ収集車": "塵芥車",
    "タンクローリー": "タンクローリー",
    "タンクローリ": "タンクローリー",
    "タンク車": "タンクローリー",
    "散水車": "散水車",
    "高所作業車": "高所作業車",
    "穴掘建柱車": "穴掘建柱車",
    "バス": "バス",
    "マイクロバス": "マイクロバス",
    "幼児バス": "幼児バス",
    "送迎バス": "送迎バス",
    "観光バス": "観光バス",
    "路線バス": "路線バス",
    "脱着ボディ": "脱着ボディ",
    "アームロール": "脱着ボディ",
    "フックロール": "脱着ボディ",
    "コンテナ専用車": "脱着ボディ",
}


# ======================================================================
# Era (年号) mappings for Japanese calendar conversion
# ======================================================================

_ERA_MAP: dict[str, int] = {
    "R": 2018,   # 令和: R1 = 2019
    "令和": 2018,
    "令": 2018,
    "H": 1988,   # 平成: H1 = 1989
    "平成": 1988,
    "平": 1988,
    "S": 1925,   # 昭和: S1 = 1926
    "昭和": 1925,
    "昭": 1925,
}


# ======================================================================
# Full-width -> Half-width
# ======================================================================

# Build translation table for full-width ASCII -> half-width ASCII
_ZEN2HAN_TABLE = str.maketrans(
    {chr(0xFF01 + i): chr(0x21 + i) for i in range(94)}
)
# Also map full-width space
_ZEN2HAN_TABLE[0x3000] = 0x0020


def zenkaku_to_hankaku(text: str) -> str:
    """Convert full-width (zenkaku) ASCII characters to half-width (hankaku).

    Covers A-Z, a-z, 0-9, punctuation, and full-width space.

    >>> zenkaku_to_hankaku("１２３ＡＢＣ")
    '123ABC'
    """
    if not text:
        return text
    return text.translate(_ZEN2HAN_TABLE)


def clean_text(text: str | None) -> str:
    """Strip, collapse whitespace, and convert zenkaku to hankaku.

    >>> clean_text("  ３ｔ　ダンプ  ")
    '3t ダンプ'
    """
    if not text:
        return ""
    text = zenkaku_to_hankaku(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ======================================================================
# Price normalization
# ======================================================================

def normalize_price(raw: str | None) -> tuple[int | None, bool]:
    """Parse a Japanese price string.

    Returns:
        (price_in_yen, tax_included)

    Examples:
        >>> normalize_price("450万円(税込)")
        (4500000, True)
        >>> normalize_price("450万円(税別)")
        (4500000, False)
        >>> normalize_price("12,500,000円")
        (12500000, False)
        >>> normalize_price("ASK")
        (None, False)
        >>> normalize_price("応談")
        (None, False)
    """
    if not raw:
        return (None, False)

    text = clean_text(raw)

    # Detect tax inclusion
    tax_included = bool(re.search(r"税込|税込み|込み|込", text))

    # Remove everything that isn't a digit or 万
    # First check for 万 (ten-thousand) notation
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*万", text)
    if m:
        num_str = m.group(1).replace(",", "")
        try:
            value = float(num_str) * 10_000
            return (int(value), tax_included)
        except ValueError:
            pass

    # Plain numeric (e.g. "12,500,000円" or "12500000")
    m = re.search(r"([\d,]+)", text)
    if m:
        num_str = m.group(1).replace(",", "")
        try:
            return (int(num_str), tax_included)
        except ValueError:
            pass

    return (None, False)


# ======================================================================
# Mileage normalization
# ======================================================================

def normalize_mileage(raw: str | None) -> int | None:
    """Parse a mileage string.

    Examples:
        >>> normalize_mileage("18.5万km")
        185000
        >>> normalize_mileage("185,000km")
        185000
        >>> normalize_mileage("不明")
        None
    """
    if not raw:
        return None

    text = clean_text(raw)

    # 万km notation
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*万\s*(?:km|キロ|Km|KM)?", text, re.IGNORECASE)
    if m:
        num_str = m.group(1).replace(",", "")
        try:
            return int(float(num_str) * 10_000)
        except ValueError:
            pass

    # Plain numeric
    m = re.search(r"([\d,]+)", text)
    if m:
        num_str = m.group(1).replace(",", "")
        try:
            return int(num_str)
        except ValueError:
            pass

    return None


# ======================================================================
# Year normalization
# ======================================================================

def normalize_year(raw: str | None) -> int | None:
    """Parse a Japanese year string (era or western).

    Examples:
        >>> normalize_year("R1")
        2019
        >>> normalize_year("令和3年")
        2021
        >>> normalize_year("H30")
        2018
        >>> normalize_year("平成30年")
        2018
        >>> normalize_year("2019年")
        2019
        >>> normalize_year("S63")
        1988
    """
    if not raw:
        return None

    text = clean_text(raw)

    # Try era-based format: e.g. "R1", "令和3", "H30", "平成30年"
    for era_key, base_year in _ERA_MAP.items():
        pattern = re.escape(era_key) + r"\s*(\d{1,2})"
        m = re.search(pattern, text)
        if m:
            era_num = int(m.group(1))
            western = base_year + era_num
            if 1950 <= western <= 2100:
                return western

    # Western year: "2019年" or just "2019"
    m = re.search(r"((?:19|20)\d{2})", text)
    if m:
        year = int(m.group(1))
        if 1950 <= year <= 2100:
            return year

    return None


# ======================================================================
# Maker / Model / Body type normalization
# ======================================================================

def normalize_maker(raw: str | None) -> str:
    """Normalize a maker/manufacturer name.

    >>> normalize_maker("ISUZU")
    'いすゞ'
    >>> normalize_maker("三菱")
    '三菱ふそう'
    """
    if not raw:
        return ""
    text = clean_text(raw)
    return MAKER_MAP.get(text, text)


def normalize_model(raw: str | None) -> str:
    """Normalize a vehicle model name.

    >>> normalize_model("FORWARD")
    'フォワード'
    """
    if not raw:
        return ""
    text = clean_text(raw)
    return MODEL_MAP.get(text, text)


def normalize_body_type(raw: str | None) -> str:
    """Normalize a body type name.

    >>> normalize_body_type("ウィングボディ")
    'ウイング'
    >>> normalize_body_type("パッカー車")
    '塵芥車'
    """
    if not raw:
        return ""
    text = clean_text(raw)
    # Try exact match first
    if text in BODY_TYPE_MAP:
        return BODY_TYPE_MAP[text]
    # Try substring match (longest match wins)
    best_match = ""
    best_key = ""
    for key, value in BODY_TYPE_MAP.items():
        if key in text and len(key) > len(best_key):
            best_match = value
            best_key = key
    return best_match if best_match else text


# ======================================================================
# Validation
# ======================================================================

_REQUIRED_FIELDS = ["maker", "model", "year", "price"]
_YEAR_RANGE = (1980, 2030)
_PRICE_RANGE = (10_000, 500_000_000)       # 1万 ~ 5億
_MILEAGE_RANGE = (0, 5_000_000)            # 0 ~ 500万km


def is_valid_vehicle(data: dict) -> tuple[bool, list[str]]:
    """Validate a vehicle data dict.

    Checks:
        - Required fields are present and non-empty.
        - Year is within a reasonable range.
        - Price is within a reasonable range.
        - Mileage (if present) is within a reasonable range.

    Returns:
        (is_valid, list_of_error_messages)

    >>> is_valid_vehicle({"maker": "日野", "model": "レンジャー", "year": 2020, "price": 5000000})
    (True, [])
    >>> is_valid_vehicle({"maker": "", "model": "レンジャー"})
    (False, ['Missing or empty field: maker', 'Missing or empty field: year', 'Missing or empty field: price'])
    """
    errors: list[str] = []

    # Required fields
    for field in _REQUIRED_FIELDS:
        val = data.get(field)
        if val is None or val == "" or val == 0:
            errors.append(f"Missing or empty field: {field}")

    # Year range
    year = data.get("year")
    if isinstance(year, int) and not (_YEAR_RANGE[0] <= year <= _YEAR_RANGE[1]):
        errors.append(
            f"Year {year} outside valid range {_YEAR_RANGE[0]}-{_YEAR_RANGE[1]}"
        )

    # Price range
    price = data.get("price")
    if isinstance(price, (int, float)) and price > 0:
        if not (_PRICE_RANGE[0] <= price <= _PRICE_RANGE[1]):
            errors.append(
                f"Price {price} outside valid range "
                f"{_PRICE_RANGE[0]:,}-{_PRICE_RANGE[1]:,}"
            )

    # Mileage range (optional)
    mileage = data.get("mileage")
    if isinstance(mileage, (int, float)) and mileage > 0:
        if not (_MILEAGE_RANGE[0] <= mileage <= _MILEAGE_RANGE[1]):
            errors.append(
                f"Mileage {mileage} outside valid range "
                f"{_MILEAGE_RANGE[0]:,}-{_MILEAGE_RANGE[1]:,}"
            )

    return (len(errors) == 0, errors)
