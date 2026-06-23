"""SGB (Sovereign Gold Bond) Issue Price Mapping — ISIN to RBI Issue Price per gram."""

# Comprehensive mapping of SGB ISINs to their issue prices (₹/gram)
# Source: RBI announcements, NSDL/CDSL records
# This covers all SGB tranches from 2015 to 2024

SGB_ISSUE_PRICES = {
    # 2015
    "IN0020150085": {"series": "SGB 2015-I", "issue_price": 2684, "issue_date": "2015-11-30"},
    # 2016
    "IN0020150101": {"series": "SGB 2016-I", "issue_price": 2600, "issue_date": "2016-02-08"},
    "IN0020150119": {"series": "SGB 2016-II", "issue_price": 2916, "issue_date": "2016-03-29"},
    # 2016-17
    "IN0020160027": {"series": "SGB 2016-17 Series I", "issue_price": 3119, "issue_date": "2016-08-05"},
    "IN0020160043": {"series": "SGB 2016-17 Series II", "issue_price": 3150, "issue_date": "2016-09-30"},
    "IN0020160068": {"series": "SGB 2016-17 Series III", "issue_price": 2957, "issue_date": "2016-11-17"},
    "IN0020160084": {"series": "SGB 2016-17 Series IV", "issue_price": 2893, "issue_date": "2017-03-17"},
    # 2017-18
    "IN0020170018": {"series": "SGB 2017-18 Series I", "issue_price": 2951, "issue_date": "2017-05-12"},
    "IN0020170034": {"series": "SGB 2017-18 Series II", "issue_price": 2830, "issue_date": "2017-07-28"},
    "IN0020170050": {"series": "SGB 2017-18 Series III", "issue_price": 2956, "issue_date": "2017-09-19"},
    "IN0020170067": {"series": "SGB 2017-18 Series IV", "issue_price": 2945, "issue_date": "2017-10-09"},
    "IN0020170075": {"series": "SGB 2017-18 Series V", "issue_price": 2988, "issue_date": "2017-10-23"},
    "IN0020170083": {"series": "SGB 2017-18 Series VI", "issue_price": 2945, "issue_date": "2017-11-06"},
    "IN0020170091": {"series": "SGB 2017-18 Series VII", "issue_price": 2934, "issue_date": "2017-11-13"},
    "IN0020170109": {"series": "SGB 2017-18 Series VIII", "issue_price": 2961, "issue_date": "2017-11-20"},
    "IN0020170117": {"series": "SGB 2017-18 Series IX", "issue_price": 2934, "issue_date": "2017-11-27"},
    "IN0020170125": {"series": "SGB 2017-18 Series X", "issue_price": 2890, "issue_date": "2017-12-04"},
    "IN0020170133": {"series": "SGB 2017-18 Series XI", "issue_price": 2890, "issue_date": "2017-12-11"},
    "IN0020170141": {"series": "SGB 2017-18 Series XII", "issue_price": 2890, "issue_date": "2017-12-18"},
    "IN0020170158": {"series": "SGB 2017-18 Series XIII", "issue_price": 2866, "issue_date": "2017-12-26"},
    "IN0020170166": {"series": "SGB 2017-18 Series XIV", "issue_price": 2881, "issue_date": "2018-01-01"},
    # 2018-19
    "IN0020180016": {"series": "SGB 2018-19 Series I", "issue_price": 3114, "issue_date": "2018-04-16"},
    "IN0020180032": {"series": "SGB 2018-19 Series II", "issue_price": 3146, "issue_date": "2018-05-07"},
    "IN0020180040": {"series": "SGB 2018-19 Series III", "issue_price": 3183, "issue_date": "2018-07-16"},
    "IN0020180057": {"series": "SGB 2018-19 Series IV", "issue_price": 3119, "issue_date": "2018-10-15"},
    "IN0020180065": {"series": "SGB 2018-19 Series V", "issue_price": 3214, "issue_date": "2019-01-14"},
    "IN0020180073": {"series": "SGB 2018-19 Series VI", "issue_price": 3196, "issue_date": "2019-02-25"},
    # 2019-20
    "IN0020190015": {"series": "SGB 2019-20 Series I", "issue_price": 3196, "issue_date": "2019-04-15"},
    "IN0020190023": {"series": "SGB 2019-20 Series II", "issue_price": 3443, "issue_date": "2019-06-11"},
    "IN0020190031": {"series": "SGB 2019-20 Series III", "issue_price": 3499, "issue_date": "2019-08-05"},
    "IN0020190049": {"series": "SGB 2019-20 Series IV", "issue_price": 3788, "issue_date": "2019-09-09"},
    "IN0020190056": {"series": "SGB 2019-20 Series V", "issue_price": 3835, "issue_date": "2019-10-14"},
    "IN0020190064": {"series": "SGB 2019-20 Series VI", "issue_price": 3795, "issue_date": "2019-10-28"},
    "IN0020190072": {"series": "SGB 2019-20 Series VII", "issue_price": 3788, "issue_date": "2019-11-25"},
    "IN0020190080": {"series": "SGB 2019-20 Series VIII", "issue_price": 3890, "issue_date": "2020-01-13"},
    "IN0020190098": {"series": "SGB 2019-20 Series IX", "issue_price": 4036, "issue_date": "2020-02-03"},
    "IN0020190106": {"series": "SGB 2019-20 Series X", "issue_price": 4260, "issue_date": "2020-03-02"},
    # 2020-21
    "IN0020200013": {"series": "SGB 2020-21 Series I", "issue_price": 4639, "issue_date": "2020-04-20"},
    "IN0020200021": {"series": "SGB 2020-21 Series II", "issue_price": 4590, "issue_date": "2020-05-11"},
    "IN0020200039": {"series": "SGB 2020-21 Series III", "issue_price": 4677, "issue_date": "2020-06-08"},
    "IN0020200047": {"series": "SGB 2020-21 Series IV", "issue_price": 4852, "issue_date": "2020-07-06"},
    "IN0020200054": {"series": "SGB 2020-21 Series V", "issue_price": 5334, "issue_date": "2020-08-03"},
    "IN0020200062": {"series": "SGB 2020-21 Series VI", "issue_price": 5117, "issue_date": "2020-08-31"},
    "IN0020200070": {"series": "SGB 2020-21 Series VII", "issue_price": 5177, "issue_date": "2020-10-12"},
    "IN0020200088": {"series": "SGB 2020-21 Series VIII", "issue_price": 5177, "issue_date": "2020-11-09"},
    "IN0020200096": {"series": "SGB 2020-21 Series IX", "issue_price": 5000, "issue_date": "2020-12-28"},
    "IN0020200104": {"series": "SGB 2020-21 Series X", "issue_price": 4912, "issue_date": "2021-01-11"},
    "IN0020200112": {"series": "SGB 2020-21 Series XI", "issue_price": 4662, "issue_date": "2021-02-01"},
    "IN0020200120": {"series": "SGB 2020-21 Series XII", "issue_price": 4662, "issue_date": "2021-03-01"},
    # Additional 2020-21 variant ISINs
    "IN0020200146": {"series": "SGB 2020-21 Series IV", "issue_price": 4852, "issue_date": "2020-07-06"},
    # 2021-22
    "IN0020210011": {"series": "SGB 2021-22 Series I", "issue_price": 4777, "issue_date": "2021-05-17"},
    "IN0020210029": {"series": "SGB 2021-22 Series II", "issue_price": 4842, "issue_date": "2021-05-24"},
    "IN0020210037": {"series": "SGB 2021-22 Series III", "issue_price": 4889, "issue_date": "2021-05-31"},
    "IN0020210045": {"series": "SGB 2021-22 Series IV", "issue_price": 4807, "issue_date": "2021-08-09"},
    # SGB 2021-22 Series V — authoritative ISIN per RBI/NSE is IN0020210129
    # (NSE: SGBAUG29V, BSE: 800385, issued 2021-08-17; issue price ₹4,740/g per NSE).
    # IN0020210052 was a previously-recorded key for the same tranche; its ISIN is
    # unverified and superseded by IN0020210129 — kept only for back-compat.
    "IN0020210129": {"series": "SGB 2021-22 Series V", "issue_price": 4740, "issue_date": "2021-08-17"},
    "IN0020210052": {"series": "SGB 2021-22 Series V", "issue_price": 4732, "issue_date": "2021-08-16"},
    "IN0020210060": {"series": "SGB 2021-22 Series VI", "issue_price": 4765, "issue_date": "2021-10-25"},
    "IN0020210078": {"series": "SGB 2021-22 Series VII", "issue_price": 4791, "issue_date": "2021-11-29"},
    "IN0020210086": {"series": "SGB 2021-22 Series VIII", "issue_price": 4786, "issue_date": "2022-01-10"},
    "IN0020210094": {"series": "SGB 2021-22 Series IX", "issue_price": 5109, "issue_date": "2022-03-01"},
    # 2022-23
    "IN0020220011": {"series": "SGB 2022-23 Series I", "issue_price": 5091, "issue_date": "2022-06-20"},
    "IN0020220029": {"series": "SGB 2022-23 Series II", "issue_price": 5197, "issue_date": "2022-08-22"},
    "IN0020220037": {"series": "SGB 2022-23 Series III", "issue_price": 5409, "issue_date": "2022-12-19"},
    "IN0020220045": {"series": "SGB 2022-23 Series IV", "issue_price": 5611, "issue_date": "2023-03-06"},
    # Alternate ISINs observed in CAS for 2022-23
    "IN0020220110": {"series": "SGB 2022-23 Series X", "issue_price": 5409, "issue_date": "2022-12-19"},
    # 2023-24
    "IN0020230039": {"series": "SGB 2023-24 Series I", "issue_price": 5926, "issue_date": "2023-06-19"},
    "IN0020230047": {"series": "SGB 2023-24 Series II", "issue_price": 5923, "issue_date": "2023-09-11"},
    "IN0020230069": {"series": "SGB 2023-24 Series II", "issue_price": 5926, "issue_date": "2023-09-11"},
    "IN0020230168": {"series": "SGB 2023-24 Series III", "issue_price": 6199, "issue_date": "2023-12-28"},
    "IN0020230184": {"series": "SGB 2023-24 Series IV", "issue_price": 6263, "issue_date": "2024-02-21"},
}


