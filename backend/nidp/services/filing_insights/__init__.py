"""filing_insights — stage-7 generator.

For each MATERIAL corporate announcement that has a parsed document, prompt an
LLM over the parsed PDF text and write one structured insight row into
nidp.corporate_event_signals (signal_type='filing_insight'). This is what
populates the Filings Home feed's `one` / `period` / `metric` / `hasInsights`.

See docs/FILINGS_HOME_SPEC.md §3.3 / step 3.
"""
