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
from libs.bybit.errors import BybitError, is_retryable_error, is_rate_limit_error, extract_retry_after_ms
from libs.bybit.ratelimit import EndpointGroup, get_rate_limiter
from libs.common.config import settings


def _lower_headers(headers_obj) -> Dict[str, str]:
    try:
        return {k.lower(): v for k, v in dict(headers_obj).items()}
    except Exception:
        return {}


def _header_int(headers: Dict[str, str], key: str) -> Optional[int]:
    try:
        v = headers.get(key.lower()) or headers.get(key)
        if v is None:
            return None
        return int(float(v))
    except Exception:
        return None


def _header_reset_ts_ms(headers: Dict[str, str]) -> Optional[int]:
    # Bybit uses epoch ms in X-Bapi-Limit-Reset-Timestamp
    n = _header_int(headers, "x-bapi-limit-reset-timestamp")
    if n is None:
        n = _header_int(headers, "X-Bapi-Limit-Reset-Timestamp")
    if n is None:
        return None
    if n < 10_000_000_000:
        n *= 1000
    return n


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
        # Stage 4: in-process rate limiter and TTL caches for private query endpoints
        self._limiter = get_rate_limiter(settings)
        self._cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    def _cache_get(self, key: str, ttl_sec: float) -> Optional[Dict[str, Any]]:
        try:
            ts, val = self._cache.get(key, (0.0, {}))
            if not val:
                return None
            if (time.time() - float(ts)) <= float(ttl_sec):
                return val
            return None
        except Exception:
            return None

    def _cache_get_stale(self, key: str) -> Optional[Tuple[float, Dict[str, Any]]]:
        try:
            ts, val = self._cache.get(key, (0.0, {}))
            if not val:
                return None
            return (float(ts), val)
        except Exception:
            return None

    def _cache_set(self, key: str, val: Dict[str, Any]) -> None:
        try:
            self._cache[key] = (time.time(), val)
        except Exception:
            pass

    def _endpoint_group(self, path: str) -> EndpointGroup:
        # Critical private endpoints: create/amend/cancel orders, trading-stop.
        critical_prefixes = (
            "/v5/order/create",
            "/v5/order/amend",
            "/v5/order/cancel",
            "/v5/order/cancel-all",
            "/v5/position/trading-stop",
        )
        if any(path.startswith(p) for p in critical_prefixes):
            return EndpointGroup.PRIVATE_CRITICAL
        # Stage 5: split private queries
        order_query_prefixes = (
            "/v5/order/realtime",
            "/v5/order/history",
            "/v5/order/execution",
            "/v5/execution/list",
        )
        if any(path.startswith(p) for p in order_query_prefixes):
            return EndpointGroup.PRIVATE_ORDER_QUERY

        account_query_prefixes = (
            "/v5/account/wallet-balance",
            "/v5/position/list",
            "/v5/account/",
            "/v5/position/",
        )
        if any(path.startswith(p) for p in account_query_prefixes):
            return EndpointGroup.PRIVATE_ACCOUNT_QUERY

        # safe default
        return EndpointGroup.PRIVATE_ACCOUNT_QUERY

    @staticmethod
    def _extract_symbol(params: Dict[str, Any], body: Dict[str, Any]) -> str:
        for d in (body, params):
            sym = d.get("symbol") or d.get("Symbol")
            if isinstance(sym, str) and sym:
                return sym
        return ""

    def _apply_rate_limit_headers(self, *, group: EndpointGroup, symbol: str, headers: Dict[str, str]) -> None:
        """Adaptive limiter updates from Bybit headers (Stage 5)."""
        try:
            self._limiter.update_from_headers(group=group, symbol=symbol, headers=headers)
        except Exception:
            pass

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

        group = self._endpoint_group(path)
        symbol = self._extract_symbol(params, body)
        query = urllib.parse.urlencode(params)
        json_body = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        url = f"{self.base_url}{path}"
        if query:
            url = url + "?" + query

        data = None
        headers = {"Content-Type": "application/json"}
        if method != "GET":
            data = json_body.encode("utf-8")

        # Stage 4: public limiter
        gw, _ = self._limiter.acquire(group=EndpointGroup.PUBLIC, symbol="")
        if gw > 0:
            time.sleep(min(float(gw), float(self._limiter.max_wait_ms)) / 1000.0)

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                hdrs = _lower_headers(getattr(resp, "headers", {}))
                raw = resp.read().decode("utf-8")
                obj = json.loads(raw)
                self._apply_rate_limit_headers(group=EndpointGroup.PUBLIC, symbol="", headers=hdrs)
                if isinstance(obj, dict) and obj.get("retCode") not in (None, 0, "0"):
                    raise BybitError(
                        http_status=getattr(resp, "status", None),
                        ret_code=int(obj.get("retCode")),
                        ret_msg=str(obj.get("retMsg")),
                        raw={**obj, "_headers": hdrs, "_rl_wait_ms": {"global": gw, "symbol": 0}},
                    )
                return obj
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            try:
                obj = json.loads(raw)
                hdrs = _lower_headers(getattr(e, "headers", {}))
                self._apply_rate_limit_headers(group=EndpointGroup.PUBLIC, symbol="", headers=hdrs)
                raise BybitError(
                    http_status=e.code,
                    ret_code=int(obj.get("retCode")) if "retCode" in obj else None,
                    ret_msg=str(obj.get("retMsg")) if "retMsg" in obj else raw,
                    raw={**obj, "_headers": hdrs, "_rl_wait_ms": {"global": gw, "symbol": 0}},
                )
            except Exception:
                raise BybitError(http_status=e.code, ret_code=None, ret_msg=raw, raw={"_headers": _lower_headers(getattr(e, "headers", {})), "_rl_wait_ms": {"global": gw, "symbol": 0}})


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

        # 定义 group 和 symbol（在内部函数 _once 中使用）
        group = self._endpoint_group(path)
        symbol = self._extract_symbol(params, body)

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

            # Stage 4: limiter acquire
            gw, sw = self._limiter.acquire(group=group, symbol=symbol)
            wait_ms = max(gw, sw)
            if wait_ms > 0:
                time.sleep(min(float(wait_ms), float(self._limiter.max_wait_ms)) / 1000.0)

            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    hdrs = _lower_headers(getattr(resp, "headers", {}))
                    raw = resp.read().decode("utf-8")
                    obj = json.loads(raw)
                    self._apply_rate_limit_headers(group=group, symbol=symbol, headers=hdrs)
                    if isinstance(obj, dict) and obj.get("retCode") not in (None, 0, "0"):
                        raise BybitError(
                            http_status=getattr(resp, "status", None),
                            ret_code=int(obj.get("retCode")),
                            ret_msg=str(obj.get("retMsg")),
                            raw={**obj, "_headers": hdrs, "_rl_wait_ms": {"global": gw, "symbol": sw}, "_path": path, "_symbol": symbol},
                        )
                    return obj
            except urllib.error.HTTPError as e:
                raw = e.read().decode("utf-8", errors="replace")
                try:
                    obj = json.loads(raw)
                    hdrs = _lower_headers(getattr(e, "headers", {}))
                    self._apply_rate_limit_headers(group=group, symbol=symbol, headers=hdrs)
                    raise BybitError(
                        http_status=e.code,
                        ret_code=int(obj.get("retCode")) if "retCode" in obj else None,
                        ret_msg=str(obj.get("retMsg")) if "retMsg" in obj else raw,
                        raw={**obj, "_headers": hdrs, "_rl_wait_ms": {"global": gw, "symbol": sw}, "_path": path, "_symbol": symbol},
                    )
                except Exception:
                    hdrs = _lower_headers(getattr(e, "headers", {}))
                    self._apply_rate_limit_headers(group=group, symbol=symbol, headers=hdrs)
                    raise BybitError(http_status=e.code, ret_code=None, ret_msg=raw, raw={"_headers": hdrs, "_rl_wait_ms": {"global": gw, "symbol": sw}, "_path": path, "_symbol": symbol})

        # Custom retry loop so we can respect Bybit's rate-limit reset (retCode=10006) when present.
        attempts = 0
        last: Exception | None = None
        while attempts < 3:
            attempts += 1
            try:
                return _once()
            except Exception as e:
                last = e
                if attempts >= 3 or not is_retryable_error(e):
                    raise
                # rate limit: try to sleep until reset (best-effort)
                if is_rate_limit_error(e):
                    ms = extract_retry_after_ms(e, default_ms=1500) or 1500
                    time.sleep(float(ms) / 1000.0)
                else:
                    # fallback exponential backoff
                    time.sleep(min(5.0, 0.5 * (2 ** (attempts - 1))))
        assert last is not None
        raise last

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

    def position_list(self, *, category: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"category": category}
        if symbol:
            params["symbol"] = symbol
        return self._request_private("GET", "/v5/position/list", params=params)

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

    # -------------------- Stage 4: cached private query endpoints --------------------
    def wallet_balance_cached(self, *, account_type: str, coin: Optional[str] = None) -> Dict[str, Any]:
        ttl = float(getattr(settings, "bybit_wallet_balance_cache_ttl_sec", 1.0))
        key = f"wallet_balance:{account_type}:{coin or ''}"
        hit = self._cache_get(key, ttl)
        if hit is not None:
            return hit

        # degrade: if predicted wait is too long, return stale if available
        wait = self._limiter.estimate_wait_ms(group=EndpointGroup.PRIVATE_ACCOUNT_QUERY, symbol="")
        if wait > int(getattr(settings, "bybit_rate_limit_max_wait_ms", 5000)):
            stale = self._cache_get_stale(key)
            if stale is not None:
                ts, val = stale
                return {**val, "_degraded": True, "_stale_ms": int((time.time() - ts) * 1000), "_predicted_wait_ms": int(wait)}

        val = self.wallet_balance(account_type=account_type, coin=coin)
        self._cache_set(key, val)
        return val

    def position_list_cached(self, *, category: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        ttl = float(getattr(settings, "bybit_position_cache_ttl_sec", 1.0))
        sym = symbol or ""
        key = f"position_list:{category}:{sym}"
        hit = self._cache_get(key, ttl)
        if hit is not None:
            return hit

        wait = self._limiter.estimate_wait_ms(group=EndpointGroup.PRIVATE_ACCOUNT_QUERY, symbol=sym)
        if wait > int(getattr(settings, "bybit_rate_limit_max_wait_ms", 5000)):
            stale = self._cache_get_stale(key)
            if stale is not None:
                ts, val = stale
                return {**val, "_degraded": True, "_stale_ms": int((time.time() - ts) * 1000), "_predicted_wait_ms": int(wait)}

        val = self.position_list(category=category, symbol=symbol)
        self._cache_set(key, val)
        return val

    def open_orders_cached(self, *, category: str, symbol: str, open_only: int = 0) -> Dict[str, Any]:
        ttl = float(getattr(settings, "bybit_open_orders_cache_ttl_sec", 0.5))
        key = f"open_orders:{category}:{symbol}:{open_only}"
        hit = self._cache_get(key, ttl)
        if hit is not None:
            return hit

        wait = self._limiter.estimate_wait_ms(group=EndpointGroup.PRIVATE_ORDER_QUERY, symbol=symbol)
        if wait > int(getattr(settings, "bybit_rate_limit_max_wait_ms", 5000)):
            stale = self._cache_get_stale(key)
            if stale is not None:
                ts, val = stale
                return {**val, "_degraded": True, "_stale_ms": int((time.time() - ts) * 1000), "_predicted_wait_ms": int(wait)}

        val = self.open_orders(category=category, symbol=symbol, open_only=open_only)
        self._cache_set(key, val)
        return val


# 兼容别名（如果其它地方用老名字）
BybitV5Client = TradeRestV5Client