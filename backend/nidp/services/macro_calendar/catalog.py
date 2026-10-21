"""The indicators the desk calendar carries: our editorial choices (which ones, impact, usual release time).

`impact` and `time_local` are EDITORIAL: no free source rates a release's market impact, and the FRED / MoSPI / RBI
calendars give dates, not times. Times are the agencies' usual publication times and are stored with
time_is_typical = TRUE.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

NY = "America/New_York"
IST = "Asia/Kolkata"

FRED_RELEASE_URL = "https://fred.stlouisfed.org/release?rid={rid}"
FED_FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
MOSPI_CALENDAR_URL = "https://mospi.gov.in/release-calendar"
RBI_HOME_URL = "https://www.rbi.org.in/"
RBI_MPC_SCHEDULE_URL = "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=62422"  # MPC schedule 2026-27


@dataclass(frozen=True)
class Indicator:
    code: str
    country: str
    name: str
    short: str
    impact: str                      # H / M / L, editorial
    unit: str
    time_local: Optional[str]        # 'HH:MM' in tz, the usual publication time
    tz: Optional[str]
    # FRED-driven indicators only
    series: Optional[str] = None
    release_id: Optional[int] = None
    kind: Optional[str] = None       # yoy | mom | chg | level
    scale: float = 1.0               # multiply the transformed value (claims persons → thousands)
    freq: Optional[str] = None       # M | W | Q


US: Dict[str, Indicator] = {i.code: i for i in (
    Indicator("US_CPI_YOY", "US", "CPI inflation YoY", "CPI", "H", "%", "08:30", NY, "CPIAUCNS", 10, "yoy", 1.0, "M"),
    Indicator("US_CORE_PCE_YOY", "US", "Core PCE price index YoY", "Core PCE", "H", "%", "08:30", NY, "PCEPILFE", 54, "yoy", 1.0, "M"),
    Indicator("US_NFP", "US", "Non-farm payrolls", "NFP", "H", "K", "08:30", NY, "PAYEMS", 50, "chg", 1.0, "M"),
    Indicator("US_UNRATE", "US", "Unemployment rate", "Unemployment", "M", "%", "08:30", NY, "UNRATE", 50, "level", 1.0, "M"),
    Indicator("US_GDP_QOQ", "US", "GDP growth rate QoQ, annualised", "GDP", "H", "%", "08:30", NY, "A191RL1Q225SBEA", 53, "level", 1.0, "Q"),
    Indicator("US_JOBLESS_CLAIMS", "US", "Initial jobless claims", "Jobless claims", "L", "K", "08:30", NY, "ICSA", 180, "level", 0.001, "W"),
    Indicator("US_RETAIL_MOM", "US", "Retail sales MoM", "Retail sales", "M", "%", "08:30", NY, "RSAFS", 9, "mom", 1.0, "M"),
    Indicator("US_PPI_YOY", "US", "PPI final demand YoY", "PPI", "M", "%", "08:30", NY, "PPIFIS", 46, "yoy", 1.0, "M"),
)}
FOMC = Indicator("US_FOMC", "US", "Fed interest rate decision", "Fed decision", "H", "%", "14:00", NY, "DFEDTARU")

IN: Dict[str, Indicator] = {i.code: i for i in (
    Indicator("IN_RBI_MPC", "IN", "RBI interest rate decision", "RBI rate", "H", "%", "10:00", IST),
    Indicator("IN_CPI", "IN", "CPI inflation YoY", "CPI", "H", "%", "16:00", IST),
    Indicator("IN_IIP", "IN", "Industrial production YoY", "IIP", "M", "%", "16:00", IST),
    Indicator("IN_GDP", "IN", "GDP growth rate YoY", "GDP", "H", "%", "16:00", IST),
    Indicator("IN_PLFS", "IN", "Unemployment rate, PLFS monthly bulletin", "PLFS", "L", "%", None, None),
)}

ALL: Dict[str, Indicator] = {**US, FOMC.code: FOMC, **IN}


def make_row(ind: Indicator, release_date, period: Optional[str], previous, actual, source: str, source_url: Optional[str],
             time_local: Optional[str] = ..., tz: Optional[str] = ...) -> dict:
    """One nidp.macro_releases row (without run id / timestamps). `estimate` is always None: no free source has one."""
    return {
        "indicator_code": ind.code, "release_date": release_date, "country": ind.country, "name": ind.name,
        "short_name": ind.short,
        "release_time": ind.time_local if time_local is ... else time_local,
        "release_tz": ind.tz if tz is ... else tz,
        "time_is_typical": True, "period": period, "previous": previous, "estimate": None, "actual": actual,
        "unit": ind.unit, "impact": ind.impact, "source": source, "source_url": source_url,
    }
