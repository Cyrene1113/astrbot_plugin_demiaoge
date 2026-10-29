"""W3 · 公共查询 HTTP 端口测试（全离线，aiohttp.test_utils，不 import astrbot）。

用 HsrHttpServer.create_app() 挂 TestServer/TestClient 打路由：
/hsr/profile JSON 投影结构与取值、缺 uid 400、DATA_NOT_FOUND 404 / 其他 502
固定英文错误码、profile.png 的 content-type 与字节；另验证真实 bind（端口占用
→ start() 返回 False、stop 后可重启）。

运行（父目录）：python -m pytest -q astrbot_plugin_demiaoge/test_http_api.py
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import socket
from pathlib import Path

import httpx
from aiohttp.test_utils import TestClient, TestServer

from astrbot_plugin_demiaoge.adapters.icon_cache import IconCache
from astrbot_plugin_demiaoge.domain.errors import DemiaogeError, ErrorCode
from astrbot_plugin_demiaoge.services.cache_service import ProfileCache
from astrbot_plugin_demiaoge.services.http_server import HsrHttpServer
from astrbot_plugin_demiaoge.services.panel_service import PanelService
from astrbot_plugin_demiaoge.services.wiki_service import WikiService

PLUGIN_DIR = Path(__file__).parent
UID = "100895290"
OFFLINE_TRANSPORT = httpx.MockTransport(lambda request: httpx.Response(404, text="offline"))


def _fixture_payload() -> dict:
    return json.loads((PLUGIN_DIR / "data" / "fixtures" / "mihomo_sr_info_parsed.json")
                      .read_text(encoding="utf-8"))


class FakeClient:
    def __init__(self, payload: dict | None = None, error: DemiaogeError | None = None) -> None:
        self.payload = payload or {}
        self.error = error
        self.calls = 0

    async def fetch_parsed(self, uid: str, request_id: str) -> dict:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return json.loads(json.dumps(self.payload))


def _fake_render(kind: str, vm, cache_dir: Path) -> Path:
    """渲染层契约：落盘 PNG 并返回路径（与真实渲染器一致，服务不再二次写盘）。"""
    target = Path(cache_dir) / f"{kind}_fixed.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\x89PNG\r\n\x1a\nFAKE")
    return target


def _make_service(tmp_path: Path, client: FakeClient) -> PanelService:
    return PanelService(
        client,
        ProfileCache(tmp_path / "profile_cache", ttl_seconds=600),
        IconCache(root=tmp_path / "icons", transport=OFFLINE_TRANSPORT),
        None,
        WikiService([tmp_path / "nowhere.json"]),  # 空 wiki：HTTP 用例不需要资料
        tmp_path / "cards",
        render_fn=_fake_render,
    )


def _make_server(tmp_path: Path, client: FakeClient) -> HsrHttpServer:
    service = _make_service(tmp_path, client)
    return HsrHttpServer(lambda: service, host="127.0.0.1", port=0)


def _free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# ---------- /hsr/profile JSON ----------


def test_profile_json_shape_and_values(tmp_path) -> None:
    async def run() -> None:
        server = _make_server(tmp_path, FakeClient(_fixture_payload()))
        async with TestClient(TestServer(server.create_app())) as client:
            resp = await client.get("/hsr/profile", params={"uid": UID})
            assert resp.status == 200
            assert resp.content_type == "application/json"
            data = await resp.json()
        assert data["uid"] == "100895290"
        assert data["nickname"] == "洛尘"
        assert data["level"] == 70 and data["world_level"] == 6
        assert len(data["characters"]) == 3
        first = data["characters"][0]
        assert set(first) == {"name", "level", "eidolon", "rarity", "path", "element", "light_cone"}
        assert first["name"] == "流萤" and first["level"] == 80
        assert first["eidolon"] == 2 and first["rarity"] == 5
        assert first["path"] == "毁灭" and first["element"] == "火"
        assert first["light_cone"] == {"name": "记一位星神的陨落", "level": 80, "rank": 5, "rarity": 5}

    asyncio.run(run())


def test_profile_json_missing_uid_is_400(tmp_path) -> None:
    async def run() -> None:
        server = _make_server(tmp_path, FakeClient(_fixture_payload()))
        async with TestClient(TestServer(server.create_app())) as client:
            resp = await client.get("/hsr/profile")
            assert resp.status == 400
            assert await resp.json() == {"error": "missing uid"}

    asyncio.run(run())


def test_profile_json_data_not_found_is_404_fixed_code(tmp_path) -> None:
    async def run() -> None:
        error = DemiaogeError(ErrorCode.DATA_NOT_FOUND, "未找到该 UID 的资料，请确认对方已开启角色展示。")
        server = _make_server(tmp_path, FakeClient(error=error))
        async with TestClient(TestServer(server.create_app())) as client:
            resp = await client.get("/hsr/profile", params={"uid": "999999999"})
            assert resp.status == 404
            assert await resp.json() == {"error": "user_not_found_or_not_public"}

    asyncio.run(run())


def test_profile_json_upstream_and_internal_errors_are_502(tmp_path) -> None:
    async def run() -> None:
        network = DemiaogeError(ErrorCode.UPSTREAM_NETWORK, "数据服务暂时不可用。")
        server = _make_server(tmp_path, FakeClient(error=network))
        async with TestClient(TestServer(server.create_app())) as client:
            resp = await client.get("/hsr/profile", params={"uid": UID})
            assert resp.status == 502
            assert await resp.json() == {"error": "upstream"}

        class BoomClient:
            async def fetch_parsed(self, uid: str, request_id: str) -> dict:
                raise RuntimeError("boom")

        boom_service = PanelService(
            BoomClient(),
            ProfileCache(tmp_path / "pc2", ttl_seconds=600),
            IconCache(root=tmp_path / "ic2", transport=OFFLINE_TRANSPORT),
            None, WikiService([tmp_path / "nowhere.json"]), tmp_path / "cards2",
            render_fn=_fake_render,
        )
        boom_server = HsrHttpServer(lambda: boom_service, host="127.0.0.1", port=0)
        async with TestClient(TestServer(boom_server.create_app())) as client:
            resp = await client.get("/hsr/profile", params={"uid": UID})
            assert resp.status == 502
            assert await resp.json() == {"error": "upstream"}

    asyncio.run(run())


# ---------- /hsr/profile.png ----------


def test_profile_png_route_content_type_and_body(tmp_path) -> None:
    async def run() -> None:
        client_fake = FakeClient(_fixture_payload())
        server = _make_server(tmp_path, client_fake)
        async with TestClient(TestServer(server.create_app())) as client:
            resp = await client.get("/hsr/profile.png", params={"uid": UID})
            assert resp.status == 200
            assert resp.content_type == "image/png"
            body = await resp.read()
            assert body.startswith(b"\x89PNG\r\n\x1a\n")
            # 第二次：payload 缓存 + 成图缓存命中，client 不再被调
            resp2 = await client.get("/hsr/profile.png", params={"uid": UID})
            assert resp2.status == 200
            assert client_fake.calls == 1
            # 错误路径同样回 JSON
            resp3 = await client.get("/hsr/profile.png")
            assert resp3.status == 400
            assert await resp3.json() == {"error": "missing uid"}

    asyncio.run(run())


def test_profile_png_not_found_is_404_json(tmp_path) -> None:
    async def run() -> None:
        error = DemiaogeError(ErrorCode.DATA_NOT_FOUND, "未找到该 UID 的资料，请确认对方已开启角色展示。")
        server = _make_server(tmp_path, FakeClient(error=error))
        async with TestClient(TestServer(server.create_app())) as client:
            resp = await client.get("/hsr/profile.png", params={"uid": "999999999"})
            assert resp.status == 404
            assert await resp.json() == {"error": "user_not_found_or_not_public"}

    asyncio.run(run())


# ---------- start/stop 生命周期 ----------


def test_start_stop_and_port_conflict(tmp_path) -> None:
    async def run() -> None:
        import aiohttp

        server = _make_server(tmp_path, FakeClient(_fixture_payload()))
        port = _free_port()

        # 先占住端口：start() 应返回 False（OSError→端口占用），调用方只告警不阻塞
        holder = await asyncio.get_running_loop().create_server(
            asyncio.Protocol, host="127.0.0.1", port=port)
        conflict = HsrHttpServer(lambda: None, host="127.0.0.1", port=port)
        try:
            assert await conflict.start() is False
        finally:
            holder.close()
            await holder.wait_closed()

        # 空闲端口：start() 成功，真实 socket 上端到端可查
        service = _make_service(tmp_path, FakeClient(_fixture_payload()))
        real = HsrHttpServer(lambda: service, host="127.0.0.1", port=port)
        assert await real.start() is True
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://127.0.0.1:{port}/hsr/profile",
                                       params={"uid": UID}) as resp:
                    assert resp.status == 200
                    data = await resp.json()
                    assert data["uid"] == UID
        finally:
            await real.stop()

        # stop 后端口已释放：连接被拒
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"http://127.0.0.1:{port}/hsr/profile",
                                       params={"uid": UID}) as resp:
                    raise AssertionError(f"stop 后仍可访问: {resp.status}")
            except aiohttp.ClientConnectionError:
                pass  # 预期：端口已关闭

    asyncio.run(run())
