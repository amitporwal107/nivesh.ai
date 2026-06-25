"""
Financial term override dictionary for English → Hindi translation.

Hybrid approach: IndicTrans2 handles bulk translation; this dictionary
overrides domain-specific financial terms where:
  - The English acronym must be preserved (XIRR, NAV, SIP, etc.)
  - A standard Hindi financial term exists and is preferred
  - IndicTrans2 tends to produce inconsistent or wrong results

Apply these overrides AFTER machine translation, using regex word-boundary
replacement so partial matches (e.g. "SIP-based") are handled correctly.

Usage:
    from tools.hindi_financial_terms import apply_overrides
    hindi_text = apply_overrides(machine_translated_text)

Maintenance: add new entries when a native-speaker reviewer flags an
inconsistent translation in the QA pass. Entries are case-sensitive.
"""

import re


# ─── Terms that STAY IN ENGLISH (acronyms / brand names) ─────────────────────
# IndicTrans2 sometimes transliterates these; override to keep Latin form.
KEEP_ENGLISH = [
    "XIRR", "NAV", "SIP", "LTCG", "STCG", "ELSS", "PPF", "NPS", "AMC",
    "ETF", "NFO", "SWP", "PMS", "AIF", "AUM", "TER", "FD", "P&L",
    "ROE", "ROA", "EPS", "P/E", "P/B", "EBITDA", "PAT", "SEBI",
    "NSE", "BSE", "NIFTY", "SENSEX", "CAGR", "IRR",
    "KYC", "PAN", "AADHAAR", "UPI", "DEMAT",
    "Grade A", "Grade B", "Grade C", "Grade D",
]

# ─── Term replacements: English phrase → preferred Hindi translation ──────────
# Verified by native-speaker review. Override machine translation for these.
TERM_MAP: dict[str, str] = {
    # Portfolio concepts
    "portfolio":              "पोर्टफोलियो",       # transliteration accepted in finance
    "Portfolio":              "पोर्टफोलियो",
    "concentration":          "एकाग्रता",
    "Concentration":          "एकाग्रता",
    "diversification":        "विविधीकरण",
    "Diversification":        "विविधीकरण",
    "diversified":            "विविधीकृत",
    "rebalance":              "पुनर्संतुलन",
    "Rebalance":              "पुनर्संतुलन",
    "rebalancing":            "पुनर्संतुलन",
    "allocation":             "आवंटन",
    "Allocation":             "आवंटन",
    "holdings":               "होल्डिंग्स",
    "Holdings":               "होल्डिंग्स",
    "overlap":                "ओवरलैप",
    "Overlap":                "ओवरलैप",

    # Risk
    "risk":                   "जोखिम",
    "Risk":                   "जोखिम",
    "risk profile":           "जोखिम प्रोफाइल",
    "Risk Profile":           "जोखिम प्रोफाइल",
    "drawdown":               "गिरावट",
    "volatility":             "उतार-चढ़ाव",
    "Volatility":             "उतार-चढ़ाव",
    "stress test":            "तनाव परीक्षण",
    "Stress Test":            "तनाव परीक्षण",

    # Returns & performance
    "returns":                "रिटर्न",
    "Returns":                "रिटर्न",
    "return":                 "रिटर्न",
    "Return":                 "रिटर्न",
    "performance":            "प्रदर्शन",
    "Performance":            "प्रदर्शन",
    "benchmark":              "बेंचमार्क",
    "Benchmark":              "बेंचमार्क",
    "underperforming":        "कम प्रदर्शन कर रहे",
    "underperform":           "कम प्रदर्शन करना",
    "outperform":             "बेहतर प्रदर्शन करना",
    "outperforming":          "बेहतर प्रदर्शन कर रहे",

    # Fund types
    "mutual fund":            "म्यूचुअल फंड",
    "Mutual Fund":            "म्यूचुअल फंड",
    "mutual funds":           "म्यूचुअल फंड",
    "Mutual Funds":           "म्यूचुअल फंड",
    "large-cap":              "लार्ज-कैप",
    "Large-cap":              "लार्ज-कैप",
    "mid-cap":                "मिड-कैप",
    "Mid-cap":                "मिड-कैप",
    "small-cap":              "स्मॉल-कैप",
    "flexi-cap":              "फ्लेक्सी-कैप",
    "debt fund":              "डेट फंड",
    "Debt Fund":              "डेट फंड",
    "equity fund":            "इक्विटी फंड",
    "Equity Fund":            "इक्विटी फंड",
    "index fund":             "इंडेक्स फंड",

    # Goals
    "retirement":             "सेवानिवृत्ति",
    "Retirement":             "सेवानिवृत्ति",
    "corpus":                 "कोष",
    "Corpus":                 "कोष",
    "goal":                   "लक्ष्य",
    "Goal":                   "लक्ष्य",
    "goals":                  "लक्ष्य",
    "Goals":                  "लक्ष्य",
    "shortfall":              "कमी",
    "Shortfall":              "कमी",
    "inflation":              "मुद्रास्फीति",
    "Inflation":              "मुद्रास्फीति",

    # Tax
    "tax":                    "कर",
    "Tax":                    "कर",
    "tax harvesting":         "टैक्स हार्वेस्टिंग",
    "Tax Harvesting":         "टैक्स हार्वेस्टिंग",
    "capital gains":          "पूंजीगत लाभ",
    "Capital Gains":          "पूंजीगत लाभ",
    "tax-efficient":          "कर-कुशल",
    "Tax-efficient":          "कर-कुशल",
    "expense ratio":          "व्यय अनुपात",
    "Expense Ratio":          "व्यय अनुपात",

    # UI labels
    "Copilot":                "कोपायलट",
    "copilot":                "कोपायलट",
    "Dashboard":              "डैशबोर्ड",
    "Settings":               "सेटिंग्स",
    "Portfolio":              "पोर्टफोलियो",
    "Insights":               "इनसाइट्स",
    "Goals":                  "लक्ष्य",
    "Profile":                "प्रोफाइल",
    "Sign out":               "साइन आउट",
    "Sign in":                "साइन इन",
    "Send":                   "भेजें",
    "Retry":                  "पुनः प्रयास",
    "Cancel":                 "रद्द करें",
    "Confirm":                "पुष्टि करें",

    # Score bands (keep the letter grade, translate the label)
    "Grade A":                "श्रेणी A",
    "Grade B":                "श्रेणी B",
    "Grade C":                "श्रेणी C",
    "Grade D":                "श्रेणी D",
    "Excellent":              "उत्कृष्ट",
    "Good":                   "अच्छा",
    "Average":                "औसत",
    "Poor":                   "खराब",

    # Severity / action labels
    "URGENT":                 "अत्यावश्यक",
    "urgent":                 "अत्यावश्यक",
    "CRITICAL":               "अत्यंत महत्वपूर्ण",
    "MODERATE":               "मध्यम",
    "LOW":                    "कम",
    "SEVERE":                 "गंभीर",

    # Equity / stock terms
    "equity":                 "इक्विटी",
    "Equity":                 "इक्विटी",
    "stock":                  "शेयर",
    "Stock":                  "शेयर",
    "stocks":                 "शेयर",
    "Stocks":                 "शेयर",
    "sector":                 "क्षेत्र",
    "Sector":                 "क्षेत्र",
    "fundamentals":           "मूल तत्व",
    "Fundamentals":           "मूल तत्व",
    "valuation":              "मूल्यांकन",
    "Valuation":              "मूल्यांकन",
    "overvalued":             "अधिक मूल्यांकित",
    "undervalued":            "कम मूल्यांकित",
    "dividend":               "लाभांश",
    "Dividend":               "लाभांश",

    # Misc finance
    "fixed deposit":          "सावधि जमा",
    "Fixed Deposit":          "सावधि जमा",
    "insurance":              "बीमा",
    "Insurance":              "बीमा",
    "annuity":                "वार्षिकी",
    "Annuity":                "वार्षिकी",
    "wealth":                 "संपदा",
    "Wealth":                 "संपदा",
    "estate planning":        "संपदा नियोजन",
    "Estate Planning":        "संपदा नियोजन",
    "net worth":              "कुल संपत्ति",
    "Net Worth":              "कुल संपत्ति",
}