def get_sgb_issue_price(isin: str) -> dict | None:
    """Look up SGB issue price by ISIN. Returns {series, issue_price, issue_date} or None."""
    isin = (isin or "").strip().upper()
    return SGB_ISSUE_PRICES.get(isin)


# Names that the upstream CAS parsers sometimes produce for SGBs when no
# series field is extracted. We treat any of these as "generic" and prefer
# the ISIN-derived series label instead.
_GENERIC_SGB_NAMES = {
    "", "government", "government of india", "goi",
    "sovereign gold bond", "sovereign gold bonds",
    "sgb", "sovereign gold bond (sgb)",
}


def get_sgb_series_name(isin: str) -> str | None:
    """Return the human-readable series label for an SGB ISIN
    (e.g. 'SGB 2023-24 Series III'), or None if unknown."""
    info = get_sgb_issue_price(isin)
    return (info or {}).get("series")


def resolve_sgb_display_name(name: str | None, isin: str | None) -> str:
    """Return the best display name for an SGB. If `name` is missing or
    generic (issuer-only, like 'GOVERNMENT'), substitute the series label
    looked up from `isin`. Falls back to the original name (or
    'Sovereign Gold Bond') if no series is on file."""
    nm = (name or "").strip()
    if nm.lower() in _GENERIC_SGB_NAMES:
        series = get_sgb_series_name(isin or "")
        if series:
            return series
        return nm or "Sovereign Gold Bond"
    return nm


def apply_sgb_issue_prices(holdings: list) -> tuple[list, int]:
    """
    For gold/SGB holdings, set buy_price to the RBI issue price if:
    - ISIN matches a known SGB series
    - Current buy_price is 0 or equals current_price (meaning CAS didn't extract cost basis)
    Returns (updated_holdings, count_updated).
    """
    updated = 0
    for h in holdings:
        if h.get("asset_type") != "gold":
            continue
        isin = (h.get("ticker") or "").strip().upper()
        if not isin:
            continue
        sgb = SGB_ISSUE_PRICES.get(isin)
        if not sgb:
            continue
        issue_price = sgb["issue_price"]
        buy_p = h.get("buy_price", 0)
        cur_p = h.get("current_price", 0)
        # Set issue price as buy_price if buy_price is missing or equals current_price
        if buy_p == 0 or (cur_p > 0 and abs(buy_p - cur_p) < 1):
            h["buy_price"] = issue_price
            h["sgb_series"] = sgb["series"]
            h["sgb_issue_date"] = sgb["issue_date"]
            h["price_source_buy"] = "rbi_sgb_mapping"
            updated += 1
    return holdings, updated
