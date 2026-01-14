# -*- coding: utf-8 -*-
"""Telegram message templates.

⚠️ Important: templates MUST NOT change any strategy logic.

This module renders:
- execution_report (stream:execution_report)
- risk_event (stream:risk_event)

Stage 2 goals:
- Human friendly open/close messages
- Close message includes PnL (USDT) and consecutive_loss_count
- Rate-limit (10006/429) alerts are explicit and actionable
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


def _safe(v: Any) -> str:
    if v is None:
        return ""
    return str(v)


def _num(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _fmt(v: Any, nd: int = 4) -> str:
    x = _num(v)
    if x is None:
        return ""
    return f"{x:.{nd}f}"


def _direction_from_detail(detail: Dict[str, Any], ext: Dict[str, Any]) -> str:
    # Prefer bias when present
    bias = _safe(detail.get("bias") or ext.get("bias")).upper()
    if bias in ("LONG", "BULL", "UP"):
        return "多"
    if bias in ("SHORT", "BEAR", "DOWN"):
        return "空"

    side = _safe(detail.get("side") or ext.get("side")).upper()
    if side == "BUY":
        return "多"
    if side == "SELL":
        return "空"
    return ""


def severity_from_execution_status(status: str) -> str:
    """Map execution status to notifier severity."""
    s = (status or "").strip().upper()
    if s in ("ORDER_REJECTED", "PRIMARY_SL_HIT", "SECONDARY_SL_EXIT"):
        return "IMPORTANT"
    if s in ("TP_HIT", "FILLED", "POSITION_CLOSED", "RUNNER_SL_UPDATED"):
        return "IMPORTANT"
    if s == "ORDER_SUBMITTED":
        return "INFO"
    return "IMPORTANT"


def _render_position_closed(*, symbol: str, direction: str, payload: Dict[str, Any], detail: Dict[str, Any], ext: Dict[str, Any]) -> str:
    qty = payload.get("filled_qty") or detail.get("filled_qty") or detail.get("qty")
    entry_avg = ext.get("entry_avg_price") or detail.get("entry_avg_price") or detail.get("entry_price") or detail.get("entry")
    exit_avg = ext.get("exit_avg_price") or detail.get("exit_avg_price") or payload.get("avg_price") or detail.get("close_price")
    pnl_usdt = ext.get("pnl_usdt") or detail.get("pnl_usdt")
    loss_cnt = ext.get("consecutive_loss_count") or detail.get("consecutive_loss_count")

    pnl = _num(pnl_usdt)
    if pnl is None:
        pnl_line = ""
    else:
        if pnl > 0:
            pnl_line = f"🟢 本次盈利：{_fmt(pnl, 4)} USDT"
        elif pnl < 0:
            pnl_line = f"🔴 本次亏损：{_fmt(abs(pnl), 4)} USDT"
        else:
            pnl_line = "🟡 本次盈亏：0.0000 USDT"

    lines = [
        f"📘 平仓成交：{symbol} {direction}".strip(),
        f"数量：{_fmt(qty, 4)}".rstrip("："),
        f"开仓均价：{_fmt(entry_avg, 4)}".rstrip("："),
        f"平仓均价：{_fmt(exit_avg, 4)}".rstrip("："),
    ]
    if pnl_line:
        lines.append(pnl_line)
    if loss_cnt is not None and _safe(loss_cnt) != "":
        try:
            lines.append(f"当前连续亏损次数：{int(loss_cnt)}")
        except Exception:
            lines.append(f"当前连续亏损次数：{_safe(loss_cnt)}")

    reason = _safe(payload.get("reason") or detail.get("reason"))
    if reason and reason not in ("POSITION_CLOSED", "EXITED"):
        lines.append(f"原因：{reason}")

    return "\n".join([x for x in lines if x])


def render_execution_report(evt: Dict[str, Any]) -> Tuple[str, str]:
    """Return (severity, text)."""
    payload = evt.get("payload", {}) or {}
    plan_id = _safe(payload.get("plan_id"))
    status = _safe(payload.get("status"))
    symbol = _safe(payload.get("symbol"))
    timeframe = _safe(payload.get("timeframe"))

    ext = payload.get("ext", {}) or {}
    detail = (ext.get("detail") or {}) if isinstance(ext.get("detail"), dict) else {}
    direction = _direction_from_detail(detail, ext)

    sev = severity_from_execution_status(status)

    s = (status or "").upper()
    if s == "POSITION_CLOSED":
        text = _render_position_closed(symbol=symbol, direction=direction, payload=payload, detail=detail, ext=ext)
    elif s in ("PRIMARY_SL_HIT", "SECONDARY_SL_EXIT"):
        title = "🛑 止损成交" if s == "PRIMARY_SL_HIT" else "🟠 二级止损/规则退出"
        # Reuse close layout (it includes PnL if provided)
        text = _render_position_closed(symbol=symbol, direction=direction, payload=payload, detail=detail, ext=ext)
        text = text.replace("📘 平仓成交", title, 1)
    elif s == "TP_HIT":
        title = "🎯 止盈成交"
        text = _render_position_closed(symbol=symbol, direction=direction, payload=payload, detail=detail, ext=ext)
        text = text.replace("📘 平仓成交", title, 1)
    elif s == "FILLED":
        qty = payload.get("filled_qty") or detail.get("qty")
        avg = payload.get("avg_price") or detail.get("avg_price") or detail.get("price")
        lines = [
            f"📗 开仓成交：{symbol} {direction}".strip(),
            f"数量：{_fmt(qty, 4)}".rstrip("："),
            f"开仓均价：{_fmt(avg, 4)}".rstrip("："),
        ]
        if timeframe:
            lines.append(f"周期：{timeframe}")
        text = "\n".join([x for x in lines if x])
    elif s == "ORDER_SUBMITTED":
        qty = payload.get("filled_qty") or detail.get("qty")
        price = payload.get("avg_price") or detail.get("price")
        order_id = _safe(payload.get("order_id") or detail.get("order_id"))
        lines = [
            f"🧾 订单已提交：{symbol} {direction}".strip(),
        ]
        if qty is not None:
            lines.append(f"数量：{_fmt(qty, 4)}")
        if price is not None:
            lines.append(f"价格：{_fmt(price, 4)}")
        if order_id:
            lines.append(f"order_id：{order_id}")
        text = "\n".join([x for x in lines if x])
    elif s == "RUNNER_SL_UPDATED":
        new_sl = detail.get("new_sl") or detail.get("sl") or ext.get("runner_stop")
        lines = [
            f"🟡 Runner 止损更新：{symbol} {direction}".strip(),
        ]
        if new_sl is not None:
            lines.append(f"新止损：{_fmt(new_sl, 4)}")
        text = "\n".join([x for x in lines if x])
    else:
        # ORDER_REJECTED or unknown
        reason = _safe(payload.get("reason") or detail.get("error") or detail.get("reason"))
        lines = [
            f"❌ 执行异常：{symbol} {direction}".strip(),
            f"status：{status}",
        ]
        if reason:
            # 防止 reason 中包含未转义的格式化字符串（如 {group}）
            # 使用双大括号转义，或者直接替换
            safe_reason = str(reason).replace("{", "{{").replace("}", "}}")
            lines.append(f"原因：{safe_reason}")
        text = "\n".join([x for x in lines if x])

    # Add traceability footer (kept short)
    if plan_id:
        text = text + f"\n#plan_id {plan_id}"
    return sev, text


def render_risk_event(evt: Dict[str, Any]) -> Tuple[str, str]:
    payload = evt.get("payload", {}) or {}
    typ = _safe(payload.get("type")).upper()
    sev = _safe(payload.get("severity")) or "INFO"
    symbol = _safe(payload.get("symbol"))
    retry_after_ms = payload.get("retry_after_ms")
    detail = payload.get("detail", {}) or {}

    if typ == "RATE_LIMIT":
        endpoint = _safe(detail.get("endpoint"))
        rc = detail.get("ret_code")
        rm = _safe(detail.get("ret_msg"))
        hint = _safe(detail.get("hint"))
        lines = [
            "⏳ Bybit API 限频触发" + (f"：{symbol}" if symbol else ""),
            f"retCode：{_safe(rc) or '429/10006'}",
        ]
        if rm:
            lines.append(f"retMsg：{rm}")
        if endpoint:
            lines.append(f"endpoint：{endpoint}")
        if retry_after_ms is not None:
            lines.append(f"建议等待：{int(retry_after_ms)} ms")
        if hint:
            lines.append(f"建议：{hint}")
        return sev, "\n".join([x for x in lines if x])
    if typ == "CONSISTENCY_DRIFT":
        drift_pct = detail.get("drift_pct")
        thr = detail.get("threshold_pct")
        lines = [
            "🧭 仓位一致性漂移" + (f"：{symbol}" if symbol else ""),
        ]
        if drift_pct is not None:
            try:
                lines.append(f"漂移比例：{float(drift_pct)*100:.2f}%")
            except Exception:
                lines.append(f"漂移比例：{_safe(drift_pct)}")
        if thr is not None:
            try:
                lines.append(f"阈值：{float(thr)*100:.2f}%")
            except Exception:
                lines.append(f"阈值：{_safe(thr)}")
        lq = detail.get("local_qty_total")
        wsq = detail.get("ws_size")
        if lq is not None or wsq is not None:
            lines.append(f"本地/WS：{_safe(lq)}/{_safe(wsq)}")
        ik = _safe(detail.get("idempotency_key"))
        if ik:
            lines.append(f"idempotency_key：{ik}")
        return sev, "\n".join([x for x in lines if x])

    if typ == "COOLDOWN_BLOCKED":
        tf = _safe(detail.get("timeframe"))
        until_ts_ms = detail.get("until_ts_ms")
        lines = [
            "⏸️ 冷却中" + (f"：{symbol}" if symbol else ""),
        ]
        if tf:
            lines.append(f"周期：{tf}")
        if until_ts_ms is not None:
            lines.append(f"until_ts_ms：{until_ts_ms}")
        rsn = _safe(detail.get("reason"))
        if rsn:
            lines.append(f"原因：{rsn}")
        return sev, "\n".join([x for x in lines if x])

    if typ in ("DATA_GAP", "DATA_LAG"):
        tf = _safe(detail.get("timeframe"))
        close_time_ms = detail.get("close_time_ms") or detail.get("prev_close_time_ms")
        lag_ms = detail.get("lag_ms")
        missing_bars = detail.get("missing_bars")
        lines = [
            ("🧯 行情缺口" if typ == "DATA_GAP" else "⏱️ 行情延迟") + (f"：{symbol}" if symbol else ""),
        ]
        if tf:
            lines.append(f"周期：{tf}")
        if close_time_ms is not None:
            lines.append(f"close_time_ms：{_safe(close_time_ms)}")
        if lag_ms is not None:
            lines.append(f"lag_ms：{_safe(lag_ms)}")
        if missing_bars is not None:
            lines.append(f"missing_bars：{_safe(missing_bars)}")
        return sev, "\n".join([x for x in lines if x])

    if typ == "BAR_DUPLICATE":
        tf = _safe(detail.get("timeframe"))
        diffs = detail.get("diffs") or {}
        lines = [
            "🧩 Bar 修订/重复" + (f"：{symbol}" if symbol else ""),
        ]
        if tf:
            lines.append(f"周期：{tf}")
        ct = detail.get("close_time_ms")
        if ct is not None:
            lines.append(f"close_time_ms：{_safe(ct)}")
        if diffs:
            # show up to 3 fields
            shown = []
            for k, v in list(diffs.items())[:3]:
                shown.append(f"{k}:{_safe(v.get('old'))}→{_safe(v.get('new'))}")
            lines.append("diffs：" + ", ".join(shown))
        return sev, "\n".join([x for x in lines if x])

    if typ == "PRICE_JUMP":
        tf = _safe(detail.get("timeframe"))
        jp = detail.get("jump_pct")
        thr = detail.get("threshold_pct")
        lines = [
            "📈 异常跳变" + (f"：{symbol}" if symbol else ""),
        ]
        if tf:
            lines.append(f"周期：{tf}")
        if jp is not None:
            try:
                lines.append(f"jump：{float(jp)*100:.2f}%")
            except Exception:
                lines.append(f"jump：{_safe(jp)}")
        if thr is not None:
            try:
                lines.append(f"阈值：{float(thr)*100:.2f}%")
            except Exception:
                lines.append(f"阈值：{_safe(thr)}")
        return sev, "\n".join([x for x in lines if x])

    if typ == "VOLUME_ANOMALY":
        tf = _safe(detail.get("timeframe"))
        multiple = detail.get("spike_multiple")
        lines = [
            "📊 成交量异常" + (f"：{symbol}" if symbol else ""),
        ]
        if tf:
            lines.append(f"周期：{tf}")
        if multiple is not None:
            try:
                lines.append(f"倍数：{float(multiple):.2f}x")
            except Exception:
                lines.append(f"倍数：{_safe(multiple)}")
        return sev, "\n".join([x for x in lines if x])

    if typ == "KILL_SWITCH_ON":
        reason = _safe(detail.get("reason"))
        lines = [
            "🛑 账户熔断（Kill Switch）已开启" + (f"：{symbol}" if symbol else ""),
        ]
        if reason:
            lines.append(f"原因：{reason}")
        return sev, "\n".join([x for x in lines if x])

    if typ == "MAX_POSITIONS_BLOCKED":
        cur = detail.get("current")
        mx = detail.get("max")
        lines = [
            "🚫 最大持仓限制触发" + (f"：{symbol}" if symbol else ""),
        ]
        if mx is not None or cur is not None:
            lines.append(f"当前/上限：{_safe(cur)}/{_safe(mx)}")
        return sev, "\n".join([x for x in lines if x])

    if typ == "POSITION_MUTEX_BLOCKED":
        inc_tf = _safe(detail.get("incoming_timeframe"))
        ex_tf = _safe(detail.get("existing_timeframe"))
        ex_idem = _safe(detail.get("existing_idempotency_key"))
        lines = [
            "🔒 同币种同向互斥阻断" + (f"：{symbol}" if symbol else ""),
        ]
        if inc_tf:
            lines.append(f"incoming：{inc_tf}")
        if ex_tf:
            lines.append(f"existing：{ex_tf}")
        if ex_idem:
            lines.append(f"existing_idem：{ex_idem}")
        return sev, "\n".join([x for x in lines if x])

    if typ == "SIGNAL_EXPIRED":
        expires_at_ms = detail.get("expires_at_ms")
        now_ms = detail.get("now_ms")
        lines = [
            "⌛ 信号/计划已过期" + (f"：{symbol}" if symbol else ""),
        ]
        if expires_at_ms is not None:
            lines.append(f"expires_at_ms：{expires_at_ms}")
        if now_ms is not None:
            lines.append(f"now_ms：{now_ms}")
        plan_id = _safe(detail.get("plan_id"))
        if plan_id:
            lines.append(f"plan_id：{plan_id}")
        return sev, "\n".join([x for x in lines if x])

    if typ == "ORDER_TIMEOUT":
        purpose = _safe(detail.get("purpose"))
        order_id = _safe(detail.get("order_id"))
        age_ms = detail.get("age_ms")
        lines = [
            "⏱️ 订单超时" + (f"：{symbol}" if symbol else ""),
        ]
        if purpose:
            lines.append(f"purpose：{purpose}")
        if order_id:
            lines.append(f"order_id：{order_id}")
        if age_ms is not None:
            lines.append(f"age_ms：{age_ms}")
        action = _safe(detail.get("action"))
        if action:
            lines.append(f"action：{action}")
        return sev, "\n".join([x for x in lines if x])


    if typ == "ORDER_RETRY":
        purpose = _safe(detail.get("purpose"))
        order_id = _safe(detail.get("order_id"))
        attempt = detail.get("attempt")
        new_price = detail.get("new_price")
        lines = [
            "🔁 订单重试" + (f"：{symbol}" if symbol else ""),
        ]
        if purpose:
            lines.append(f"purpose：{purpose}")
        if order_id:
            lines.append(f"order_id：{order_id}")
        if attempt is not None:
            lines.append(f"attempt：{attempt}")
        if new_price is not None:
            lines.append(f"new_price：{new_price}")
        return sev, "\n".join([x for x in lines if x])

    if typ == "ORDER_FALLBACK_MARKET":
        purpose = _safe(detail.get("purpose"))
        order_id = _safe(detail.get("order_id"))
        remain = detail.get("remaining_qty")
        lines = [
            "🟠 降级市价" + (f"：{symbol}" if symbol else ""),
        ]
        if purpose:
            lines.append(f"purpose：{purpose}")
        if order_id:
            lines.append(f"order_id：{order_id}")
        if remain is not None:
            lines.append(f"remaining_qty：{remain}")
        return sev, "\n".join([x for x in lines if x])

    if typ == "ORDER_CANCELLED":
        purpose = _safe(detail.get("purpose"))
        order_id = _safe(detail.get("order_id"))
        reason = _safe(detail.get("reason"))
        lines = [
            "✅ 订单撤销" + (f"：{symbol}" if symbol else ""),
        ]
        if purpose:
            lines.append(f"purpose：{purpose}")
        if order_id:
            lines.append(f"order_id：{order_id}")
        if reason:
            lines.append(f"reason：{reason}")
        return sev, "\n".join([x for x in lines if x])

    if typ == "ORDER_PARTIAL_FILL":
        order_id = _safe(detail.get("order_id"))
        filled = detail.get("filled_qty")
        total = detail.get("total_qty")
        lines = [
            "🧩 订单部分成交" + (f"：{symbol}" if symbol else ""),
        ]
        if order_id:
            lines.append(f"order_id：{order_id}")
        if filled is not None or total is not None:
            lines.append(f"已成/总量：{_safe(filled)}/{_safe(total)}")
        return sev, "\n".join([x for x in lines if x])

    if typ == "MARKET_STATE":
        state = _safe(detail.get("state"))
        tf = _safe(detail.get("timeframe"))
        close_time_ms = detail.get("close_time_ms")
        lines = [
            "📡 市场状态标记" + (f"：{symbol}" if symbol else ""),
        ]
        if state:
            lines.append(f"state：{state}")
        if tf:
            lines.append(f"周期：{tf}")
        if close_time_ms is not None:
            lines.append(f"close_time_ms：{close_time_ms}")
        return sev, "\n".join([x for x in lines if x])

    lines = [
        f"⚠️ 风险事件：{typ}",
        f"severity：{sev}",
    ]
    if symbol:
        lines.append(f"symbol：{symbol}")
    if retry_after_ms is not None:
        lines.append(f"retry_after_ms：{retry_after_ms}")

    # Keep detail short
    msg = _safe(detail.get("message") or detail.get("reason") or detail.get("error"))
    if msg:
        lines.append(f"detail：{msg}")

    return sev, "\n".join(lines)
