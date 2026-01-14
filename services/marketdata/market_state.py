# -*- coding: utf-8 -*-
"""Stage 11: market state marker (non-trading).

Adds:
- HIGH_VOL based on ATR/close (Wilder ATR)
- NEWS_WINDOW based on configurable UTC time windows

Emits risk_event type MARKET_STATE (already supported schema).
Must not affect strategy logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class MarketState:
    states: List[str]
    atr: Optional[float]
    atr_pct: Optional[float]
    range_pct: Optional[float]


def _parse_news_window_utc(spec: str) -> List[Tuple[int, int]]:
    """Parse 'HH:MM-HH:MM,HH:MM-HH:MM' into list of minute ranges [start,end)."""
    out: List[Tuple[int, int]] = []
    if not spec:
        return out
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" not in part:
            continue
        a, b = [x.strip() for x in part.split("-", 1)]
        try:
            ah, am = [int(x) for x in a.split(":", 1)]
            bh, bm = [int(x) for x in b.split(":", 1)]
            start = ah * 60 + am
            end = bh * 60 + bm
            out.append((start, end))
        except Exception:
            continue
    return out


def _utc_minute_of_day(ts_ms: int) -> int:
    # Convert epoch ms to UTC minute-of-day without importing heavy tz libs.
    import datetime
    dt = datetime.datetime.utcfromtimestamp(int(ts_ms) / 1000.0)
    return dt.hour * 60 + dt.minute


class MarketStateTracker:
    def __init__(
        self,
        *,
        atr_period: int = 14,
        high_vol_pct: float = 0.04,
        news_window_utc: str = "",
        emit_on_normal: bool = False,
    ) -> None:
        self.atr_period = max(2, int(atr_period))
        self.high_vol_pct = float(high_vol_pct)
        self.emit_on_normal = bool(emit_on_normal)
        self._last_state: Dict[Tuple[str, str], List[str]] = {}
        self._prev_close: Dict[Tuple[str, str], float] = {}
        self._atr: Dict[Tuple[str, str], float] = {}
        self._atr_init_count: Dict[Tuple[str, str], int] = {}
        self._atr_sum_tr: Dict[Tuple[str, str], float] = {}
        self._news_ranges = _parse_news_window_utc(news_window_utc)

    def classify_states(
        self,
        *,
        symbol: str,
        timeframe: str,
        close_time_ms: int,
        high: float,
        low: float,
        close: float,
    ) -> MarketState:
        key = (symbol, timeframe)
        range_pct = (high - low) / close if close else None

        # ATR
        prev_close = self._prev_close.get(key)
        tr = None
        if prev_close is None:
            tr = float(high - low)
        else:
            tr = float(max(high - low, abs(high - prev_close), abs(low - prev_close)))

        # Wilder ATR init
        if key not in self._atr:
            self._atr_sum_tr[key] = self._atr_sum_tr.get(key, 0.0) + tr
            self._atr_init_count[key] = self._atr_init_count.get(key, 0) + 1
            if self._atr_init_count[key] >= self.atr_period:
                self._atr[key] = self._atr_sum_tr[key] / float(self.atr_period)
        else:
            self._atr[key] = (self._atr[key] * (self.atr_period - 1) + tr) / float(self.atr_period)

        self._prev_close[key] = float(close)

        atr = self._atr.get(key)
        atr_pct = (atr / close) if (atr is not None and close) else None

        states: List[str] = []
        if atr_pct is not None and atr_pct >= self.high_vol_pct:
            states.append("HIGH_VOL")
        else:
            states.append("NORMAL")

        # NEWS_WINDOW
        if self._news_ranges:
            m = _utc_minute_of_day(close_time_ms)
            for start, end in self._news_ranges:
                if start <= end:
                    if start <= m < end:
                        states.append("NEWS_WINDOW")
                        break
                else:
                    # Cross-midnight window
                    if m >= start or m < end:
                        states.append("NEWS_WINDOW")
                        break

        return MarketState(states=states, atr=atr, atr_pct=atr_pct, range_pct=range_pct)

    def should_emit(self, *, symbol: str, timeframe: str, states: List[str]) -> bool:
        key = (symbol, timeframe)
        last = self._last_state.get(key)
        self._last_state[key] = list(states)
        # Emit on first non-normal or if configured
        if last is None:
            return ("NORMAL" not in states) or self.emit_on_normal
        if states != last:
            return ("NORMAL" not in states) or self.emit_on_normal
        return False
