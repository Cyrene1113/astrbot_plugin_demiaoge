"""公共查询 HTTP 端口（只读；DEVELOPMENT.md §7）。禁止 import astrbot。

- ``GET /hsr/profile?uid=xxx``      → 200 JSON（payload 机械投影，仅公开数据）
- ``GET /hsr/profile.png?uid=xxx``  → 200 PNG bytes（走 PanelService.panel_png）
- 缺 uid → 400 {"error":"missing uid"}；DATA_NOT_FOUND → 404；其余 → 502。
  错误码固定英文枚举，不透传任何上游细节；端点只读，无凭据输出。
- ``start()`` 返回 False 表示端口占用等启动失败（main 层只告警不阻塞插件加载）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from aiohttp import web

from ..domain.errors import DemiaogeError, ErrorCode
from .request_context import RequestContext

LOGGER = logging.getLogger("demiaoge.http")

MISSING_UID_ERROR = "missing uid"
NOT_FOUND_ERROR = "user_not_found_or_not_public"
UPSTREAM_ERROR = "upstream"


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def project_profile(payload: dict[str, Any]) -> dict[str, Any]:
    """parsed 面板 JSON → 公开查询 JSON（固定字段投影，缺失字段安全默认值）。"""
    player = _as_dict(payload.get("player"))
    rows = []
    for item in _as_list(payload.get("characters")):
        if not isinstance(item, dict):
            continue
        light_cone = _as_dict(item.get("light_cone"))
        rows.append({
            "name": str(item.get("name") or ""),
            "level": _as_int(item.get("level")),
            "eidolon": _as_int(item.get("rank")),
            "rarity": _as_int(item.get("rarity")),
            "path": str(_as_dict(item.get("path")).get("name") or ""),
            "element": str(_as_dict(item.get("element")).get("name") or ""),
            "light_cone": {
                "name": str(light_cone.get("name") or ""),
                "level": _as_int(light_cone.get("level")),
                "rank": _as_int(light_cone.get("rank")),
                "rarity": _as_int(light_cone.get("rarity")),
            },
        })
    return {
        "uid": str(player.get("uid") or ""),
        "nickname": str(player.get("nickname") or ""),
        "level": _as_int(player.get("level")),
        "world_level": _as_int(player.get("world_level")),
        "characters": rows,
    }


class HsrHttpServer:
    """只读查询端口；``panel_service_factory()`` 每请求取当前 PanelService 实例。"""

    def __init__(self, panel_service_factory: Callable[[], Any],
                 host: str = "127.0.0.1", port: int = 8765) -> None:
        self._factory = panel_service_factory
        self._host = host
        self._port = int(port)
        self._runner: web.AppRunner | None = None

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    def create_app(self) -> web.Application:
        """构建 aiohttp Application（独立出来便于测试客户端直接挂载）。"""
        app = web.Application()
        app.router.add_get("/hsr/profile", self._handle_profile)
        app.router.add_get("/hsr/profile.png", self._handle_profile_png)
        return app

    async def start(self) -> bool:
        """启动站点；成功 True，端口占用等 OSError → False（调用方只告警）。"""
        self._runner = web.AppRunner(self.create_app(), access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        try:
            await site.start()
        except OSError:
            await self.stop()
            return False
        return True

    async def stop(self) -> None:
        runner, self._runner = self._runner, None
        if runner is not None:
            await runner.cleanup()

    # ---------- handlers ----------

    async def _handle_profile(self, request: web.Request) -> web.Response:
        uid = (request.query.get("uid") or "").strip()
        if not uid:
            return web.json_response({"error": MISSING_UID_ERROR}, status=400)
        service = self._factory()
        try:
            payload, _ = await service.get_payload(uid, self._request_id())
        except DemiaogeError as exc:
            return self._error_response(exc)
        except Exception:
            LOGGER.exception("/hsr/profile 内部错误 uid=%s", uid)
            return web.json_response({"error": UPSTREAM_ERROR}, status=502)
        return web.json_response(project_profile(payload))

    async def _handle_profile_png(self, request: web.Request) -> web.StreamResponse:
        uid = (request.query.get("uid") or "").strip()
        if not uid:
            return web.json_response({"error": MISSING_UID_ERROR}, status=400)
        service = self._factory()
        try:
            png_path = await service.panel_png(uid, self._request_id())
        except DemiaogeError as exc:
            return self._error_response(exc)
        except Exception:
            LOGGER.exception("/hsr/profile.png 内部错误 uid=%s", uid)
            return web.json_response({"error": UPSTREAM_ERROR}, status=502)
        # panel_png 返回已落盘的 PNG 路径；FileResponse 由内核流式发送，不再读入内存。
        return web.FileResponse(png_path, headers={"Content-Type": "image/png"})

    def _request_id(self) -> str:
        return RequestContext.create().request_id

    @staticmethod
    def _error_response(exc: DemiaogeError) -> web.Response:
        if exc.code == ErrorCode.DATA_NOT_FOUND:
            return web.json_response({"error": NOT_FOUND_ERROR}, status=404)
        return web.json_response({"error": UPSTREAM_ERROR}, status=502)
