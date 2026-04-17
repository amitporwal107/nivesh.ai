"""Equity sector classification for Indian stocks (NSE/BSE).
Maps ISIN/stock names to NSE industry sectors."""

# NSE Industry Classification for major Indian stocks
# Source: NSE India sector indices and industry classification
ISIN_SECTOR_MAP = {
    # Banking
    "INE040A01034": "Banking", "INE090A01021": "Banking", "INE476A01014": "Banking",
    "INE467B01029": "Banking", "INE019A01038": "Banking", "INE062A01020": "Banking",
    "INE077A01010": "Banking", "INE160A01022": "Banking", "INE084A01016": "Banking",
    "INE028A01039": "Banking", "INE614G01033": "Banking", "INE491A01021": "Banking",
    "INE238A01034": "Banking", "INE095A01012": "Banking", "INE483A01010": "Banking",
    "INE557F01011": "Banking", "INE692A01016": "Banking",
    # IT / Technology
    "INE009A01021": "IT", "INE669C01036": "IT", "INE860A01027": "IT",
    "INE836A01035": "IT", "INE154A01025": "IT", "INE313F01019": "IT",
    "INE018I01017": "IT", "INE126J01031": "IT", "INE121J01016": "IT",
    # Pharma / Healthcare
    "INE326A01037": "Pharma", "INE089A01023": "Pharma", "INE148I01020": "Pharma",
    "INE361B01024": "Pharma", "INE749A01030": "Pharma", "INE901L01018": "Pharma",
    "INE199A01012": "Pharma", "INE427S01011": "Pharma",
    # FMCG / Consumer
    "INE030A01027": "FMCG", "INE102D01028": "FMCG", "INE047A01021": "FMCG",
    "INE192A01025": "FMCG", "INE259A01022": "FMCG", "INE979A01025": "FMCG",
    "INE619A01035": "FMCG", "INE205A01025": "FMCG",
    # Auto
    "INE585B01010": "Auto", "INE169A01031": "Auto", "INE917I01010": "Auto",
    "INE081A01020": "Auto", "INE216A01030": "Auto", "INE628A01036": "Auto",
    "INE758T01015": "Auto", "INE752E01010": "Auto",
    # Financial Services (Non-Banking)
    "INE758E01017": "Financial Services", "INE237A01036": "Financial Services",
    "INE296A01024": "Financial Services", "INE916GK1015": "Financial Services",
    "INE466L01038": "Financial Services", "INE121A01024": "Financial Services",
    # Telecom
    "INE397D01024": "Telecom", "INE882G01027": "Telecom",
    # Energy / Oil & Gas
    "INE002A01018": "Energy", "INE213A01029": "Energy", "INE029A01011": "Energy",
    "INE733E01010": "Energy", "INE274J01014": "Energy",
    # Metals & Mining
    "INE114A01011": "Metals", "INE136A01020": "Metals",
    "INE531E01026": "Metals", "INE226A01021": "Metals",
    # Power / Utilities
    "INE101A01026": "Power",
    "INE299U01018": "Consumer Durables",
    # Infrastructure / Construction
    "INE481G01011": "Infrastructure", "INE962Y01021": "Infrastructure",
    "INE701B01021": "Infrastructure",
    # Cement
    "INE049A01027": "Cement", "INE012A01025": "Cement",
    # Real Estate
    "INE106I01010": "Real Estate",
    # Insurance
    "INE263A01024": "Insurance", "INE795G01014": "Insurance",
    # Media / Entertainment
    "INE663F01032": "Internet / Tech",
    # Defence
    "INE118H01025": "Defence", "INE053F01010": "Defence",
    # Chemicals
    "INE318A01026": "Chemicals",
    # Textiles
    "INE14LE01019": "Textiles / Lifestyle",
    # Renewable Energy
    "INE202E01016": "Renewable Energy",
    # Electronics
    "INE955D01029": "Power Equipment",
}

