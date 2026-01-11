# -*- coding: utf-8 -*-
"""指标计算（Phase 2）

为控制代码量与可读性，本模块采用纯 Python 实现：
- EMA
- MACD（12/26/9）以及 histogram
- RSI（14）
- OBV

注意：
- 这里的实现强调“可读 + 可复现 + 注释充分”，性能不是首要目标。
- 后续如果需要性能，可替换为 numpy/pandas，但要保持输出口径一致。
"""

from __future__ import annotations
from typing import List, Optional


def ema(values: List[float], period: int) -> List[Optional[float]]:
    """
    计算 EMA（指数移动平均）

    返回列表长度与 values 相同：
    - 前 (period-1) 个位置为 None（数据不足）
    - 从第 period 个起输出 EMA 值

    公式：
    EMA_t = alpha * price_t + (1 - alpha) * EMA_{t-1}
    alpha = 2 / (period + 1)
    """
    if period <= 0:
        raise ValueError("period must be positive")

    out: List[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return out

    alpha = 2.0 / (period + 1.0)

    # 初始 EMA：用前 period 个的简单均值作为种子
    seed = sum(values[:period]) / float(period)
    out[period - 1] = seed
    prev = seed

    for i in range(period, len(values)):
        prev = alpha * values[i] + (1 - alpha) * prev
        out[i] = prev
    return out


def macd(close: List[float], fast: int = 12, slow: int = 26, signal: int = 9):
    """
    计算 MACD：
    - macd_line = EMA(fast) - EMA(slow)
    - signal_line = EMA(macd_line, signal)
    - histogram = macd_line - signal_line

    返回：(macd_line, signal_line, histogram)
    每个列表长度与 close 相同，数据不足处为 None。
    """
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)

    macd_line: List[Optional[float]] = [None] * len(close)
    for i in range(len(close)):
        if ema_fast[i] is None or ema_slow[i] is None:
            macd_line[i] = None
        else:
            macd_line[i] = float(ema_fast[i] - ema_slow[i])

    # signal 对 macd_line 的 None 做处理：只有非 None 才参与计算
    # 为保持索引对齐：我们构造一个“填充序列”，但只在足够点后输出。
    macd_vals = [x if x is not None else 0.0 for x in macd_line]
    signal_line_raw = ema(macd_vals, signal)

    signal_line: List[Optional[float]] = [None] * len(close)
    histogram: List[Optional[float]] = [None] * len(close)

    for i in range(len(close)):
        if macd_line[i] is None or signal_line_raw[i] is None:
            signal_line[i] = None
            histogram[i] = None
        else:
            signal_line[i] = float(signal_line_raw[i])
            histogram[i] = float(macd_line[i] - signal_line[i])

    return macd_line, signal_line, histogram


def rsi(close: List[float], period: int = 14) -> List[Optional[float]]:
    """
    RSI（相对强弱指标）

    采用经典 Wilder 平滑方法：
    - gain = max(diff, 0)
    - loss = max(-diff, 0)
    - avg_gain/avg_loss 采用递推平滑
    - RSI = 100 - (100 / (1 + RS))

    返回长度与 close 一致；不足 period 时为 None。
    """
    if len(close) < period + 1:
        return [None] * len(close)

    out: List[Optional[float]] = [None] * len(close)

    gains = []
    losses = []
    for i in range(1, period + 1):
        diff = close[i] - close[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    def _rsi(ag: float, al: float) -> float:
        if al == 0:
            return 100.0
        rs = ag / al
        return 100.0 - (100.0 / (1.0 + rs))

    out[period] = _rsi(avg_gain, avg_loss)

    # Wilder smoothing
    for i in range(period + 1, len(close)):
        diff = close[i] - close[i - 1]
        gain = max(diff, 0.0)
        loss = max(-diff, 0.0)

        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[i] = _rsi(avg_gain, avg_loss)

    return out


def obv(close: List[float], volume: List[float]) -> List[float]:
    """
    OBV（On-Balance Volume）

    规则：
    - 若 close 上涨：OBV += volume
    - 若 close 下跌：OBV -= volume
    - 若 close 不变：OBV 不变

    返回长度与 close 一致（首个为 0）。
    """
    if len(close) != len(volume):
        raise ValueError("close and volume length mismatch")

    out: List[float] = [0.0] * len(close)
    for i in range(1, len(close)):
        if close[i] > close[i - 1]:
            out[i] = out[i - 1] + volume[i]
        elif close[i] < close[i - 1]:
            out[i] = out[i - 1] - volume[i]
        else:
            out[i] = out[i - 1]
    return out
