"""
8h K 线派生器（Phase 1）

背景：Bybit 官方 Kline interval 列表不包含 480 分钟（8h）。
但系统要求监控 8h，因此我们从 1h candle 聚合生成 8h candle。

聚合规则（标准 OHLCV）：
- open: 8h 窗口内第一根 1h 的 open
- high: 8h 窗口内最高 high
- low: 8h 窗口内最低 low
- close: 8h 窗口内最后一根 1h 的 close
- volume/turnover: 求和

对齐规则：
- 以 epoch 毫秒对齐：window_start = floor(start_ms / (8h)) * (8h)
- window_end = window_start + 8h - 1ms
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


EIGHT_H_MS = 8 * 60 * 60 * 1000


@dataclass
class AggState:
    window_start_ms: int
    window_end_ms: int
    bars: List[dict]


class Derived8hAggregator:
    def __init__(self):
        self._state: Dict[str, AggState] = {}

    @staticmethod
    def _window_for_start(start_ms: int) -> Tuple[int, int]:
        ws = (start_ms // EIGHT_H_MS) * EIGHT_H_MS
        we = ws + EIGHT_H_MS - 1
        return ws, we

    def push_1h_bar(self, symbol: str, bar: dict) -> Tuple[Optional[dict], Optional[str]]:
        """
        输入一根已收盘的 1h bar。

        返回：
        - agg_bar: 若形成完整 8h bar 则返回该 8h bar，否则 None
        - warning: 若检测到缺口/错位，返回 warning 文本（用于日志/后续 risk_event）
        """
        start_ms = int(bar["start_ms"])
        end_ms = int(bar["end_ms"])

        ws, we = self._window_for_start(start_ms)

        st = self._state.get(symbol)
        warning = None

        if st is None or st.window_end_ms != we:
            if st is not None and len(st.bars) != 8:
                warning = f"8h_window_incomplete prev_start={st.window_start_ms} got_bars={len(st.bars)}"
            st = AggState(window_start_ms=ws, window_end_ms=we, bars=[])
            self._state[symbol] = st

        # 去重：按 start_ms
        if any(b["start_ms"] == start_ms for b in st.bars):
            return None, None

        st.bars.append(bar)
        st.bars.sort(key=lambda x: x["start_ms"])

        # 完成条件：最后一根 1h bar 的 end_ms == window_end，并且数量 == 8
        if end_ms == st.window_end_ms and len(st.bars) == 8:
            b0 = st.bars[0]
            bN = st.bars[-1]
            agg = {
                "start_ms": st.window_start_ms,
                "end_ms": st.window_end_ms,
                "open": float(b0["open"]),
                "high": max(float(b["high"]) for b in st.bars),
                "low": min(float(b["low"]) for b in st.bars),
                "close": float(bN["close"]),
                "volume": sum(float(b["volume"]) for b in st.bars),
                "turnover": sum(float(b["turnover"]) for b in st.bars if b.get("turnover") is not None) or None,
                "source": "derived_8h",
            }
            self._state.pop(symbol, None)
            return agg, warning

        return None, warning
