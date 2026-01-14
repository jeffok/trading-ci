# -*- coding: utf-8 -*-
"""Stage 5: local self-test for Bybit rate limiter.

This script does NOT call Bybit.
It simulates a burst of calls across multiple symbols, mixing:
- critical private calls (order/create)
- order queries (order/realtime)
- account queries (position/list / wallet)

Expected:
- critical calls should show consistently lower wait vs queries under load
- per-symbol limits should prevent N symbols from multiplying qps too much

Run:
  python scripts/ratelimit_selftest.py
"""

from __future__ import annotations

import random
import time

from libs.common.config import settings
from libs.bybit.ratelimit import EndpointGroup, get_rate_limiter


def main() -> None:
    rl = get_rate_limiter(settings)

    symbols = ["BTCUSDT", "ETHUSDT", "BCHUSDT", "SOLUSDT", "XRPUSDT"]

    print("Limiter config:")
    print(f"  max_wait_ms={rl.max_wait_ms} low_status_threshold={rl.low_status_threshold}")
    print("  env overrides:")
    for k in [
        "BYBIT_PUBLIC_RPS",
        "BYBIT_PRIVATE_CRITICAL_RPS",
        "BYBIT_PRIVATE_ORDER_QUERY_RPS",
        "BYBIT_PRIVATE_ACCOUNT_QUERY_RPS",
        "BYBIT_PRIVATE_PER_SYMBOL_ORDER_QUERY_RPS",
        "BYBIT_PRIVATE_PER_SYMBOL_ACCOUNT_QUERY_RPS",
        "BYBIT_RATE_LIMIT_MAX_WAIT_MS",
    ]:
        print(f"    {k}={getattr(settings, k.lower(), None)}")

    stats = {"crit_wait_ms": [], "order_query_wait_ms": [], "account_query_wait_ms": []}

    start = time.time()
    for i in range(200):
        sym = random.choice(symbols)
        # 25% critical, 45% order-query, 30% account-query
        r = random.random()
        if r < 0.25:
            gw, sw = rl.acquire(group=EndpointGroup.PRIVATE_CRITICAL, symbol=sym)
            w = max(gw, sw)
            stats["crit_wait_ms"].append(w)
        elif r < 0.70:
            gw, sw = rl.acquire(group=EndpointGroup.PRIVATE_ORDER_QUERY, symbol=sym)
            w = max(gw, sw)
            stats["order_query_wait_ms"].append(w)
        else:
            gw, sw = rl.acquire(group=EndpointGroup.PRIVATE_ACCOUNT_QUERY, symbol=sym)
            w = max(gw, sw)
            stats["account_query_wait_ms"].append(w)

        # no actual sleep here; we only measure predicted waits from token bucket
        if i % 50 == 0 and i > 0:
            # let time pass so buckets refill
            time.sleep(0.4)

    elapsed = (time.time() - start) * 1000

    def p(xs, q):
        if not xs:
            return 0
        xs2 = sorted(xs)
        idx = int((len(xs2) - 1) * q)
        return xs2[idx]

    print("\nResults (ms):")
    for k in ["crit_wait_ms", "order_query_wait_ms", "account_query_wait_ms"]:
        xs = stats[k]
        print(
            f"  {k}: n={len(xs)} mean={sum(xs)/max(1,len(xs)):.1f} "
            f"p50={p(xs,0.50)} p90={p(xs,0.90)} p99={p(xs,0.99)} max={max(xs) if xs else 0}"
        )

    print(f"\nDone. elapsed={elapsed:.0f}ms")


if __name__ == "__main__":
    main()
