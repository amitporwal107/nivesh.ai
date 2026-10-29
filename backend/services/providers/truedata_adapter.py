"""TrueDataAdapter: TrueData's REST data as the provider contract's ProviderResult (docs/charting.md §32.4).

The client (nidp/shared/sources/truedata.py) does the calls and classifies TrueData's failures. This adapter turns every
outcome into a ProviderResult, so a caller never sees a raised exception or TrueData's own format. An empty answer is
DQ_EMPTY with EMPTY_RESPONSE; any other failure is DQ_BLOCKED with its reason code.

What every price result states rather than hides (measured on the trial, 29 Oct 2026):
  * price_adjustment = ADJUSTED: bars and past bhavcopies are adjusted for later corporate actions;
  * traded contracts only: an untraded option or future is absent from TrueData's bhavcopy, not zero.

The switch decides (backend/config/market_data_source.json, nidp/shared/market_data_source.py): unless TrueData is on
(shadow or truedata, after every safety gate), each call returns DQ_BLOCKED / NOT_CONFIGURED with `switched_off` in its
meta and TrueData is never called. So `current`, in the file or forced with MARKET_DATA_SOURCE_FORCE_CURRENT=1, is a
complete way back to our own feeds. Not wired to any route or job in this PR; the switch ships on `current`.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional

from nidp.shared import market_data_source as mds
from nidp.shared.sources import truedata as td

from .contract import (
    DQ_BLOCKED, DQ_EMPTY, DQ_OK, EMPTY_RESPONSE, NOT_CONFIGURED, PROVIDER_TRUEDATA, ProviderResult, new_request_id,
    utcnow,
)

PROVIDER_VERSION = td.CLIENT_VERSION
NORMALIZATION_VERSION = "truedata-v1"


class TrueDataAdapter:
    provider_id = PROVIDER_TRUEDATA
    provider_version = PROVIDER_VERSION

    def __init__(self, client: Optional[td.TrueDataClient] = None, *,
                 switch: Callable[[], mds.Resolution] = mds.resolve):
        self._client = client or td.TrueDataClient()
        self._switch = switch

    @property
    def configured(self) -> bool:
        return self._client.configured

    def _run(self, identifier: str, call: Callable[[], List[Dict[str, Any]]], meta: Dict[str, Any],
             ts_field: Optional[str] = "timestamp") -> ProviderResult:
        request_id, requested_at = new_request_id(), utcnow()
        resolution = self._switch()
        if not mds.truedata_is_on(resolution):
            records, error_code, retryable = [], NOT_CONFIGURED, False
            meta = {**meta, "switched_off": True, "market_data_source": resolution.effective,
                    "message": mds.truedata_off_message(resolution)}
        else:
            try:
                records = call()
                error_code, retryable = None, False
            except td.TrueDataError as e:
                records, error_code, retryable = [], e.code, e.retryable
                meta = {**meta, "message": e.message}
        received_at = utcnow()
        if error_code is None and not records:
            error_code = EMPTY_RESPONSE
        if error_code is None:
            status = DQ_OK
        elif error_code == EMPTY_RESPONSE:
            status = DQ_EMPTY
        else:
            status = DQ_BLOCKED
        last_ts = None
        if records and ts_field:
            stamps = [str(r[ts_field]) for r in records if r.get(ts_field)]
            last_ts = max(stamps) if stamps else None
        return ProviderResult(
            provider_id=self.provider_id, provider_version=self.provider_version, request_id=request_id,
            requested_at=requested_at, response_received_at=received_at, instrument_identifier=identifier,
            source_timestamp=last_ts, availability_timestamp=received_at.isoformat(),
            normalized_records=records, data_quality_status=status, error_code=error_code, retryable=retryable,
            meta={**meta, "normalization_version": NORMALIZATION_VERSION, "count": len(records)},
        )

    def fetch_bars(self, symbol: str, start: datetime, end: datetime, interval: str = "eod",
                   delivery: bool = False) -> ProviderResult:
        return self._run(symbol, lambda: self._client.bars(symbol, start, end, interval, delivery), {
            "interval": interval, "requested_range": [start.isoformat(), end.isoformat()],
            "series_type": "EOD" if interval == "eod" else "INTRADAY", "price_adjustment": "ADJUSTED"})

    def fetch_bhavcopy(self, segment: str, day: date) -> ProviderResult:
        return self._run(f"{segment.upper()}:{day.isoformat()}", lambda: self._client.bhavcopy(segment, day), {
            "segment": segment.upper(), "date": day.isoformat(), "price_adjustment": "ADJUSTED",
            "coverage": "traded contracts only (an untraded contract is absent, not zero)"})

    def fetch_symbol_master(self, segment: str, search: Optional[str] = None) -> ProviderResult:
        return self._run(f"master:{segment}", lambda: self._client.symbol_master(segment, search), {
            "segment": segment, "search": search}, ts_field=None)

    def fetch_corporate_actions(self, ex_from: date, ex_to: date) -> ProviderResult:
        return self._run("corporate_actions", lambda: self._client.corporate_actions(ex_from, ex_to), {
            "ex_date_range": [ex_from.isoformat(), ex_to.isoformat()],
            "ratio": "TrueData's price adjustment ratio (bonus 1:1 = 2, split 10 to 2 = 5)"}, ts_field=None)
