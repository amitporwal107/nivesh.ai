"""NIDP annual-report feed.

Per-scrip sweep of BSE's AnnualReport_New endpoint across the equity universe
(ref.security_master). Registers each annual-report PDF in nidp.documents
pre-typed doc_type='annual_report' for the existing document_parser to ingest.
"""
