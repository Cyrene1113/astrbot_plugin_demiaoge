"""米游社 game_record 客户端（Cookie 降级路径，本期只实现 index）。

头组合与 DS 公式按 ``docs/api_notes.md`` §1.2/§3：DS 用 b/q 式 + X4 salt、query 按
参数名字母序（``role_id`` < ``server``）、app_version 2.40.1 + client_type 5 +
Referer webstatic.mihoyo.com + miHoYoBBS UA。retcode 一律映射固定中文文案，
绝不透传上游 message。本路径为 Mihomo 主路径失败后的降级，不要求实网联调。
"""

from __future__ import annotations

from typing import Any

import httpx

from ..domain.errors import CookieExpiredError, DemiaogeError, ErrorCode, MappingError, RateLimitedError
from ..domain.models import PlayerProfile
from .ds import SALT_X4, ds_bq
from .mapper import map_profile

BASE_URL = "https://api-takumi-record.mihoyo.com/game_record/app/hkrpg/api"
APP_VERSION = "2.40.1"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 miHoYoBBS/2.40.1"
)
NETWORK_MESSAGE = "米游社服务暂时不可用。"
VERIFY_MESSAGE = "触发了安全验证，请稍后再试。"


def resolve_server(uid: str) -> str:
    """按 UID 首位推断 server：1-5 → 官服 prod_gf_cn，6-7 → B 服 prod_qd_cn。"""
    return "prod_qd_cn" if uid[:1] in {"6", "7"} else "prod_gf_cn"


class MihoyoRecordClient:
    """game_record index 查询（Cookie 路径）；``transport`` 供测试注入 MockTransport。"""

    def __init__(self, timeout: float = 15.0, salt: str = SALT_X4,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._timeout = timeout
        self._salt = salt
        self._transport = transport

    async def fetch_index(self, uid: str, server: str, cookie: str, request_id: str) -> dict[str, Any]:
        """GET index?role_id={uid}&server={server}，retcode=0 时返回 data dict。"""
        # query 按参数名字母序：role_id < server（Miao-Yunzai apiTool.js 硬编码同序）。
        query = f"role_id={uid}&server={server}"
        headers = {
            "DS": ds_bq(self._salt, body="", query=query),
            "x-rpc-app_version": APP_VERSION,
            "x-rpc-client_type": "5",
            "User-Agent": USER_AGENT,
            "Referer": "https://webstatic.mihoyo.com/",
            "Cookie": cookie,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport,
                                         headers=headers) as client:
                # 直接拼 URL，保证线上 query 顺序与 DS 的 q 串逐字一致（均为字母序）。
                response = await client.get(f"{BASE_URL}/index?{query}")
        except httpx.HTTPError:
            raise DemiaogeError(ErrorCode.UPSTREAM_NETWORK, NETWORK_MESSAGE, request_id) from None

        try:
            result: Any = response.json()
        except ValueError:
            raise DemiaogeError(ErrorCode.UPSTREAM_NETWORK, NETWORK_MESSAGE, request_id) from None
        if not isinstance(result, dict):
            raise MappingError(request_id)
        code = result.get("retcode")
        if code == 0:
            data = result.get("data")
            return data if isinstance(data, dict) else {}
        if code == -101:
            raise CookieExpiredError(request_id)
        if code == -110:
            raise RateLimitedError(request_id)
        if code == 1034:
            raise DemiaogeError(ErrorCode.AUTH_MISSING, VERIFY_MESSAGE, request_id)
        # 其余 retcode 一律固定文案，不透传上游 message。
        raise DemiaogeError(ErrorCode.UPSTREAM_NETWORK, NETWORK_MESSAGE, request_id) from None

    async def fetch_profile(self, uid: str, cookie: str, request_id: str) -> PlayerProfile:
        """index → PlayerProfile（复用既有保守 mapper，供降级调用方直接使用）。"""
        data = await self.fetch_index(uid, resolve_server(uid), cookie, request_id)
        return map_profile(data, fallback_uid=uid)

    async def fetch_note(self, uid: str, server: str, cookie: str, request_id: str) -> dict[str, Any]:
        """GET note?role_id={uid}&server={server}（实时便签：开拓力/委托等）。

        与 fetch_index 同一套头/DS/错误映射；端点出处 gsuid_core StarRailUID
        `sruid_utils/api/mys/api.py` STAR_RAIL_NOTE_URL（与 api_notes §1.2 一致）。
        仅接受本人扫码凭据（调用方保证），防串号在服务层强制。
        """
        # query 按参数名字母序：role_id < server（与 DS 的 q 串逐字一致）。
        query = f"role_id={uid}&server={server}"
        headers = {
            "DS": ds_bq(self._salt, body="", query=query),
            "x-rpc-app_version": APP_VERSION,
            "x-rpc-client_type": "5",
            "User-Agent": USER_AGENT,
            "Referer": "https://webstatic.mihoyo.com/",
            "Cookie": cookie,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport,
                                         headers=headers) as client:
                response = await client.get(f"{BASE_URL}/note?{query}")
        except httpx.HTTPError:
            raise DemiaogeError(ErrorCode.UPSTREAM_NETWORK, NETWORK_MESSAGE, request_id) from None
        try:
            result: Any = response.json()
        except ValueError:
            raise DemiaogeError(ErrorCode.UPSTREAM_NETWORK, NETWORK_MESSAGE, request_id) from None
        if not isinstance(result, dict):
            raise MappingError(request_id)
        code = result.get("retcode")
        if code == 0:
            data = result.get("data")
            return data if isinstance(data, dict) else {}
        if code == -101:
            raise CookieExpiredError(request_id)
        if code == -110:
            raise RateLimitedError(request_id)
        if code == 1034:
            raise DemiaogeError(ErrorCode.AUTH_MISSING, VERIFY_MESSAGE, request_id)
        raise DemiaogeError(ErrorCode.UPSTREAM_NETWORK, NETWORK_MESSAGE, request_id) from None
