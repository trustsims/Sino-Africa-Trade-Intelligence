import re
from datetime import date

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

CANONICAL_FIELDS = {
    "reporter_code": "Reporter country code (UN M49)",
    "reporter_name": "Reporter country name",
    "partner_code": "Partner country code (UN M49)",
    "partner_name": "Partner country name",
    "flow": "Trade flow (X export, M import, RX re-export, RM re-import)",
    "year": "Reference year",
    "month": "Reference month (1-12) for monthly data",
    "period": "Period label (e.g. 2022 or 202205)",
    "frequency": "Frequency code (A annual, M monthly)",
    "hs_code": "Commodity code (HS)",
    "classification": "Classification version (e.g. H4 = HS2012, H5 = HS2017, H6 = HS2022)",
    "product_description": "Commodity description",
    "trade_value": "Trade value (primary value)",
    "currency": "Currency of trade value",
    "net_weight_kg": "Net weight in kilograms",
    "quantity": "Quantity",
    "quantity_unit": "Quantity unit",
    "valuation_basis": "Valuation basis (FOB or CIF)",
    "data_source": "Data source label",
    "original_record_id": "Original record identifier",
    "aggregate_level": "Commodity aggregation level reported by source",
    "mot_code": "Mode of transport code (breakdown)",
    "customs_code": "Customs procedure code (breakdown)",
    "partner2_code": "Second partner code (breakdown)",
    "cif_value": "CIF value",
    "fob_value": "FOB value",
}

REQUIRED_FIELDS = ("year", "trade_value")
CONSTANT_ALLOWED_FIELDS = (
    "reporter_code",
    "reporter_name",
    "partner_code",
    "partner_name",
    "flow",
    "currency",
    "classification",
    "data_source",
    "frequency",
    "valuation_basis",
)

COLUMN_SYNONYMS = {
    "reporter_code": ["reportercode", "reporter_code", "reporterid", "rtcode"],
    "reporter_name": ["reporterdesc", "reporter", "reportername", "reporter_name", "rttitle", "reporteriso"],
    "partner_code": ["partnercode", "partner_code", "partnerid", "ptcode"],
    "partner_name": ["partnerdesc", "partner", "partnername", "partner_name", "pttitle", "partneriso"],
    "flow": ["flowcode", "flow", "tradeflow", "flowdesc", "rgdesc", "trade_flow", "rgcode"],
    "year": ["refyear", "year", "yr", "ref_year"],
    "month": ["refmonth", "month", "ref_month"],
    "period": ["period", "refperiod", "periodid", "refperiodid"],
    "frequency": ["freqcode", "frequency", "freq"],
    "hs_code": ["cmdcode", "commoditycode", "hscode", "hs_code", "productcode", "code", "commodity_code"],
    "classification": ["classificationcode", "classification", "clcode", "classificationsearchcode", "hsversion"],
    "product_description": ["cmddesc", "commodity", "commoditydesc", "productdescription", "description", "product", "cmddesce"],
    "trade_value": ["primaryvalue", "tradevalue", "tradevalueus", "tradevalueusd", "value", "trade_value", "valueusd"],
    "currency": ["currency", "currencycode"],
    "net_weight_kg": ["netwgt", "netweight", "netweightkg", "net_weight", "netweight(kg)"],
    "quantity": ["qty", "quantity", "altqty"],
    "quantity_unit": ["qtyunitabbr", "qtyunit", "quantityunit", "qtyunitcode", "unit"],
    "valuation_basis": ["valuationbasis", "valuation"],
    "data_source": ["datasource", "source"],
    "original_record_id": ["id", "recordid", "record_id", "originalid"],
    "aggregate_level": ["aggrlevel", "aggregatelevel"],
    "mot_code": ["motcode"],
    "customs_code": ["customscode"],
    "partner2_code": ["partner2code"],
    "cif_value": ["cifvalue"],
    "fob_value": ["fobvalue"],
}

