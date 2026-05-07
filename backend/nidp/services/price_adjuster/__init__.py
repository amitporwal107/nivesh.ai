"""nidp-price-adjuster — derive corp-action-adjusted EOD prices.

Reads:    nidp.prices_eod ⋈ nidp.corporate_actions
Writes:   nidp.prices_eod_adjusted
Cadence:  Nightly after corp_actions ingester succeeds; can also be
          run ad-hoc when a backfill of new historical CA lands.
"""
