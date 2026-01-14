# -*- coding: utf-8 -*-
"""In-process Bybit REST rate limiting (single-instance).

Stage 4:
1) Split private endpoints into *critical* (order/create, trading-stop, cancel) vs *query* buckets.
2) Apply both global and per-symbol limiting.
3) Support adaptive cooldown based on Bybit reset headers / retry-after.

This limiter is deliberately process-local. It is sufficient for a single-instance deployment,
and dramatically reduces 10006 storms when monitoring many symbols.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple


def _now_ms() -> int:
    return int(time.time() * 1000)


class EndpointGroup(str, Enum):
    PUBLIC = "public"
    PRIVATE_CRITICAL = "private_critical"
    # Stage 5: split private queries to protect critical path and isolate high-frequency order polling.
    PRIVATE_ORDER_QUERY = "private_order_query"
    PRIVATE_ACCOUNT_QUERY = "private_account_query"


@dataclass
class BucketConfig:
    rate_per_sec: float
    burst: float


class TokenBucket:
    """Simple token bucket (thread-safe).

    - rate_per_sec: refill tokens per second
    - burst: maximum capacity

    We also support:
    - cooldown_until_ms: hard stop until a known reset time
    - rate_multiplier: adaptive throttling (0.1..1.0)
    """

    def __init__(self, *, rate_per_sec: float, burst: float):
        self._base_rate = float(max(0.01, rate_per_sec))
        self._burst = float(max(1.0, burst))
        self._tokens = self._burst
        self._last_ms = _now_ms()
        self._cooldown_until_ms = 0
        self._rate_multiplier = 1.0
        self._lock = threading.Lock()

    def set_cooldown_until(self, reset_ts_ms: int) -> None:
        with self._lock:
            self._cooldown_until_ms = max(self._cooldown_until_ms, int(reset_ts_ms))

    def set_rate_multiplier(self, mul: float) -> None:
        with self._lock:
            self._rate_multiplier = float(min(1.0, max(0.1, mul)))

    def _refill(self, now_ms: int) -> None:
        if now_ms <= self._last_ms:
            return
        elapsed = (now_ms - self._last_ms) / 1000.0
        rate = self._base_rate * self._rate_multiplier
        self._tokens = min(self._burst, self._tokens + elapsed * rate)
        self._last_ms = now_ms

    def estimate_wait_ms(self, cost: float = 1.0) -> int:
        with self._lock:
            now = _now_ms()
            if now < self._cooldown_until_ms:
                return int(self._cooldown_until_ms - now)
            self._refill(now)
            if self._tokens >= cost:
                return 0
            # need more tokens
            needed = max(0.0, cost - self._tokens)
            rate = max(0.01, self._base_rate * self._rate_multiplier)
            return int((needed / rate) * 1000)

    def acquire(self, cost: float = 1.0) -> int:
        """Consume tokens. Return wait_ms required before request can proceed."""
        with self._lock:
            now = _now_ms()
            if now < self._cooldown_until_ms:
                return int(self._cooldown_until_ms - now)
            self._refill(now)
            if self._tokens >= cost:
                self._tokens -= cost
                return 0
            # Not enough tokens; compute wait.
            needed = max(0.0, cost - self._tokens)
            rate = max(0.01, self._base_rate * self._rate_multiplier)
            wait_ms = int((needed / rate) * 1000)
            # After waiting, tokens would be available; pessimistically set tokens to 0.
            self._tokens = 0.0
            self._last_ms = now
            return wait_ms


class BybitRateLimiter:
    """Rate limiter with endpoint groups and per-symbol buckets."""

    def __init__(
        self,
        *,
        public: BucketConfig,
        private_critical: BucketConfig,
        private_order_query: BucketConfig,
        private_account_query: BucketConfig,
        per_symbol_order_query: BucketConfig,
        per_symbol_account_query: BucketConfig,
        per_symbol_critical: BucketConfig,
        max_wait_ms: int = 5_000,
        low_status_threshold: int = 2,
    ):
        self._public = TokenBucket(rate_per_sec=public.rate_per_sec, burst=public.burst)
        self._priv_crit = TokenBucket(rate_per_sec=private_critical.rate_per_sec, burst=private_critical.burst)
        self._priv_order_q = TokenBucket(rate_per_sec=private_order_query.rate_per_sec, burst=private_order_query.burst)
        self._priv_account_q = TokenBucket(rate_per_sec=private_account_query.rate_per_sec, burst=private_account_query.burst)
        self._sym_order_q_cfg = per_symbol_order_query
        self._sym_account_q_cfg = per_symbol_account_query
        self._sym_c_cfg = per_symbol_critical
        self._sym_order_q: Dict[str, TokenBucket] = {}
        self._sym_account_q: Dict[str, TokenBucket] = {}
        self._sym_c: Dict[str, TokenBucket] = {}
        self._lock = threading.Lock()
        self.max_wait_ms = int(max_wait_ms)
        self.low_status_threshold = int(low_status_threshold)

    def _get_sym_bucket(self, *, symbol: str, group: EndpointGroup) -> Optional[TokenBucket]:
        if not symbol:
            return None
        with self._lock:
            if group == EndpointGroup.PRIVATE_CRITICAL:
                b = self._sym_c.get(symbol)
                if b is None:
                    b = TokenBucket(rate_per_sec=self._sym_c_cfg.rate_per_sec, burst=self._sym_c_cfg.burst)
                    self._sym_c[symbol] = b
                return b
            if group == EndpointGroup.PRIVATE_ORDER_QUERY:
                b = self._sym_order_q.get(symbol)
                if b is None:
                    b = TokenBucket(rate_per_sec=self._sym_order_q_cfg.rate_per_sec, burst=self._sym_order_q_cfg.burst)
                    self._sym_order_q[symbol] = b
                return b
            if group == EndpointGroup.PRIVATE_ACCOUNT_QUERY:
                b = self._sym_account_q.get(symbol)
                if b is None:
                    b = TokenBucket(rate_per_sec=self._sym_account_q_cfg.rate_per_sec, burst=self._sym_account_q_cfg.burst)
                    self._sym_account_q[symbol] = b
                return b
        return None

    # --- acquisition / estimation ---
    def estimate_wait_ms(self, *, group: EndpointGroup, symbol: str = "") -> int:
        if group == EndpointGroup.PUBLIC:
            return self._public.estimate_wait_ms(1.0)
        if group == EndpointGroup.PRIVATE_CRITICAL:
            gb = self._priv_crit
        elif group == EndpointGroup.PRIVATE_ORDER_QUERY:
            gb = self._priv_order_q
        else:
            gb = self._priv_account_q
        sb = self._get_sym_bucket(symbol=symbol, group=group)
        sw = sb.estimate_wait_ms(1.0) if sb is not None else 0
        return max(gb.estimate_wait_ms(1.0), sw)

    def acquire(self, *, group: EndpointGroup, symbol: str = "") -> Tuple[int, int]:
        """Return (global_wait_ms, symbol_wait_ms)."""
        if group == EndpointGroup.PUBLIC:
            w = self._public.acquire(1.0)
            return (w, 0)

        if group == EndpointGroup.PRIVATE_CRITICAL:
            gb = self._priv_crit
        elif group == EndpointGroup.PRIVATE_ORDER_QUERY:
            gb = self._priv_order_q
        else:
            gb = self._priv_account_q

        sb = self._get_sym_bucket(symbol=symbol, group=group)
        gw = gb.acquire(1.0)
        sw = sb.acquire(1.0) if sb is not None else 0
        return (gw, sw)

    # --- adaptive controls from headers ---
    def apply_rate_limit_reset(self, *, group: EndpointGroup, symbol: str, reset_ts_ms: int) -> None:
        if group == EndpointGroup.PUBLIC:
            self._public.set_cooldown_until(reset_ts_ms)
            return
        if group == EndpointGroup.PRIVATE_CRITICAL:
            self._priv_crit.set_cooldown_until(reset_ts_ms)
        elif group == EndpointGroup.PRIVATE_ORDER_QUERY:
            self._priv_order_q.set_cooldown_until(reset_ts_ms)
        else:
            self._priv_account_q.set_cooldown_until(reset_ts_ms)
        sb = self._get_sym_bucket(symbol=symbol, group=group)
        if sb is not None:
            sb.set_cooldown_until(reset_ts_ms)

    def apply_limit_status(self, *, group: EndpointGroup, symbol: str, remaining: Optional[int], limit: Optional[int] = None) -> None:
        """Adaptive throttling based on remaining/limit ratio.

        - Critical endpoints get a *less aggressive* slowdown.
        - Query endpoints get a *more aggressive* slowdown when remaining budget is low.
        """
        if remaining is None:
            return

        ratio = None
        if limit is not None and limit > 0:
            try:
                ratio = float(remaining) / float(limit)
            except Exception:
                ratio = None

        # default multipliers
        if ratio is None:
            # fallback: threshold-based
            if remaining <= self.low_status_threshold:
                ratio = 0.05
            else:
                ratio = 1.0

        # compute multipliers per group
        if group == EndpointGroup.PRIVATE_CRITICAL:
            # preserve critical path as much as possible
            mul = 0.6 if ratio < 0.25 else 1.0
        elif group == EndpointGroup.PUBLIC:
            mul = 0.5 if ratio < 0.25 else 1.0
        else:
            # queries throttle harder
            if ratio < 0.10:
                mul = 0.2
            elif ratio < 0.25:
                mul = 0.5
            else:
                mul = 1.0

        # apply
        if group == EndpointGroup.PUBLIC:
            self._public.set_rate_multiplier(mul)
            return

        if group == EndpointGroup.PRIVATE_CRITICAL:
            self._priv_crit.set_rate_multiplier(mul)
        elif group == EndpointGroup.PRIVATE_ORDER_QUERY:
            self._priv_order_q.set_rate_multiplier(mul)
        else:
            self._priv_account_q.set_rate_multiplier(mul)

        sb = self._get_sym_bucket(symbol=symbol, group=group)
        if sb is not None:
            sb.set_rate_multiplier(mul)

    def update_from_headers(self, *, group: EndpointGroup, symbol: str, headers: Dict[str, str]) -> None:
        """Single entry-point for adaptive limiter updates."""
        remain: Optional[int] = None
        limit: Optional[int] = None
        try:
            # Bybit uses X-Bapi-Limit-Status for remaining, X-Bapi-Limit for limit.
            for k in ("x-bapi-limit-status", "X-Bapi-Limit-Status"):
                if k in headers:
                    remain = int(float(headers[k]))
                    break
            for k in ("x-bapi-limit", "X-Bapi-Limit"):
                if k in headers:
                    limit = int(float(headers[k]))
                    break
            self.apply_limit_status(group=group, symbol=symbol, remaining=remain, limit=limit)
        except Exception:
            pass
        try:
            reset_ts = None
            for k in ("x-bapi-limit-reset-timestamp", "X-Bapi-Limit-Reset-Timestamp"):
                if k in headers:
                    n = int(float(headers[k]))
                    if n < 10_000_000_000:
                        n *= 1000
                    reset_ts = n
                    break
            # Only enforce cooldown when budget is exhausted/low, or when Retry-After is explicitly present.
            if reset_ts is not None:
                ra = headers.get("retry-after") or headers.get("Retry-After")
                force = ra is not None
                if not force and remain is not None:
                    force = remain <= self.low_status_threshold
                if force:
                    # Also use Retry-After if present (seconds)
                    if ra is not None:
                        try:
                            sec = float(ra)
                            reset_ts = max(reset_ts, _now_ms() + int(sec * 1000))
                        except Exception:
                            pass
                    self.apply_rate_limit_reset(group=group, symbol=symbol, reset_ts_ms=reset_ts)
        except Exception:
            pass


# Singleton (single process)
_limiter_singleton: Optional[BybitRateLimiter] = None


def get_rate_limiter(settings_obj) -> BybitRateLimiter:
    global _limiter_singleton
    if _limiter_singleton is not None:
        return _limiter_singleton

    public = BucketConfig(
        rate_per_sec=float(getattr(settings_obj, "bybit_public_rps", 8.0)),
        burst=float(getattr(settings_obj, "bybit_public_burst", 16.0)),
    )
    private_critical = BucketConfig(
        rate_per_sec=float(getattr(settings_obj, "bybit_private_critical_rps", 3.0)),
        burst=float(getattr(settings_obj, "bybit_private_critical_burst", 6.0)),
    )
    # Stage 5: split query budgets; fall back to the generic BYBIT_PRIVATE_QUERY_* if per-bucket vars are not set.
    oq_rps = float(getattr(settings_obj, "bybit_private_order_query_rps", getattr(settings_obj, "bybit_private_query_rps", 2.0)))
    oq_burst = float(getattr(settings_obj, "bybit_private_order_query_burst", getattr(settings_obj, "bybit_private_query_burst", 4.0)))
    aq_rps = float(getattr(settings_obj, "bybit_private_account_query_rps", getattr(settings_obj, "bybit_private_query_rps", 2.0)))
    aq_burst = float(getattr(settings_obj, "bybit_private_account_query_burst", getattr(settings_obj, "bybit_private_query_burst", 4.0)))

    private_order_query = BucketConfig(rate_per_sec=oq_rps, burst=oq_burst)
    private_account_query = BucketConfig(rate_per_sec=aq_rps, burst=aq_burst)

    so_rps = float(getattr(settings_obj, "bybit_private_per_symbol_order_query_rps", getattr(settings_obj, "bybit_private_per_symbol_query_rps", 0.7)))
    so_burst = float(getattr(settings_obj, "bybit_private_per_symbol_order_query_burst", getattr(settings_obj, "bybit_private_per_symbol_query_burst", 1.5)))
    sa_rps = float(getattr(settings_obj, "bybit_private_per_symbol_account_query_rps", getattr(settings_obj, "bybit_private_per_symbol_query_rps", 0.7)))
    sa_burst = float(getattr(settings_obj, "bybit_private_per_symbol_account_query_burst", getattr(settings_obj, "bybit_private_per_symbol_query_burst", 1.5)))
    per_symbol_order_query = BucketConfig(rate_per_sec=so_rps, burst=so_burst)
    per_symbol_account_query = BucketConfig(rate_per_sec=sa_rps, burst=sa_burst)
    per_symbol_critical = BucketConfig(
        rate_per_sec=float(getattr(settings_obj, "bybit_private_per_symbol_critical_rps", 1.0)),
        burst=float(getattr(settings_obj, "bybit_private_per_symbol_critical_burst", 2.0)),
    )
    _limiter_singleton = BybitRateLimiter(
        public=public,
        private_critical=private_critical,
        private_order_query=private_order_query,
        private_account_query=private_account_query,
        per_symbol_order_query=per_symbol_order_query,
        per_symbol_account_query=per_symbol_account_query,
        per_symbol_critical=per_symbol_critical,
        max_wait_ms=int(getattr(settings_obj, "bybit_rate_limit_max_wait_ms", 5_000)),
        low_status_threshold=int(getattr(settings_obj, "bybit_rate_limit_low_status_threshold", 2)),
    )
    return _limiter_singleton
