"""米游社扫码登录单步原语（passport web 变体 A，api_notes §1.3/§5）。

只提供 create/query/complete 三个 async 原语；轮询循环与提示节奏归 W3 的 bind 服务。
备用 app 变体（xiaoyao 同款，PROD salt + b/q DS + pass 头）不实现（YAGNI）——
其 query 阶段实测 -3503 风控，web 变体实测全通且无需 DS。

Confirmed 后凭据来源：``data.user_info{aid, mid}`` + 响应 ``Set-Cookie``。
域内 token 名不完全固定（v1/v2 并存），按已知名匹配，v2 优先。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx

from ..domain.errors import DemiaogeError, ErrorCode
from .ds import SALT_X4, ds_simple

WEB_BASE = "https://passport-api.miyoushe.com/account/ma-cn-passport/web"
AUTH_BASE = "https://passport-api.mihoyo.com/account/auth/api"
APP_ID = "bll8iq97cem8"
CREATE_FAIL_MESSAGE = "二维码生成失败，请稍后再试。"
NETWORK_MESSAGE = "米游社服务暂时不可用。"

# Confirmed 时按已知名匹配的 cookie（v2 优先）。
_TOKEN_NAMES = {
    "stoken": ("stoken_v2", "stoken"),
    "mid": ("mid",),
    "stuid": ("stuid", "account_id"),
    "ltoken": ("ltoken_v2", "ltoken"),
    "cookie_token": ("cookie_token_v2", "cookie_token"),
    "ltuid": ("ltuid",),
}


@dataclass
class CookieBundle:
    """一组米游社凭据；空字段在 as_cookie_header 中跳过。"""

    stuid: str = ""
    stoken: str = ""
    mid: str = ""
    ltoken: str = ""
    cookie_token: str = ""
    ltuid: str = ""

    def as_cookie_header(self) -> str:
        pairs = [f"{name}={value}" for name, value in (
            ("stuid", self.stuid),
            ("stoken", self.stoken),
            ("mid", self.mid),
            ("ltoken", self.ltoken),
            ("cookie_token", self.cookie_token),
            ("ltuid", self.ltuid),
        ) if value]
        return "; ".join(pairs)


@dataclass(frozen=True)
class QrPollResult:
    """queryQRLoginStatus 单次轮询结果；status 为固定枚举字符串。"""

    status: str  # Created / Scanned / Confirmed / Expired / Cancelled / Risk / Timeout
    user_info: dict[str, Any] = field(default_factory=dict)
    cookies: CookieBundle | None = None


def _parse_set_cookie(headers: httpx.Headers) -> dict[str, str]:
    """手动解析 Set-Cookie（同名可能重复出现，先到先得，v2 名不冲突）。"""
    parsed: dict[str, str] = {}
    for raw in headers.get_list("set-cookie"):
        first = raw.split(";", 1)[0].strip()
        if "=" not in first:
            continue
        name, _, value = first.partition("=")
        name = name.strip()
        if name and name not in parsed:
            parsed[name] = value.strip()
    return parsed


class MihoyoQrAuth:
    """扫码登录 HTTP 原语；``transport`` 供测试注入 httpx.MockTransport。"""

    def __init__(self, timeout: float = 15.0, transport: httpx.AsyncBaseTransport | None = None,
                 app_id: str = APP_ID, device_id: str | None = None) -> None:
        self._timeout = timeout
        self._transport = transport
        self._app_id = app_id
        self._device_id = device_id or str(uuid.uuid4())

    def _web_headers(self) -> dict[str, str]:
        return {
            "x-rpc-app_id": self._app_id,
            "x-rpc-device_id": self._device_id,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Demiaoge/0.4",
        }

    async def create_login(self, request_id: str) -> tuple[str, str]:
        """POST web/createQRLogin → (ticket, url)；retcode!=0 → 固定文案错误。"""
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.post(f"{WEB_BASE}/createQRLogin", json={},
                                             headers=self._web_headers())
        except httpx.HTTPError:
            raise DemiaogeError(ErrorCode.UPSTREAM_NETWORK, CREATE_FAIL_MESSAGE, request_id) from None
        try:
            result: Any = response.json()
        except ValueError:
            result = None
        data = result.get("data") if isinstance(result, dict) else None
        data = data if isinstance(data, dict) else {}
        ticket, url = str(data.get("ticket") or ""), str(data.get("url") or "")
        if not isinstance(result, dict) or result.get("retcode") != 0 or not ticket or not url:
            raise DemiaogeError(ErrorCode.UPSTREAM_NETWORK, CREATE_FAIL_MESSAGE, request_id) from None
        return ticket, url

    async def query_login(self, ticket: str, request_id: str) -> QrPollResult:
        """POST web/queryQRLoginStatus；retcode/status → QrPollResult（映射见 api_notes §5）。"""
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.post(f"{WEB_BASE}/queryQRLoginStatus",
                                             json={"ticket": ticket}, headers=self._web_headers())
        except httpx.HTTPError:
            raise DemiaogeError(ErrorCode.UPSTREAM_NETWORK, NETWORK_MESSAGE, request_id) from None
        try:
            result: Any = response.json()
        except ValueError:
            result = None
        if not isinstance(result, dict):
            raise DemiaogeError(ErrorCode.UPSTREAM_NETWORK, NETWORK_MESSAGE, request_id) from None
        code = result.get("retcode")
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        if code == 0:
            status = str(data.get("status") or "")
            if status == "Confirmed":
                return self._build_confirmed(data, response)
            if status in ("Created", "Scanned"):
                return QrPollResult(status=status)
            return QrPollResult(status="Risk")  # 未知名状态按风控处理，不透传
        if code == -3501:
            return QrPollResult(status="Expired")
        if code == -3505:
            return QrPollResult(status="Cancelled")
        return QrPollResult(status="Risk")  # -3503 及其他一律 Risk

    def _build_confirmed(self, data: dict[str, Any], response: httpx.Response) -> QrPollResult:
        user_info = data.get("user_info") if isinstance(data.get("user_info"), dict) else {}
        aid = str(user_info.get("aid") or "")
        user_mid = str(user_info.get("mid") or "")
        cookies = _parse_set_cookie(response.headers)
        for name, value in response.cookies.items():
            cookies.setdefault(name, value)

        def pick(*names: str) -> str:
            for name in names:
                if cookies.get(name):
                    return cookies[name]
            return ""

        bundle = CookieBundle(
            stuid=pick(*_TOKEN_NAMES["stuid"]) or aid,
            stoken=pick(*_TOKEN_NAMES["stoken"]),
            mid=pick(*_TOKEN_NAMES["mid"]) or user_mid,
            ltoken=pick(*_TOKEN_NAMES["ltoken"]),
            cookie_token=pick(*_TOKEN_NAMES["cookie_token"]),
            ltuid=pick(*_TOKEN_NAMES["ltuid"]) or aid,
        )
        return QrPollResult(status="Confirmed", user_info=dict(user_info), cookies=bundle)

    async def complete_with_stoken(self, bundle: CookieBundle, request_id: str) -> CookieBundle:
        """用 stoken 补齐 cookie_token/ltoken；任一步失败静默返回原 bundle（不抛异常）。"""
        if not bundle.stoken or not bundle.mid:
            return bundle
        cookie_header = f"mid={bundle.mid};stoken={bundle.stoken}"
        headers = {
            "Cookie": cookie_header,
            "DS": ds_simple(SALT_X4),
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Demiaoge/0.4",
        }
        filled = CookieBundle(
            stuid=bundle.stuid, stoken=bundle.stoken, mid=bundle.mid,
            ltoken=bundle.ltoken, cookie_token=bundle.cookie_token, ltuid=bundle.ltuid,
        )
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport,
                                         headers=headers) as client:
                token_response = await client.get(
                    f"{AUTH_BASE}/getCookieAccountInfoBySToken",
                    params={"stoken": bundle.stoken},
                )
                ltoken_response = await client.get(
                    f"{AUTH_BASE}/getLTokenBySToken",
                    params={"stoken": bundle.stoken},
                )
        except httpx.HTTPError:
            return bundle  # 静默保留原 bundle
        token_data = self._ok_data(token_response)
        if token_data:
            filled.cookie_token = str(token_data.get("cookie_token") or filled.cookie_token)
        ltoken_data = self._ok_data(ltoken_response)
        if ltoken_data:
            # getLTokenBySToken 文献返回 data.token；兼容 data.ltoken 命名。
            filled.ltoken = str(ltoken_data.get("ltoken") or ltoken_data.get("token") or filled.ltoken)
        return filled

    @staticmethod
    def _ok_data(response: httpx.Response) -> dict[str, Any]:
        try:
            result: Any = response.json()
        except ValueError:
            return {}
        if not isinstance(result, dict) or result.get("retcode") != 0:
            return {}
        data = result.get("data")
        return data if isinstance(data, dict) else {}
