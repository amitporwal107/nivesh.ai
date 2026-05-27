"""NIDP Sector-Aware Stock Quality Scoring Framework.

7 sector profiles (BANK, NBFC, CYCLICAL, IT, FMCG, PHARMA, CAPGOODS) + DEFAULT.
Each profile computes a sector-specific fundamental sub-score. A cross-sector
technical sub-score is applied universally. Final composite = fund×w + tech×w
+ cycle×w (CYCLICAL only) + event_overlay − red_flag_penalty.

Entry point: composer.score_stock(prims, tech_data, bank_metrics, event_signals)
"""
