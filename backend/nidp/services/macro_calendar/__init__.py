"""nidp-macro-calendar: scheduled India / US macro releases from free sources.

Sources
    US     FRED API (api.stlouisfed.org): release dates, and first-release values from the ALFRED vintage matrix
           (series/observations?output_type=2); the Fed's FOMC calendar page for the meeting dates.
    India  MoSPI Advance Release Calendar PDF (CPI, IIP, GDP, PLFS dates), RBI press release for the MPC schedule,
           rbi.org.in home page for the current policy repo rate.
Output     nidp.macro_releases (one row per indicator per release date).

No source here publishes consensus forecasts, so `estimate` stays NULL. Impact and the release times are editorial.
Anything a source does not give is NULL and named in the desk API's `gaps`; nothing is guessed.
"""
__all__ = ["catalog", "fred_us", "india", "service", "writer"]
