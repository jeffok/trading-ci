# -*- coding: utf-8 -*-
"""Bybit V5 REST 客户端（最小可用）

目标：支撑 execution-service 的 Phase 3/4 所需功能：
- 获取钱包余额（用于风险仓位计算）
- 获取合约精度（qtyStep/minOrderQty/tickSize）
- 下单/撤单
- 查询订单实时状态
- 查询持仓
- 设置止损（trading-stop）

说明：
- 为控制依赖，这里使用标准库 `urllib`；你也可以很容易替换成 httpx/requests。
- 所有方法都返回 dict（原样 JSON），调用方自行解析。
- 错误处理：遇到非 2xx 会抛出 RuntimeError，并包含 response body 便于排障。
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

from libs.bybit.auth_v5 import sign_hmac_sha256, build_auth_headers
from libs.bybit.errors import BybitError, is_retryable_error
from libs.common.retry import retry_call
from libs.common.config import settings


class TradeRestV5Client:
    """Bybit V5 REST 客户端（execution-service 依赖的对外接口）

    说明：
    - execution-service 代码里按 `TradeRestV5Client(base_url=...)` 方式构造（不显式传 key/secret）。
    - 因此这里默认从 `settings.bybit_api_key/bybit_api_secret` 读取。
    - 对于 public endpoints（如 instruments_info）允许无 key/secret。
    - 对于 private endpoints（下单/余额/仓位/止损等）若缺少 key/secret 会抛出清晰错误。
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        recv_window_ms: int = 5000,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = (api_key or getattr(settings, "bybit_api_key", "") or "").strip()
        self.api_secret = (api_secret or getattr(settings, "bybit_api_secret", "") or "").strip()
        self.recv_window_ms = int(recv_window_ms)

    def _require_auth(self, endpoint: str) -> None:
        if not self.api_key or not self.api_secret:
            raise RuntimeError(
                f"Missing BYBIT credentials for private endpoint {endpoint}. "
                f"Set BYBIT_API_KEY and BYBIT_API_SECRET in .env (or pass api_key/api_secret explicitly)."
            )

    def _ts_ms(self) -> str:
        return str(int(time.time() * 1000))

    def _request_public(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Public endpoint（无需签名）"""
        method = method.upper()
        params = params or {}
        body = body or {}

        query = urllib.parse.urlencode(params)
        json_body = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        url = f"{self.base_url}{path}"
        if query:
            url = url + "?" + query

        data = None
        headers = {"Content-Type": "application/json"}
        if method != "GET":
            data = json_body.encode("utf-8")

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read().decode("utf-8")
                obj = json.loads(raw)
                if isinstance(obj, dict) and obj.get("retCode") not in (None, 0, "0"):
                    raise BybitError(
                        http_status=getattr(resp, "status", None),
                        ret_code=int(obj.get("retCode")),
                        ret_msg=str(obj.get("retMsg")),
                        raw=obj,
                    )
                return obj
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            try:
                obj = json.loads(raw)
                raise BybitError(
                    http_status=e.code,
                    ret_code=int(obj.get("retCode")) if "retCode" in obj else None,
                    ret_msg=str(obj.get("retMsg")) if "retMsg" in obj else raw,
                    raw=obj,
                )
            except Exception:
                raise BybitError(http_status=e.code, ret_code=None, ret_msg=raw, raw={})


    def _request_private(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Private endpoint（签名+重试）"""
        self._require_auth(path)
        method = method.upper()
        params = params or {}
        body = body or {}

        def _once() -> Dict[str, Any]:
            query = urllib.parse.urlencode(params)
            json_body = json.dumps(body, separators=(",", ":"), ensure_ascii=False)

            ts = self._ts_ms()
            recv = str(self.recv_window_ms)

            if method == "GET":
                prehash = ts + self.api_key + recv + query
            else:
                prehash = ts + self.api_key + recv + json_body

            sig = sign_hmac_sha256(self.api_secret, prehash)
            headers = build_auth_headers(api_key=self.api_key, api_secret=self.api_secret, timestamp_ms=ts, recv_window=recv, signature=sig)

            url = f"{self.base_url}{path}"
            if query:
                url = url + "?" + query

            data = None
            if method != "GET":
                data = json_body.encode("utf-8")

            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    raw = resp.read().decode("utf-8")
                    obj = json.loads(raw)
                    if isinstance(obj, dict) and obj.get("retCode") not in (None, 0, "0"):
                        raise BybitError(http_status=getattr(resp, "status", None), ret_code=int(obj.get("retCode")), ret_msg=str(obj.get("retMsg")), raw=obj)
                    return obj
            except urllib.error.HTTPError as e:
                raw = e.read().decode("utf-8", errors="replace")
                try:
                    obj = json.loads(raw)
                    raise BybitError(http_status=e.code, ret_code=int(obj.get("retCode")) if "retCode" in obj else None, ret_msg=str(obj.get("retMsg")) if "retMsg" in obj else raw, raw=obj)
                except Exception:
                    raise BybitError(http_status=e.code, ret_code=None, ret_msg=raw, raw={})

        return retry_call(_once, retry_if=is_retryable_error, max_attempts=3, base_delay_sec=0.5, max_delay_sec=5.0)

    # -------------------- Public endpoints --------------------
    def instruments_info(self, *, category: str, symbol: str) -> Dict[str, Any]:
        # public endpoint
        return self._request_public("GET", "/v5/market/instruments-info", params={"category": category, "symbol": symbol})

    # -------------------- Private endpoints --------------------
    def wallet_balance(self, *, account_type: str, coin: Optional[str] = None) -> Dict[str, Any]:
        params = {"accountType": account_type}
        if coin:
            params["coin"] = coin
        return self._request_private("GET", "/v5/account/wallet-balance", params=params)

    def place_order(self, *, category: str, symbol: str, side: str, order_type: str, qty: str,
                    price: Optional[str] = None, time_in_force: str = "GTC", reduce_only: bool = False,
                    position_idx: int = 0, order_link_id: Optional[str] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "category": category,
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "qty": qty,
            "timeInForce": time_in_force,
            "reduceOnly": reduce_only,
            "positionIdx": position_idx,
        }
        if price is not None:
            body["price"] = price
        if order_link_id:
            body["orderLinkId"] = order_link_id
        return self._request_private("POST", "/v5/order/create", body=body)

    def cancel_order(self, *, category: str, symbol: str, order_id: Optional[str] = None, order_link_id: Optional[str] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"category": category, "symbol": symbol}
        if order_id:
            body["orderId"] = order_id
        if order_link_id:
            body["orderLinkId"] = order_link_id
        return self._request_private("POST", "/v5/order/cancel", body=body)

    def open_orders(self, *, category: str, symbol: str, open_only: int = 0) -> Dict[str, Any]:
        # openOnly: 0=all, 1=open, 2=closed (近 500 条)
        return self._request_private("GET", "/v5/order/realtime", params={"category": category, "symbol": symbol, "openOnly": open_only})

    def position_list(self, *, category: str, symbol: str) -> Dict[str, Any]:
        return self._request_private("GET", "/v5/position/list", params={"category": category, "symbol": symbol})

    def set_trading_stop(self, *, category: str, symbol: str, position_idx: int = 0,
                         stop_loss: Optional[str] = None, trailing_stop: Optional[str] = None,
                         tpsl_mode: str = "Full") -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "category": category,
            "symbol": symbol,
            "positionIdx": position_idx,
            "tpslMode": tpsl_mode,
        }
        if stop_loss is not None:
            body["stopLoss"] = stop_loss
        if trailing_stop is not None:
            body["trailingStop"] = trailing_stop
        return self._request_private("POST", "/v5/position/trading-stop", body=body)


# 兼容别名（如果其它地方用老名字）
BybitV5Client = TradeRestV5Client