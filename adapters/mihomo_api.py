"""Mihomo API 客户端（免 Cookie 主路径）。

`GET {base}/sr_info_parsed/{uid}?lang=cn`，无需 Cookie / DS（api_notes §1.1 实测）。
错误一律映射为固定中文文案的 :class:`DemiaogeError`，绝不透传上游原文：
- HTTP 400/404 且 body 含 ``detail`` → DATA_NOT_FOUND（对方未开展示与不存在统一文案，防探测）；
- httpx 网络异常 / 其他非 200 / 200 但 body 不是预期形状 → UPSTREAM_NETWORK（或 MAPPING_FAILED）。
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from ..domain.errors import DemiaogeError, ErrorCode, MappingError

BASE_URL = "https://api.mihomo.me"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Demiaoge/0.4"
)
NOT_FOUND_MESSAGE = "未找到该 UID 的资料，请确认对方已开启角色展示。"
NETWORK_MESSAGE = "数据服务暂时不可用。"


class MihomoApiClient:
    """sr_info_parsed 拉取器；``transport`` 仅测试注入 httpx.MockTransport 用。

    W8：共享 AsyncClient（连接/TLS 复用，省每查询一次握手）；事件循环变化
    （测试多次 asyncio.run）时重建，``aclose`` 供收尾。
    """

    def __init__(self, base_url: str = BASE_URL, timeout: float = 15.0,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._client_loop_id: int | None = None

    def _get_client(self) -> httpx.AsyncClient:
        loop_id = id(asyncio.get_running_loop())
        if self._client is None or self._client_loop_id != loop_id:
            self._client = httpx.AsyncClient(timeout=self._timeout, transport=self._transport,
                                             headers={"User-Agent": USER_AGENT})
            self._client_loop_id = loop_id
        return self._client

    async def aclose(self) -> None:
        client, self._client = self._client, None
        self._client_loop_id = None
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass  # 收尾路径，关闭失败不阻塞退出

    async def fetch_parsed(self, uid: str, request_id: str) -> dict[str, Any]:
        """拉取解析面板 JSON；失败抛固定文案错误，成功返回原始 parsed dict。"""
        url = f"{self._base_url}/sr_info_parsed/{uid}"
        try:
            response = await self._get_client().get(url, params={"lang": "cn"})
        except httpx.HTTPError:
            raise DemiaogeError(ErrorCode.UPSTREAM_NETWORK, NETWORK_MESSAGE, request_id) from None

        if response.status_code in (400, 404):
            # api_notes §4.1：400 "Invalid uid" / 404 "User not found"，统一 DATA_NOT_FOUND 固定文案。
            try:
                body: Any = response.json()
            except ValueError:
                body = None
            if isinstance(body, dict) and "detail" in body:
                raise DemiaogeError(ErrorCode.DATA_NOT_FOUND, NOT_FOUND_MESSAGE, request_id) from None
            raise DemiaogeError(ErrorCode.UPSTREAM_NETWORK, NETWORK_MESSAGE, request_id) from None
        if response.status_code != 200:
            raise DemiaogeError(ErrorCode.UPSTREAM_NETWORK, NETWORK_MESSAGE, request_id) from None

        try:
            payload: Any = response.json()
        except ValueError:
            raise DemiaogeError(ErrorCode.UPSTREAM_NETWORK, NETWORK_MESSAGE, request_id) from None
        if not isinstance(payload, dict) or not isinstance(payload.get("player"), dict):
            raise MappingError(request_id)

        player = payload["player"]
        characters = payload.get("characters")
        # is_display=False 或角色列表为空 → 与"不存在"统一文案，防止探测他人是否开启展示。
        if player.get("is_display") is False or not isinstance(characters, list) or not characters:
            raise DemiaogeError(ErrorCode.DATA_NOT_FOUND, NOT_FOUND_MESSAGE, request_id) from None
        return payload
