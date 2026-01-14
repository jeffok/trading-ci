# -*- coding: utf-8 -*-
"""Stage 10 selftest: wallet drift helpers (no env / no external deps).

Run:
  python scripts/e2e_stage10_wallet_drift_selftest.py
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


def parse_wallet_rest(payload: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    bal = eq = avail = None
    try:
        lst = payload.get("result", {}).get("list", [])
        if lst and lst[0].get("coin"):
            c = lst[0]["coin"][0]
            if c.get("walletBalance") is not None:
                bal = float(c["walletBalance"])
            if c.get("equity") is not None:
                eq = float(c["equity"])
            for k in ("availableToWithdraw", "availableBalance"):
                if c.get(k) is not None:
                    avail = float(c[k])
                    break
    except Exception:
        pass
    return bal, eq, avail


def wallet_drift_pct(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    denom = abs(b) if abs(b) > 1e-9 else None
    if denom is None:
        return None
    return abs(a - b) / denom


def main() -> None:
    rest = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {
            "list": [
                {
                    "accountType": "UNIFIED",
                    "coin": [
                        {
                            "coin": "USDT",
                            "walletBalance": "1000.0",
                            "equity": "980.0",
                            "availableToWithdraw": "900.0",
                        }
                    ],
                }
            ]
        },
    }
    bal, eq, avail = parse_wallet_rest(rest)
    assert abs(bal - 1000.0) < 1e-6
    assert abs(eq - 980.0) < 1e-6
    assert abs(avail - 900.0) < 1e-6

    drift = wallet_drift_pct(eq, 1000.0)
    assert drift is not None
    assert abs(drift - 0.02) < 1e-6

    print("Stage10 wallet drift selftest OK")


if __name__ == "__main__":
    main()
