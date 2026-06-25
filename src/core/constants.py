"""Market constants for A-share trading."""

from __future__ import annotations

# ── Market Codes ───────────────────────────────────────────────

SHANGHAI = "SH"
SHENZHEN = "SZ"
BEIJING = "BJ"

# ── Board Identifiers ─────────────────────────────────────────

SH_MAIN = "sh_main"       # 上海主板: 600, 601, 603, 605
SZ_MAIN = "sz_main"       # 深圳主板: 000, 001, 002, 003
CHINEXT = "chinext"       # 创业板: 300, 301
STAR_MARKET = "star"      # 科创板: 688, 689
BSE = "bse"               # 北交所: 8, 4, 9

# ── Symbol Suffix Mapping ─────────────────────────────────────

BOARD_PREFIX_TO_SUFFIX: dict[str, str] = {
    "600": SHANGHAI,
    "601": SHANGHAI,
    "603": SHANGHAI,
    "605": SHANGHAI,
    "688": SHANGHAI,
    "689": SHANGHAI,
    "000": SHENZHEN,
    "001": SHENZHEN,
    "002": SHENZHEN,
    "003": SHENZHEN,
    "300": SHENZHEN,
    "301": SHENZHEN,
    "8": BEIJING,
    "4": BEIJING,
    "9": BEIJING,
}


def symbol_suffix(code: str) -> str:
    """Determine exchange suffix from stock code.

    >>> symbol_suffix("000001")
    'SZ'
    >>> symbol_suffix("600519")
    'SH'
    """
    for prefix, suffix in BOARD_PREFIX_TO_SUFFIX.items():
        if code.startswith(prefix):
            return suffix
    return SHANGHAI  # default


def format_symbol(code: str) -> str:
    """Format stock code with exchange suffix.

    >>> format_symbol("000001")
    '000001.SZ'
    """
    code = code.strip().upper()
    if "." in code:
        raw_code, suffix = code.split(".", 1)
        return f"{raw_code.zfill(6)}.{suffix}"
    code = code.zfill(6)
    return f"{code}.{symbol_suffix(code)}"


# ── ST Stock Identification ───────────────────────────────────

ST_PREFIXES = ("*ST", "ST", "SST", "S*ST")


def is_st(name: str) -> bool:
    """Check if a stock name indicates ST (Special Treatment)."""
    normalized = name.strip().upper()
    for prefix in ST_PREFIXES:
        if not normalized.startswith(prefix):
            continue
        suffix = normalized[len(prefix):]
        return not suffix[:1].isalpha() or not suffix[:1].isascii()
    return False
