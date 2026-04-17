"""Portfolio utility functions."""


def extract_fund_house(fund_name: str) -> str:
    """Extract AMC/fund house name from a mutual fund name."""
    known_houses = [
        "HDFC", "ICICI Prudential", "ICICI", "SBI", "Axis", "Kotak",
        "Aditya Birla Sun Life", "Aditya Birla", "Nippon India", "Nippon",
        "UTI", "DSP", "Mirae Asset", "Mirae", "Tata", "Canara Robeco",
        "HSBC", "Franklin Templeton", "Franklin", "Motilal Oswal", "Motilal",
        "Parag Parikh", "PPFAS", "Quant", "Bandhan", "Edelweiss",
        "Invesco", "Sundaram", "PGIM", "Baroda BNP", "Baroda",
        "JM Financial", "JM", "WhiteOak", "Navi", "Groww", "ITI",
        "360 ONE", "Bank of India", "BOI", "LIC", "Mahindra Manulife",
    ]
    name_lower = fund_name.lower()
    for house in known_houses:
        if house.lower() in name_lower:
            return house
    for kw in ["mutual fund", "fund", "flexi", "large", "mid", "small", "multi", "balanced", "liquid", "overnight", "debt", "index"]:
        idx = name_lower.find(kw)
        if idx > 2:
            return fund_name[:idx].strip().rstrip("-").strip()
    return fund_name.split(" ")[0] if fund_name else "Unknown"


def compute_fund_overlap(fund_a: dict, fund_b: dict) -> dict:
    """Compute overlap between two mutual funds based on sector and category similarity."""
    name_a = fund_a.get("name", "")
    name_b = fund_b.get("name", "")
    sector_a = fund_a.get("sector", "Other").lower()
    sector_b = fund_b.get("sector", "Other").lower()

    overlap_score = 0
    reasons = []

    if sector_a == sector_b and sector_a != "other":
        overlap_score += 50
        reasons.append(f"Same category: {fund_a.get('sector', 'Other')}")

    categories = ["large cap", "mid cap", "small cap", "flexi cap", "multi cap",
                   "balanced", "hybrid", "debt", "liquid", "elss", "index",
                   "nifty", "sensex", "banking", "it", "pharma", "infrastructure"]

    cats_a = set(c for c in categories if c in name_a.lower())
    cats_b = set(c for c in categories if c in name_b.lower())

    shared_cats = cats_a & cats_b
    if shared_cats:
        overlap_score += min(len(shared_cats) * 25, 40)
        reasons.append(f"Shared mandate: {', '.join(shared_cats)}")

    house_a = extract_fund_house(name_a)
    house_b = extract_fund_house(name_b)
    if house_a == house_b:
        overlap_score += 10
        reasons.append(f"Same AMC: {house_a}")

    overlap_score = min(overlap_score, 95)

    return {
        "fund_a": name_a[:50],
        "fund_b": name_b[:50],
        "overlap_pct": overlap_score,
        "reasons": reasons,
        "sector_a": fund_a.get("sector", "Other"),
        "sector_b": fund_b.get("sector", "Other"),
    }