COUNTRIES = {
    "0": ("World", "WLD"),
    "894": ("Zambia", "ZMB"),
    "156": ("China", "CHN"),
    "834": ("Tanzania", "TZA"),
    "710": ("South Africa", "ZAF"),
    "404": ("Kenya", "KEN"),
    "344": ("China, Hong Kong SAR", "HKG"),
}
ISO_TO_CODE = {iso: code for code, (_, iso) in COUNTRIES.items()}
NAME_TO_CODE = {name.lower(): code for code, (name, _) in COUNTRIES.items()}

FLOW_LABELS = {"X": "Export", "M": "Import", "RX": "Re-export", "RM": "Re-import"}
FLOW_ALIASES = {
    "x": "X",
    "export": "X",
    "exports": "X",
    "2": "X",
    "m": "M",
    "import": "M",
    "imports": "M",
    "1": "M",
    "rx": "RX",
    "re-export": "RX",
    "re-exports": "RX",
    "reexport": "RX",
    "3": "RX",
    "rm": "RM",
    "re-import": "RM",
    "re-imports": "RM",
    "reimport": "RM",
    "4": "RM",
}

CLASSIFICATION_LABELS = {
    "H0": "HS 1992",
    "H1": "HS 1996",
    "H2": "HS 2002",
    "H3": "HS 2007",
    "H4": "HS 2012",
    "H5": "HS 2017",
    "H6": "HS 2022",
    "HS": "HS (as reported)",
}

HS_SECTIONS = [
    ("I", "Live animals; animal products", 1, 5),
    ("II", "Vegetable products", 6, 14),
    ("III", "Animal or vegetable fats and oils", 15, 15),
    ("IV", "Prepared foodstuffs; beverages; tobacco", 16, 24),
    ("V", "Mineral products", 25, 27),
    ("VI", "Products of the chemical industries", 28, 38),
    ("VII", "Plastics and rubber", 39, 40),
    ("VIII", "Hides, skins, leather", 41, 43),
    ("IX", "Wood and articles of wood", 44, 46),
    ("X", "Pulp, paper and paperboard", 47, 49),
    ("XI", "Textiles and textile articles", 50, 63),
    ("XII", "Footwear, headgear", 64, 67),
    ("XIII", "Stone, ceramic, glass", 68, 70),
    ("XIV", "Precious stones and metals", 71, 71),
    ("XV", "Base metals and articles", 72, 83),
    ("XVI", "Machinery and electrical equipment", 84, 85),
    ("XVII", "Vehicles and transport equipment", 86, 89),
    ("XVIII", "Optical, medical, precision instruments", 90, 92),
    ("XIX", "Arms and ammunition", 93, 93),
    ("XX", "Miscellaneous manufactured articles", 94, 96),
    ("XXI", "Works of art and antiques", 97, 97),
]


def hs_section(chapter: str | None) -> str:
    if not chapter or not str(chapter).isdigit():
        return "Unclassified / total"
    ch = int(chapter)
    for roman, label, lo, hi in HS_SECTIONS:
        if lo <= ch <= hi:
            return f"{roman} – {label}"
    return "XXII – Special / unspecified (Ch. 77, 98-99)"


def country_name(code: str | None, fallback: str | None = None) -> str:
    if fallback and str(fallback).strip() and str(fallback).strip().lower() != "nan":
        return str(fallback).strip()
    if code is not None and str(code) in COUNTRIES:
        return COUNTRIES[str(code)][0]
    return str(code) if code is not None else "Unknown"