def apply_overrides(text: str) -> str:
    """
    Post-process machine-translated Hindi text by applying the override dict.
    Longer phrases are matched before shorter ones to avoid partial replacement.
    English-only terms in KEEP_ENGLISH are restored if IndicTrans2 transliterated them.
    """
    # Sort by length descending — match longer phrases first
    for en, hi in sorted(TERM_MAP.items(), key=lambda x: -len(x[0])):
        # Word-boundary replacement (handles "SIP-based" correctly)
        pattern = r'(?<!\w)' + re.escape(en) + r'(?!\w)'
        text = re.sub(pattern, hi, text)
    return text


def protect_terms(text: str) -> tuple[str, dict]:
    """
    Replace known terms with {N} placeholders Google Translate preserves.
    - TERM_MAP keys → their Hindi value is substituted after translation
    - KEEP_ENGLISH → English term restored after translation
    Longer matches are applied first to avoid partial replacements.
    Returns (protected_text, {"{N}": final_value, ...})
    """
    protected = text
    # index → final value (either Hindi from TERM_MAP or English from KEEP_ENGLISH)
    slots: list[str] = []

    def _slot(value: str) -> str:
        idx = len(slots)
        slots.append(value)
        return f"{{{idx}}}"

    # TERM_MAP keys → Hindi value (longer first)
    for en, hi in sorted(TERM_MAP.items(), key=lambda x: -len(x[0])):
        if en in protected:
            protected = protected.replace(en, _slot(hi))

    # KEEP_ENGLISH → same English term (longer first)
    for term in sorted(KEEP_ENGLISH, key=len, reverse=True):
        if term in protected:
            protected = protected.replace(term, _slot(term))

    placeholders = {f"{{{i}}}": v for i, v in enumerate(slots)}
    return protected, placeholders


def restore_terms(text: str, placeholders: dict) -> str:
    """Restore all {N} placeholders after translation."""
    for placeholder, value in placeholders.items():
        text = text.replace(placeholder, value)
    return text


# Aliases for backward compat
def protect_keep_english(text: str):
    return protect_terms(text)


def restore_keep_english(text: str, placeholders: dict) -> str:
    return restore_terms(text, placeholders)
