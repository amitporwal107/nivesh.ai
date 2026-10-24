"""Order management: the order lifecycle every future execution path must go through.

WHY THIS EXISTS
No order is placed anywhere in this system today. The F&O PRD (§12) requires that, before one is, every
order has an explicit lifecycle, cannot be submitted twice, and treats an unknown broker state as a
reason to reconcile rather than to resubmit. This package fixes that contract first, so the paper path
and a later Kite Connect adapter share one state model.

WHAT IS HERE
    states.py   the PRD §12.1 states and the transitions allowed between them
    orders.py   an idempotent order store (`oms_orders`), keyed per user by `client_order_id`

WHAT IS NOT: there is no broker adapter and no route. Live mode is refused by `orders.create_order`.
"""