def normalize_country_code(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return None
    if s.upper() in ISO_TO_CODE:
        return ISO_TO_CODE[s.upper()]
    if s.lower() in NAME_TO_CODE:
        return NAME_TO_CODE[s.lower()]
    if re.fullmatch(r"\d+(\.0+)?", s):
        return str(int(float(s)))
    return s


def normalize_flow(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    if s.endswith(".0"):
        s = s[:-2]
    return FLOW_ALIASES.get(s)


def normalize_column_name(name: str) -> str:
    return re.sub(r"[^a-z0-9()]", "", str(name).lower())


class ColumnMapping(BaseModel):
    columns: dict[str, str] = Field(default_factory=dict)
    constants: dict[str, str] = Field(default_factory=dict)

    @field_validator("columns")
    @classmethod
    def known_fields(cls, v: dict[str, str]) -> dict[str, str]:
        unknown = [k for k in v if k not in CANONICAL_FIELDS]
        if unknown:
            raise ValueError(f"Unknown canonical fields: {unknown}")
        return {k: c for k, c in v.items() if c}

    @field_validator("constants")
    @classmethod
    def allowed_constants(cls, v: dict[str, str]) -> dict[str, str]:
        bad = [k for k in v if k not in CONSTANT_ALLOWED_FIELDS]
        if bad:
            raise ValueError(f"Constants not allowed for: {bad}")
        return {k: str(c).strip() for k, c in v.items() if c is not None and str(c).strip()}

    @model_validator(mode="after")
    def required_present(self):
        missing = [f for f in REQUIRED_FIELDS if f not in self.columns]
        if "year" in missing and "period" in self.columns:
            missing.remove("year")
        if missing:
            raise ValueError(f"Required fields not mapped: {', '.join(missing)}")
        for f in ("reporter_code", "partner_code", "flow"):
            alt = {"reporter_code": "reporter_name", "partner_code": "partner_name"}.get(f)
            if f not in self.columns and f not in self.constants and not (alt and (alt in self.columns or alt in self.constants)):
                raise ValueError(f"'{f}' must be mapped to a column or given a constant value")
        return self


class ComtradeQuery(BaseModel):
    type_code: str = "C"
    freq_code: str = "A"
    classification: str = "HS"
    reporter_code: str
    partner_code: str
    flow_code: str
    periods: list[int]
    cmd_codes: list[str] = Field(default_factory=lambda: ["TOTAL"])

    @field_validator("freq_code")
    @classmethod
    def freq(cls, v: str) -> str:
        if v not in ("A", "M"):
            raise ValueError("freq_code must be A or M")
        return v

    @field_validator("flow_code")
    @classmethod
    def flow(cls, v: str) -> str:
        if v not in FLOW_LABELS:
            raise ValueError("flow_code must be X, M, RX or RM")
        return v

    @field_validator("reporter_code", "partner_code")
    @classmethod
    def m49(cls, v: str) -> str:
        if not re.fullmatch(r"\d{1,3}", str(v)):
            raise ValueError("country codes must be numeric UN M49 codes")
        return str(int(v))

    @field_validator("periods")
    @classmethod
    def years(cls, v: list[int], info: ValidationInfo) -> list[int]:
        if not v:
            raise ValueError("at least one period is required")
        current = date.today().year
        monthly = info.data.get("freq_code") == "M"
        for p in v:
            y, m = (p // 100, p % 100) if monthly else (p, 1)
            if y < 1962 or y > current or not 1 <= m <= 12:
                raise ValueError(f"period {p} is not a valid {'YYYYMM' if monthly else 'year'} between 1962 and {current}")
        if len(v) > 12:
            raise ValueError("request at most 12 periods per call")
        return sorted(set(v))

    @field_validator("cmd_codes")
    @classmethod
    def cmd(cls, v: list[str]) -> list[str]:
        out = []
        for c in v:
            c = str(c).strip().upper()
            if not (c in ("TOTAL", "AG2", "AG4", "AG6", "ALL") or re.fullmatch(r"\d{2,6}", c)):
                raise ValueError(f"invalid commodity code: {c}")
            out.append(c)
        return out


class ForecastConfig(BaseModel):
    horizon: int = Field(3, ge=1, le=24)
    min_train: int = Field(5, ge=3, le=60)
    interval_level: int = Field(95, ge=50, le=99)
    parsimony_tolerance_pct: float = Field(5.0, ge=0, le=50)
    mape_epsilon_share: float = Field(0.01, ge=0, le=0.5)
    volatility_threshold: float = Field(0.5, ge=0.05, le=5)
