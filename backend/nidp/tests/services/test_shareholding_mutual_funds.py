"""NSE shareholding XBRL: the mutual-fund line is tagged MutualFundsOrUTI_ContextI."""
from nidp.services.nse_shareholding.parser import parse_xbrl_document

# MOCK — not real data: a trimmed v1.1 filing built from the context names of a real archived
# filing (SHP_1740023_16102026043243_WEB.xml on the staging warehouse VM); values are invented.
_DOC = """<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:in-bse-shp="http://www.bseindia.com/xbrl/shp">
  <xbrli:context id="ShareholdingPattern_ContextI"><xbrli:entity/><xbrli:period><xbrli:instant>2026-09-30</xbrli:instant></xbrli:period></xbrli:context>
  <xbrli:context id="MutualFundsOrUTI_ContextI"><xbrli:entity/><xbrli:period><xbrli:instant>2026-09-30</xbrli:instant></xbrli:period></xbrli:context>
  <xbrli:context id="InstitutionsDomestic_ContextI"><xbrli:entity/><xbrli:period><xbrli:instant>2026-09-30</xbrli:instant></xbrli:period></xbrli:context>
  <xbrli:context id="InstitutionsForeign_ContextI"><xbrli:entity/><xbrli:period><xbrli:instant>2026-09-30</xbrli:instant></xbrli:period></xbrli:context>
  <xbrli:context id="ShareholdingOfPromoterAndPromoterGroup_ContextI"><xbrli:entity/><xbrli:period><xbrli:instant>2026-09-30</xbrli:instant></xbrli:period></xbrli:context>
  <in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="ShareholdingOfPromoterAndPromoterGroup_ContextI">0.4000</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>
  <in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="InstitutionsForeign_ContextI">0.2000</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>
  <in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="InstitutionsDomestic_ContextI">0.2500</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>
  <in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares contextRef="MutualFundsOrUTI_ContextI">0.1250</in-bse-shp:ShareholdingAsAPercentageOfTotalNumberOfShares>
  <in-bse-shp:NumberOfFullyPaidUpEquityShares contextRef="ShareholdingPattern_ContextI">1000000</in-bse-shp:NumberOfFullyPaidUpEquityShares>
</xbrli:xbrl>"""

_MANIFEST = {"symbol": "TESTCO", "company_name": "Testco", "period_end": "2026-09-30",
             "filing_id": "1", "xbrl_url": "x", "broadcast_at": None}


def test_mutual_fund_percentage_is_read_from_the_real_context_name():
    (row,) = parse_xbrl_document(_DOC.encode(), _MANIFEST)
    assert row["mf_pct"] == 12.5
    assert (row["promoter_pct"], row["fii_pct"], row["dii_pct"]) == (40.0, 20.0, 25.0)