# Name-based fallback classification for stocks not in ISIN map
NAME_SECTOR_KEYWORDS = {
    "Banking": ["bank", "banking", "sbi ", "hdfc bank", "icici bank", "kotak", "axis bank", "pnb", "bob", "canara", "ifci"],
    "IT": ["infosys", "tcs", "wipro", "hcl tech", "tech mahindra", "birlasoft", "mphasis", "persistent", "ltimindtree", "coforge", "digital india", "netweb", "railtel", "tata digital"],
    "Pharma": ["pharma", "cipla", "sun pharma", "dr reddy", "lupin", "aurobindo", "alembic", "biocon", "divis", "glenmark", "syngene"],
    "FMCG": ["hindustan unilever", "itc", "nestle", "dabur", "marico", "godrej consumer", "britannia", "colgate", "emami", "united spirits", "united breweries"],
    "Auto": ["maruti", "tata motors", "mahindra", "bajaj auto", "hero moto", "eicher", "tvs motor", "ashok leyland", "ola electric", "exide", "varroc"],
    "Financial Services": ["bajaj finance", "bajaj finserv", "hdfc life", "sbi life", "lic", "muthoot", "manappuram", "jio financial", "pnb housing", "rec limited", "national securities", "nsdl"],
    "Telecom": ["airtel", "bharti", "vodafone", "idea cellular", "reliance jio"],
    "Energy": ["reliance ind", "ongc", "bpcl", "hpcl", "ioc", "gail", "petronet", "adani green", "ntpc", "power grid"],
    "Metals": ["tata steel", "jsw steel", "hindalco", "vedanta", "hindustan copper", "nalco", "sail", "nmdc"],
    "Power": ["ntpc", "power grid", "adani power", "tata power", "nhpc", "sjvn"],
    "Infrastructure": ["larsen", "l&t", "ircon", "punj lloyd", "nbcc", "rites"],
    "Cement": ["ultratech", "ambuja", "acc", "shree cement", "dalmia"],
    "Real Estate": ["dlf", "godrej properties", "oberoi", "prestige", "brigade"],
    "Insurance": ["lic housing", "sbi life", "hdfc life", "icici prudential life", "general insurance"],
    "Consumer Durables": ["crompton", "havells", "voltas", "whirlpool", "dixon", "blue star"],
    "Chemicals": ["pidilite", "asian paints", "berger", "srf", "aarti"],
    "Internet / Tech": ["info edge", "naukri", "zomato", "paytm", "policybazaar", "one 97", "swiggy", "oravel"],
    "Defence": ["bharat electronics", "hal", "bharat dynamics", "mazagon", "zen technologies"],
    "Renewable Energy": ["ireda", "indian renewable", "ntpc green", "adani green"],
}


def classify_equity_sector(isin: str, name: str) -> str:
    """Classify an equity stock into its sector using ISIN map or name keywords."""
    isin = (isin or "").upper().strip()
    name_lower = (name or "").lower()

    # Try ISIN lookup first
    if isin and isin in ISIN_SECTOR_MAP:
        return ISIN_SECTOR_MAP[isin]

    # Try name-based classification
    for sector, keywords in NAME_SECTOR_KEYWORDS.items():
        for kw in keywords:
            if kw in name_lower:
                return sector

    return "Other"


def enrich_holdings_with_sectors(holdings: list) -> list:
    """Add proper sector classification to equity and mutual fund holdings."""
    from helpers.parsing import classify_mf_sector

    for h in holdings:
        current_sector = h.get("sector", "Other")
        if h.get("asset_type") == "equity":
            if current_sector == "Other" or not current_sector:
                h["sector"] = classify_equity_sector(h.get("ticker", ""), h.get("name", ""))
        elif h.get("asset_type") in ("mutual_fund", "etf"):
            if current_sector == "Other" or not current_sector:
                h["sector"] = classify_mf_sector(h.get("name", ""))
    return holdings
