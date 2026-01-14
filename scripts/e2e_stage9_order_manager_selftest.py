# -*- coding: utf-8 -*-
"""Stage 9 selftest (pure logic, no external dependencies).

Run:
  python -m scripts.e2e_stage9_order_manager_selftest
"""

import os

os.environ.setdefault('DATABASE_URL', 'postgresql://postgres:postgres@localhost:5432/trading_ci')
os.environ.setdefault('REDIS_URL', 'redis://localhost:6379/0')


from services.execution.order_manager import _compute_retry_price
from libs.mq.risk_normalize import normalize_risk_type


def test_retry_price():
    # BUY: price up
    p1 = _compute_retry_price(base_price=100.0, side="BUY", bps=10, attempt=1)
    assert p1 > 100.0
    # SELL: price down
    p2 = _compute_retry_price(base_price=100.0, side="SELL", bps=10, attempt=1)
    assert p2 < 100.0
    # attempt scaling
    p3 = _compute_retry_price(base_price=100.0, side="BUY", bps=10, attempt=2)
    assert p3 > p1


def test_risk_types():
    for t in ["ORDER_TIMEOUT", "ORDER_PARTIAL_FILL", "ORDER_RETRY", "ORDER_FALLBACK_MARKET", "ORDER_CANCELLED"]:
        assert normalize_risk_type(t) == t


def main():
    test_retry_price()
    test_risk_types()
    print("Stage9 selftest OK")


if __name__ == "__main__":
    main()
