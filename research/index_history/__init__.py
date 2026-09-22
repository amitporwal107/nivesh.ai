"""research.index_history — daily index history (Kite Connect) + derived market breadth
for the research charting engine.

Modules:
    manifest      — sealed out-of-sample window, sha256 hashing, manifest.json helpers
    kite_client   — Kite Connect auth/instrument-resolution/chunked historical fetch
    fetch_indices — fetches + saves data/<SLUG>.csv per index, updates manifest.json
    crosscheck    — compares fetched closes against pre-existing local CSVs
    breadth       — derives market-breadth indicators from the Kite daily-bar universe

Data lives under data/ (git-ignored-scale CSVs written by fetch_indices/breadth, not
checked in by hand). Nothing here ever prints, logs, or writes an API key, secret, or
access token.
"""
