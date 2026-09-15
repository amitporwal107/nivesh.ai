"""Catalyst Intelligence Engine (CIE) — Phase 1: the source layer.

Every calendar day, including weekends and exchange holidays, pull the regulators, exchanges, ministries and news
sources in registry.SOURCES, turn each item into a raw event that records where it came from, when the source says it
was published and when we received it, and keep it once (content hash) under a JSONL-per-day-per-source store with a
SQLite index. Nothing here classifies, resolves entities or scores; that is Phase 3 (see the CIE spec).
"""
