"""Vehicle data parser: transforms raw scraped dicts into clean DB-ready records."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from scraper.utils import (
    clean_text,
    is_valid_vehicle,
    normalize_body_type,
    normalize_maker,
    normalize_mileage,
    normalize_model,
    normalize_price,
    normalize_year,
)

logger = logging.getLogger(__name__)


class VehicleParser:
    """Converts raw scraper output into normalized vehicle records.

    Usage::

        parser = VehicleParser()
        raw = {"maker": "ISUZU", "model": "FORWARD", "price": "450万円(税込)", ...}
        result = parser.parse(raw, source_site="truck_bank")
        # result is a cleaned dict ready for DB insertion

    The parser is stateless; a single instance can be reused across records.
    """

    # Minimum fields required to consider a record valid
    REQUIRED_FIELDS = ("source_site", "source_url", "maker", "model_name")

    # Fields that map directly through ``clean_text`` without special logic
    _TEXT_FIELDS = (
        "color",
        "engine_type",
        "fuel_type",
        "transmission",
        "drive_type",
        "equipment",
        "description",
        "chassis_number",
        "model_number",
        "inspection",
    )

    # Numeric fields that should be coerced to int (if possible)
    _INT_FIELDS = (
        "horse_power",
        "max_load_kg",
        "vehicle_weight_kg",
        "gross_vehicle_weight_kg",
        "cab_width",
        "wheelbase",
        "length_cm",
        "width_cm",
        "height_cm",
        "doors",
        "seats",
    )

    # Numeric fields that should be coerced to float
    _FLOAT_FIELDS = (
        "displacement_cc",
        "fuel_economy",
    )

    # ------------------------------------------------------------------
    # Known values for title-based extraction
    # ------------------------------------------------------------------

    _KNOWN_MAKERS = [
        "いすゞ", "日野", "三菱ふそう", "UDトラックス", "トヨタ",
        "日産", "マツダ", "ISUZU", "HINO", "FUSO", "UD",
    ]

    _KNOWN_BODY_TYPES = [
        "ウイング", "ウィング", "アルミウイング", "バン", "アルミバン",
        "冷凍", "冷蔵", "平ボディ", "ダンプ", "クレーン", "ユニック",
        "トラクタ", "トレーラ", "ミキサー", "塵芥", "パッカー",
        "キャリアカー", "車載車", "タンクローリー", "セルフローダ",
    ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(
        self, raw: dict[str, Any], source_site: str
    ) -> Optional[dict[str, Any]]:
        """Parse a single raw vehicle dict into a normalized record.

        Returns None if the record is missing critical fields.
        """
        try:
            record = self._build_record(raw, source_site)
            if not self._validate(record):
                return None
            return record
        except Exception as exc:
            logger.warning(
                "parse_failed: error=%s, raw_keys=%s",
                str(exc),
                list(raw.keys()),
            )
            return None

    def parse_batch(
        self, items: list[dict[str, Any]], source_site: str
    ) -> list[dict[str, Any]]:
        """Parse a batch of raw items, filtering out invalid records."""
        results = []
        for item in items:
            parsed = self.parse(item, source_site)
            if parsed:
                results.append(parsed)
        logger.info(
            "batch_parsed: input_count=%d, output_count=%d, source_site=%s",
            len(items),
            len(results),
            source_site,
        )
        return results

    # ------------------------------------------------------------------
    # Record building
    # ------------------------------------------------------------------

    def _build_record(
        self, raw: dict[str, Any], source_site: str
    ) -> dict[str, Any]:
        """Map raw fields to the normalized vehicles table schema."""
        source_url = raw.get("url", raw.get("source_url", raw.get("detail_url", "")))
        title = clean_text(raw.get("title", ""))

        # -- Maker: try dedicated field first, then parse from title ----
        maker_raw = raw.get("maker", "")
        if not maker_raw and title:
            maker_raw = self._extract_maker_from_title(title)
        maker = normalize_maker(maker_raw)

        # -- Model: try dedicated field first, then parse from title ----
        model_raw = raw.get("model_name", raw.get("model", ""))
        if not model_raw and title:
            model_raw = self._extract_model_from_title(title, maker_raw)
        model_name = normalize_model(model_raw) or clean_text(model_raw) or title

        # -- Body type --------------------------------------------------
        body_type_raw = raw.get("body_type", raw.get("body", ""))
        if not body_type_raw and title:
            body_type_raw = self._extract_body_type_from_title(title)
        body_type = normalize_body_type(body_type_raw)

        # -- Price ------------------------------------------------------
        price_raw = raw.get("price", raw.get("price_text", ""))
        price, tax_included = normalize_price(
            str(price_raw) if price_raw else None
        )

        # -- Year -------------------------------------------------------
        year_raw = raw.get("year", raw.get("model_year", ""))
        year = normalize_year(str(year_raw)) if year_raw else None

        # -- Mileage ----------------------------------------------------
        mileage_raw = raw.get("mileage", raw.get("mileage_text", ""))
        mileage = normalize_mileage(str(mileage_raw)) if mileage_raw else None

        # -- Location ---------------------------------------------------
        location = clean_text(
            raw.get("location", raw.get("location_prefecture", raw.get("prefecture", "")))
        ) or None

        # -- Image URL --------------------------------------------------
        image_url = raw.get("image_url", raw.get("image", "")) or None

        # -- Source listing ID ------------------------------------------
        source_id = ""
        for id_key in ("source_id", "listing_id", "id", "vehicle_id", "stock_no"):
            if raw.get(id_key):
                source_id = clean_text(str(raw[id_key]))
                break

        record: dict[str, Any] = {
            "source_site": source_site,
            "source_url": source_url,
            "source_id": source_id,
            "maker": maker,
            "model_name": model_name,
            "body_type": body_type,
            "model_year": year,
            "mileage_km": mileage,
            "price_yen": price,
            "price_tax_included": tax_included,
            "tonnage_class": self._classify_tonnage(raw),
            "location_prefecture": location,
            "image_url": image_url,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "listing_status": "active",
        }

        # -- Pass-through text fields ----------------------------------
        for field in self._TEXT_FIELDS:
            val = raw.get(field)
            if val is not None:
                record[field] = clean_text(str(val)) or None

        # -- Numeric int fields -----------------------------------------
        for field in self._INT_FIELDS:
            if raw.get(field) is not None:
                record[field] = self._to_int(raw[field])

        # -- Numeric float fields ---------------------------------------
        for field in self._FLOAT_FIELDS:
            if raw.get(field) is not None:
                record[field] = self._to_float(raw[field])

        # -- Validation metadata ----------------------------------------
        # Build a minimal dict for the generic validator
        validation_dict = {
            "maker": record["maker"],
            "model": record["model_name"],
            "year": record["model_year"],
            "price": record["price_yen"],
            "mileage": record["mileage_km"],
        }
        is_valid, errors = is_valid_vehicle(validation_dict)
        record["_valid"] = is_valid
        record["_errors"] = errors

        return record

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate(self, record: dict[str, Any]) -> bool:
        """Check that required fields are present and non-empty."""
        for field in self.REQUIRED_FIELDS:
            if not record.get(field):
                logger.debug("validation_failed: missing_field=%s", field)
                return False
        return True

    # ------------------------------------------------------------------
    # Title-based extraction helpers
    # ------------------------------------------------------------------

    def _extract_maker_from_title(self, title: str) -> str:
        for m in self._KNOWN_MAKERS:
            if m in title:
                return m
        return ""

    def _extract_model_from_title(self, title: str, maker: str) -> str:
        if maker and maker in title:
            remainder = title.split(maker, 1)[1].strip()
            parts = remainder.split()
            if parts:
                return parts[0]
        return ""

    def _extract_body_type_from_title(self, title: str) -> str:
        for bt in self._KNOWN_BODY_TYPES:
            if bt in title:
                return bt
        return ""

    # ------------------------------------------------------------------
    # Numeric coercion helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_int(val: Any) -> int | None:
        """Coerce a value to int, stripping common suffixes/units."""
        if val is None:
            return None
        if isinstance(val, int):
            return val
        if isinstance(val, float):
            return int(val)
        text = clean_text(str(val))
        text = text.replace(",", "")
        # Strip common Japanese unit suffixes
        import re

        text = re.sub(r"[kgcmmmhppsPS馬力㎝㎏㎜人枚]+$", "", text)
        m = re.search(r"^-?\d+", text)
        if m:
            try:
                return int(m.group(0))
            except ValueError:
                pass
        return None

    @staticmethod
    def _to_float(val: Any) -> float | None:
        """Coerce a value to float."""
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        text = clean_text(str(val))
        text = text.replace(",", "")
        import re

        m = re.search(r"-?[\d.]+", text)
        if m:
            try:
                return float(m.group(0))
            except ValueError:
                pass
        return None

    # ------------------------------------------------------------------
    # Tonnage classification
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_tonnage(raw: dict[str, Any]) -> str:
        """Determine tonnage class from available data.

        Returns one of: '小型' (light), '中型' (medium), '大型' (heavy),
        '増トン' (uprated), or '' if undetermined.
        """
        tonnage_raw = raw.get("tonnage_class", raw.get("size_class", ""))
        tonnage_text = clean_text(str(tonnage_raw)) if tonnage_raw else ""
        if tonnage_text:
            for label in ("小型", "中型", "大型", "増トン"):
                if label in tonnage_text:
                    return label

        # Try to extract from tonnage / max_load numeric fields
        for key in ("max_load_kg", "tonnage", "tonnage_text"):
            val = raw.get(key)
            if val is None:
                continue
            text = clean_text(str(val)).replace(",", "")
            import re

            m = re.search(r"[\d.]+", text)
            if not m:
                continue
            num = float(m.group(0))
            # If the value looks like tonnes (< 100), convert to kg
            if num < 100:
                num *= 1000
            if num <= 3000:
                return "小型"
            elif num <= 8000:
                return "中型"
            else:
                return "大型"

        # Try GVW
        gvw = raw.get("gross_vehicle_weight_kg")
        if gvw is not None:
            text = clean_text(str(gvw)).replace(",", "")
            import re

            m = re.search(r"[\d.]+", text)
            if m:
                num = float(m.group(0))
                if num < 100:
                    num *= 1000
                if num <= 5000:
                    return "小型"
                elif num <= 11000:
                    return "中型"
                else:
                    return "大型"

        return ""
