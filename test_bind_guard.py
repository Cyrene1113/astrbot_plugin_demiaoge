"""W7 · 账号绑定防串号 + 实时便签（体力）测试（全离线）。

覆盖三块：
1. 凭据隔离：A 的绑定/当前指针与 B 完全隔离；跨 owner 读不到对方凭据。
2. 绑定加固：同人同 UID 去重（find_uid）、切换当前账号（set_current/get_current）、
   解绑当前账号后指针回落、resolve_uid 优先 current 指针。
3. 体力服务防串号：UID 绑定（无扫码凭据）拒绝；他人无法通过参数指定别人账号；
   note JSON → NoteVM 固定字段映射（缺字段安全默认、UI 隐藏空区块）。

运行（父目录）：python -m pytest -q astrbot_plugin_demiaoge/test_bind_guard.py
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from astrbot_plugin_demiaoge.adapters.icon_cache import IconCache
from astrbot_plugin_demiaoge.domain.errors import DemiaogeError, ErrorCode
from astrbot_plugin_demiaoge.render.v2_models import NoteVM
from astrbot_plugin_demiaoge.services.cache_service import ProfileCache
from astrbot_plugin_demiaoge.services.panel_service import (
    NOTE_NEED_QR_MESSAGE,
    NOTE_NO_BINDING_MESSAGE,
    PanelService,
)
from astrbot_plugin_demiaoge.services.uid_resolver import NO_BINDING_MESSAGE, resolve_uid
from astrbot_plugin_demiaoge.services.wiki_service import WikiService
from astrbot_plugin_demiaoge.storage.credentials import CredentialStore

OWNER_A = "user-a"
OWNER_B = "user-b"
UID_A = "100000001"
UID_B = "200000002"
OFFLINE = httpx.MockTransport(lambda request: httpx.Response(404, text="offline"))


@pytest.fixture()
def store(tmp_path):
    return CredentialStore(tmp_path / "credentials.json", "w7-master-key")


# ---------- 1. 凭据隔离 ----------


def test_owners_are_isolated(store) -> None:
    store.bind(OWNER_A, "default", "stoken-a", uid=UID_A, bind_type="qr", stoken="s-a")
    store.bind(OWNER_B, "default", "stoken-b", uid=UID_B, bind_type="qr", stoken="s-b")

    assert store.get_bundle(OWNER_A, "default")["uid"] == UID_A
    assert store.get_bundle(OWNER_B, "default")["uid"] == UID_B
    # 跨 owner 读对方别名：拿不到
    store.bind(OWNER_A, "小号", "stoken-a2", uid="300000003", bind_type="uid")
    assert store.get_bundle(OWNER_B, "小号") is None
    assert store.get_current(OWNER_B) == "default"  # 指针同样互不影响


def test_find_uid_detects_duplicate_and_respects_owner(store) -> None:
    store.bind(OWNER_A, "default", "p", uid=UID_A, bind_type="uid")
    assert store.find_uid(OWNER_A, UID_A) == "default"
    assert store.find_uid(OWNER_B, UID_A) is None  # 他人绑定不算重复
    assert store.find_uid(OWNER_A, "") is None


# ---------- 2. 当前账号指针 ----------


def test_set_current_and_fallback(store) -> None:
    store.bind(OWNER_A, "default", "p", uid=UID_A, bind_type="uid")
    store.bind(OWNER_A, "小号", "p", uid="300000003", bind_type="uid")

    assert store.get_current(OWNER_A) == "default"       # 未设置 → default
    assert store.set_current(OWNER_A, "小号") is True
    assert store.get_current(OWNER_A) == "小号"
    assert store.set_current(OWNER_A, "不存在") is False  # 只允许已绑定别名
    assert store.get_current(OWNER_A) == "小号"


def test_unbind_current_falls_back_to_default(store) -> None:
    store.bind(OWNER_A, "default", "p", uid=UID_A, bind_type="uid")
    store.bind(OWNER_A, "小号", "p", uid="300000003", bind_type="uid")
    store.set_current(OWNER_A, "小号")

    assert store.unbind(OWNER_A, "小号") is True
    assert store.get_current(OWNER_A) == "default"


def test_resolve_uid_prefers_current_pointer(store) -> None:
    store.bind(OWNER_A, "default", "p", uid=UID_A, bind_type="uid")
    store.bind(OWNER_A, "小号", "p", uid="300000003", bind_type="uid")

    assert resolve_uid(None, store, OWNER_A) == (UID_A, "")   # 默认 default
    store.set_current(OWNER_A, "小号")
    assert resolve_uid(None, store, OWNER_A) == ("300000003", "")
    # 显式参数仍优先于指针
    assert resolve_uid("default", store, OWNER_A) == (UID_A, "")
    # 他人视角：A 的指针不影响 B
    assert resolve_uid(None, store, OWNER_B) == (None, NO_BINDING_MESSAGE)


# ---------- 3. 体力服务防串号 ----------


class FakeRecordClient:
    """记录调用参数；返回固定 note JSON（或抛注入错误）。"""

    def __init__(self, data: dict | None = None, error: Exception | None = None) -> None:
        self.data = data or {}
        self.error = error
        self.calls: list[tuple[str, str, str, str]] = []

    async def fetch_note(self, uid: str, server: str, cookie: str, request_id: str) -> dict:
        self.calls.append((uid, server, cookie, request_id))
        if self.error is not None:
            raise self.error
        return dict(self.data)


def _service(tmp_path: Path, store, record_client=None) -> PanelService:
    class NoClient:
        async def fetch_parsed(self, uid: str, request_id: str) -> dict:
            raise AssertionError("体力用例不应走 Mihomo 客户端")

    return PanelService(
        NoClient(),
        ProfileCache(tmp_path / "pc", ttl_seconds=600),
        IconCache(root=tmp_path / "ic", transport=OFFLINE),
        store,
        WikiService([tmp_path / "nowhere.json"]),
        tmp_path / "cards",
        render_fn=lambda kind, vm, cache_dir: (Path(cache_dir) / f"{kind}_fixed.png"),
        record_client=record_client or FakeRecordClient(),
    )


NOTE_JSON = {
    "current_stamina": 137, "max_stamina": 240, "stamina_recover_time": 7020,
    "accepted_expedition_num": 4, "total_expedition_num": 4,
    "expeditions": [
        {"name": "奖励委托", "status": "Finished", "remaining_time": 0},
        {"name": "探索委托", "status": "Ongoing", "remaining_time": 5025},
    ],
}


def test_note_requires_binding(tmp_path, store) -> None:
    service = _service(tmp_path, store)
    with pytest.raises(DemiaogeError) as exc:
        asyncio.run(service.note_png(OWNER_A, "rid"))
    assert exc.value.code == ErrorCode.AUTH_MISSING
    assert str(exc.value) == NOTE_NO_BINDING_MESSAGE


def test_note_rejects_uid_only_binding(tmp_path, store) -> None:
    store.bind(OWNER_A, "default", UID_A, uid=UID_A, bind_type="uid")
    service = _service(tmp_path, store)
    with pytest.raises(DemiaogeError) as exc:
        asyncio.run(service.note_png(OWNER_A, "rid"))
    assert str(exc.value) == NOTE_NEED_QR_MESSAGE


def test_note_uses_only_callers_own_credentials(tmp_path, store) -> None:
    store.bind(OWNER_A, "default", "cookie-a", uid=UID_A, bind_type="qr", stoken="tok-a")
    store.bind(OWNER_B, "default", "cookie-b", uid=UID_B, bind_type="qr", stoken="tok-b")
    client = FakeRecordClient(NOTE_JSON)
    service = _service(tmp_path, store, client)

    path = asyncio.run(service.note_png(OWNER_A, "rid"))
    assert path.name == "note_fixed.png"
    # 只调一次，且用 A 自己的 uid+cookie —— 不存在任何用参数指定他人账号的入口
    assert len(client.calls) == 1
    uid, server, cookie, _ = client.calls[0]
    assert uid == UID_A and server == "prod_gf_cn" and cookie == "cookie-a"


def test_note_uses_current_alias_pointer(tmp_path, store) -> None:
    store.bind(OWNER_A, "default", "cookie-a", uid=UID_A, bind_type="qr")
    store.bind(OWNER_A, "小号", "cookie-a2", uid="300000003", bind_type="qr")
    store.set_current(OWNER_A, "小号")
    client = FakeRecordClient(NOTE_JSON)
    service = _service(tmp_path, store, client)
    asyncio.run(service.note_png(OWNER_A, "rid"))
    assert client.calls[0][0] == "300000003" and client.calls[0][2] == "cookie-a2"


def test_note_server_inferred_from_uid(tmp_path, store) -> None:
    store.bind(OWNER_A, "default", "cookie-b", uid="600000001", bind_type="qr")
    client = FakeRecordClient(NOTE_JSON)
    service = _service(tmp_path, store, client)
    asyncio.run(service.note_png(OWNER_A, "rid"))
    assert client.calls[0][1] == "prod_qd_cn"  # 6 开头 → B 服


def test_note_viewmodel_mapping(tmp_path, store) -> None:
    store.bind(OWNER_A, "default", "c", uid=UID_A, bind_type="qr")
    service = _service(tmp_path, store)
    vm = service._note_viewmodel(UID_A, NOTE_JSON)
    assert isinstance(vm, NoteVM)
    assert vm.current_stamina == 137 and vm.max_stamina == 240
    assert vm.recover_seconds == 7020
    assert len(vm.expeditions) == 2
    assert vm.expeditions[0].finished is True and vm.expeditions[0].status_text == "已完成"
    assert vm.expeditions[1].finished is False
    assert vm.expeditions[1].status_text == "剩余 01:23:45"  # 5025s
    # 上游缺失的实训/周本字段 → -1 → 模板自动隐藏区块
    assert vm.daily_train_score == -1 and vm.weekly_rogue_count == -1


def test_note_viewmodel_tolerates_missing_fields(tmp_path, store) -> None:
    service = _service(tmp_path, store)
    vm = service._note_viewmodel(UID_A, {})
    assert vm.current_stamina == 0 and vm.max_stamina == 0 and vm.expeditions == ()


def test_note_upstream_error_propagates(tmp_path, store) -> None:
    store.bind(OWNER_A, "default", "c", uid=UID_A, bind_type="qr")
    error = DemiaogeError(ErrorCode.AUTH_EXPIRED, "绑定凭据已失效，请重新绑定。")
    service = _service(tmp_path, store, FakeRecordClient(error=error))
    with pytest.raises(DemiaogeError) as exc:
        asyncio.run(service.note_png(OWNER_A, "rid"))
    assert exc.value.code == ErrorCode.AUTH_EXPIRED
