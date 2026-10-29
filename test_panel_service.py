"""W3 · PanelService 编排测试（全离线：fake client + 假渲染/真渲染注入）。

覆盖：panel/audit/character/light_cone 四用例、PNG 文件缓存与 payload 缓存命中
（第二次不再调 client）、角色别名/包含/歧义/未找到、光锥 wiki 资料合成与持有者、
渲染失败统一固定文案、本地图标解析与后台预热不阻塞。

运行（父目录）：python -m pytest -q astrbot_plugin_demiaoge/test_panel_service.py
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from astrbot_plugin_demiaoge.adapters.icon_cache import IconCache
from astrbot_plugin_demiaoge.domain.errors import DemiaogeError, ErrorCode
from astrbot_plugin_demiaoge.render.engine import find_edge
from astrbot_plugin_demiaoge.render.v2_models import CharacterVM, LightConeVM, PanelVM
from astrbot_plugin_demiaoge.services.cache_service import ProfileCache
from astrbot_plugin_demiaoge.services.panel_service import (
    CHARACTER_AMBIGUOUS_MESSAGE,
    CHARACTER_NOT_FOUND_MESSAGE,
    LIGHT_CONE_NOT_FOUND_MESSAGE,
    RENDER_FAILED_MESSAGE,
    PanelService,
)
from astrbot_plugin_demiaoge.services.wiki_service import WikiService

PLUGIN_DIR = Path(__file__).parent
DATA_DIR = PLUGIN_DIR / "data"
FIXTURES = DATA_DIR / "fixtures"
UID = "100895290"
RID = "rid-1"

# 恒 404 的 MockTransport：预热下载立即失败返回 ""，绝不触碰真实网络。
_OFFLINE_TRANSPORT = httpx.MockTransport(lambda request: httpx.Response(404, text="offline"))


def _fixture_payload() -> dict:
    return json.loads((FIXTURES / "mihomo_sr_info_parsed.json").read_text(encoding="utf-8"))


class FakeClient:
    """计数客户端：每次 fetch 返回 fixture 深拷贝，或抛注入的错误。"""

    def __init__(self, payload: dict, error: DemiaogeError | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls = 0

    async def fetch_parsed(self, uid: str, request_id: str) -> dict:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return json.loads(json.dumps(self.payload))


class RenderRecorder:
    """可注入 render_fn：记录 (kind, vm)，写固定同名 PNG 并返回路径；可选抛错。

    与真实渲染器契约一致：渲染器负责落盘并返回 PNG 文件路径（服务不再二次写盘）。
    """

    def __init__(self, body: bytes = b"PNG", error: Exception | None = None) -> None:
        self.body = body
        self.error = error
        self.calls: list[tuple[str, object]] = []

    def __call__(self, kind: str, vm, cache_dir: Path) -> Path:
        self.calls.append((kind, vm))
        if self.error is not None:
            raise self.error
        target = Path(cache_dir) / f"{kind}_fixed.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(self.body)
        return target


def _wiki(tmp_path: Path) -> WikiService:
    return WikiService([DATA_DIR / "characters.json", DATA_DIR / "light_cones.json"],
                       DATA_DIR / "aliases.json")


def _service(tmp_path: Path, client: FakeClient, render_recorder: RenderRecorder,
             icon_root: Path | None = None) -> PanelService:
    icon_cache = IconCache(root=icon_root if icon_root is not None else tmp_path / "icons",
                           transport=_OFFLINE_TRANSPORT)
    return PanelService(
        client,
        ProfileCache(tmp_path / "profile_cache", ttl_seconds=600),
        icon_cache,
        None,
        _wiki(tmp_path),
        tmp_path / "cards",
        render_fn=render_recorder,
    )


def _run(coro):
    return asyncio.run(coro)


# ---------- panel / audit ----------


def test_panel_png_renders_and_caches(tmp_path) -> None:
    client = FakeClient(_fixture_payload())
    recorder = RenderRecorder()
    service = _service(tmp_path, client, recorder)

    png_path = _run(service.panel_png(UID, RID))
    assert png_path.read_bytes() == b"PNG"
    assert png_path.is_file() and png_path.parent == tmp_path / "cards"
    assert client.calls == 1 and [kind for kind, _ in recorder.calls] == ["panel"]
    assert isinstance(recorder.calls[0][1], PanelVM)
    assert recorder.calls[0][1].uid == UID
    _run(service.wait_background())


def test_panel_png_second_call_hits_both_caches(tmp_path) -> None:
    client = FakeClient(_fixture_payload())
    recorder = RenderRecorder()
    service = _service(tmp_path, client, recorder)

    path1 = _run(service.panel_png(UID, RID))
    path2 = _run(service.panel_png(UID, RID))
    assert path1 == path2 and path2.read_bytes() == b"PNG"
    assert client.calls == 1         # payload 走 TTL 缓存，client 不再被调
    # 成图去重由渲染层文件缓存负责（引擎内容哈希键命中）：服务层每次都进渲染入口
    assert len(recorder.calls) == 2 and recorder.calls[0][0] == recorder.calls[1][0] == "panel"


def test_panel_png_renders_again_after_cache_invalidate(tmp_path) -> None:
    client = FakeClient(_fixture_payload())
    recorder = RenderRecorder()
    service = _service(tmp_path, client, recorder)

    _run(service.panel_png(UID, RID))
    service._cache.invalidate()
    _run(service.panel_png(UID, RID))
    # payload 未命中 → 重新取数；成图是否复用由渲染层内容哈希键决定
    assert client.calls == 2 and len(recorder.calls) == 2


def test_audit_png_uses_audit_vm(tmp_path) -> None:
    client = FakeClient(_fixture_payload())
    recorder = RenderRecorder()
    service = _service(tmp_path, client, recorder)

    png_path = _run(service.audit_png(UID, RID))
    assert png_path.read_bytes() == b"PNG"
    assert [kind for kind, _ in recorder.calls] == ["audit"]
    _run(service.wait_background())


def test_upstream_error_propagates(tmp_path) -> None:
    client = FakeClient({}, error=DemiaogeError(ErrorCode.UPSTREAM_NETWORK, "数据服务暂时不可用。"))
    recorder = RenderRecorder()
    service = _service(tmp_path, client, recorder)
    with pytest.raises(DemiaogeError) as exc:
        _run(service.panel_png(UID, RID))
    assert exc.value.code == ErrorCode.UPSTREAM_NETWORK
    assert str(exc.value) == "数据服务暂时不可用。"
    assert recorder.calls == []


# ---------- character ----------


def test_character_png_matches_exact_name(tmp_path) -> None:
    client = FakeClient(_fixture_payload())
    recorder = RenderRecorder()
    service = _service(tmp_path, client, recorder)

    png_path = _run(service.character_png(UID, "流萤", RID))
    assert png_path.read_bytes() == b"PNG"
    vm = recorder.calls[0][1]
    assert isinstance(vm, CharacterVM)
    assert vm.name == "流萤" and vm.eidolon == 2 and vm.level == 80
    assert vm.light_cone.name == "记一位星神的陨落"
    _run(service.wait_background())


def test_character_png_local_icon_resolver(tmp_path) -> None:
    client = FakeClient(_fixture_payload())
    recorder = RenderRecorder()
    icon_root = tmp_path / "icons"
    target = icon_root / "icon" / "character" / "1310.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"fake icon")
    service = _service(tmp_path, client, recorder, icon_root=icon_root)

    _run(service.character_png(UID, "流萤", RID))
    vm = recorder.calls[0][1]
    assert vm.avatar_path == str(target)  # 本地已有图标 → 绝对路径
    _run(service.wait_background())


def test_character_png_missing_and_ambiguous_messages(tmp_path) -> None:
    client = FakeClient(_fixture_payload())
    service = _service(tmp_path, client, RenderRecorder())

    with pytest.raises(DemiaogeError) as missing:
        _run(service.character_png(UID, "不存在的角色", RID))
    assert missing.value.code == ErrorCode.DATA_NOT_FOUND
    assert str(missing.value) == CHARACTER_NOT_FOUND_MESSAGE

    # 构造两个名字都包含"蝶"的角色 → 唯一包含匹配失败 → 歧义文案
    payload = _fixture_payload()
    payload["characters"][1]["name"] = "双蝶"
    payload["characters"][2]["name"] = "碟蝶"
    ambiguous_client = FakeClient(payload)
    with pytest.raises(DemiaogeError) as ambiguous:
        _run(PanelService(
            ambiguous_client,
            ProfileCache(tmp_path / "pc2", ttl_seconds=600),
            IconCache(root=tmp_path / "ic2", transport=_OFFLINE_TRANSPORT),
            None, _wiki(tmp_path), tmp_path / "cards2", render_fn=RenderRecorder(),
        ).character_png(UID, "蝶", RID))
    assert str(ambiguous.value) == CHARACTER_AMBIGUOUS_MESSAGE


def test_character_png_single_containment_match(tmp_path) -> None:
    client = FakeClient(_fixture_payload())
    recorder = RenderRecorder()
    service = _service(tmp_path, client, recorder)
    _run(service.character_png(UID, "萤", RID))  # 仅"流萤"包含"萤"
    assert recorder.calls[0][1].name == "流萤"


# ---------- light cone ----------


def test_light_cone_png_uses_wiki_data_without_uid(tmp_path) -> None:
    client = FakeClient(_fixture_payload())
    recorder = RenderRecorder()
    service = _service(tmp_path, client, recorder)

    _run(service.light_cone_png(None, "于夜色中", RID))
    assert client.calls == 0  # 无 UID → 纯资料卡，不取 payload
    vm = recorder.calls[0][1]
    assert isinstance(vm, LightConeVM)
    assert vm.name == "于夜色中" and vm.rarity == 5 and vm.path_name == "巡猎"
    # W6 重爬后该条目描述来自 BWiki「光锥故事」字段，非空
    assert len(vm.description) > 10
    assert len(vm.skills) == 1
    assert vm.skills[0].title == "花与蝶" and "暴击率" in vm.skills[0].description
    assert vm.owners == ()


def test_light_cone_png_alias_resolution(tmp_path) -> None:
    client = FakeClient(_fixture_payload())
    recorder = RenderRecorder()
    service = _service(tmp_path, client, recorder)
    _run(service.light_cone_png(None, "希儿专武", RID))  # aliases.json: 希儿专武→于夜色中
    assert recorder.calls[0][1].name == "于夜色中"


def test_light_cone_png_with_uid_collects_owners(tmp_path) -> None:
    client = FakeClient(_fixture_payload())
    recorder = RenderRecorder()
    service = _service(tmp_path, client, recorder)

    _run(service.light_cone_png(UID, "记一位星神的陨落", RID))
    vm = recorder.calls[0][1]
    assert len(vm.owners) == 1
    owner = vm.owners[0]
    assert owner.name == "流萤" and owner.level == 80 and owner.rank == 5 and owner.eidolon == 2
    _run(service.wait_background())


def test_light_cone_png_not_in_wiki_fixed_message(tmp_path) -> None:
    client = FakeClient(_fixture_payload())
    service = _service(tmp_path, client, RenderRecorder())
    with pytest.raises(DemiaogeError) as exc:
        _run(service.light_cone_png(None, "不存在的光锥名字", RID))
    assert exc.value.code == ErrorCode.DATA_NOT_FOUND
    assert str(exc.value) == LIGHT_CONE_NOT_FOUND_MESSAGE


# ---------- 渲染失败 ----------


def test_render_failure_maps_to_fixed_message(tmp_path) -> None:
    client = FakeClient(_fixture_payload())
    recorder = RenderRecorder(error=RuntimeError("Edge missing"))
    service = _service(tmp_path, client, recorder)
    with pytest.raises(DemiaogeError) as exc:
        _run(service.panel_png(UID, RID))
    assert exc.value.code == ErrorCode.RENDER_FAILED
    assert str(exc.value) == RENDER_FAILED_MESSAGE


# ---------- 真渲染（Edge 可用时；否则跳过） ----------


def test_panel_png_real_render_when_edge_available(tmp_path) -> None:
    if not find_edge():
        pytest.skip("本机未找到 Microsoft Edge，跳过真渲染")
    service = PanelService(
        FakeClient(_fixture_payload()),
        ProfileCache(tmp_path / "pc", ttl_seconds=600),
        IconCache(root=tmp_path / "ic", transport=_OFFLINE_TRANSPORT),
        None, _wiki(tmp_path), tmp_path / "cards",
    )
    png_path = _run(service.panel_png(UID, RID))
    data = png_path.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(data) > 1000
    _run(service.wait_background())
