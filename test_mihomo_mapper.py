"""W2 · Mihomo schema → 渲染视图模型映射测试（全离线，fixture 驱动）。

- map_mihomo_payload / map_character_detail / map_light_cone：按
  data/fixtures/mihomo_sr_info_parsed.json 与 mihomo_full_one_character.json 实测
  schema 断言固定字段表（E 数/突破/技能/叠影/词条/properties→stats/element.color）。
- 附带 MihomoApiClient 错误映射测试（MockTransport；fetch 是 mapper 的上游入口）。

运行（父目录）：python -m pytest -q astrbot_plugin_demiaoge/test_mihomo_mapper.py
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from astrbot_plugin_demiaoge.adapters.mihomo_api import MihomoApiClient
from astrbot_plugin_demiaoge.adapters.mihomo_mapper import (
    iter_icon_paths,
    map_character_detail,
    map_light_cone,
    map_mihomo_payload,
)
from astrbot_plugin_demiaoge.domain.errors import DemiaogeError, ErrorCode, MappingError
from astrbot_plugin_demiaoge.render.v2_models import (
    LightConeRef,
    RelicSetVM,
    SubAffix,
)

FIXTURES = Path(__file__).parent / "data" / "fixtures"
STUB_RESOLVER = lambda rel_path: ""  # noqa: E731 —— 图标解析桩，返回空串走占位


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_map_payload_panel_and_audit() -> None:
    payload = _load("mihomo_sr_info_parsed.json")
    panel, audit, chars = map_mihomo_payload(payload, STUB_RESOLVER)
    assert panel.uid == "100895290"
    assert panel.nickname == "洛尘"
    assert panel.level == 70 and panel.world_level == 6
    assert len(panel.characters) == 3
    first = panel.characters[0]
    assert first.name == "流萤" and first.level == 80 and first.eidolon == 2
    assert first.rarity == 5 and first.path_name == "毁灭"
    assert first.element_name == "火" and first.element_color == "#F84F36"
    assert first.light_cone_name == "记一位星神的陨落"
    assert first.light_cone_level == 80 and first.light_cone_rarity == 5
    assert first.avatar_path == "" and first.light_cone_icon == ""
    # 练度统计行与面板行一一对应
    assert len(audit.rows) == len(panel.characters) == 3
    assert audit.uid == panel.uid and audit.nickname == panel.nickname
    assert audit.rows[0].name == "流萤" and audit.rows[0].element_color == "#F84F36"
    # 角色以 id 为键
    assert set(chars) == {"1310", "1505", "1407"}
    assert chars["1310"].name == "流萤"


def test_map_character_detail_fixed_fields() -> None:
    full = _load("mihomo_full_one_character.json")
    vm = map_character_detail(full, STUB_RESOLVER)
    assert vm.name == "流萤"
    assert vm.rarity == 5 and vm.level == 80
    assert vm.promotion == 6 and vm.eidolon == 2  # rank → E 数、promotion → 突破
    assert vm.path_name == "毁灭" and vm.element_name == "火"
    assert vm.element_color == "#F84F36"  # element.color 直接透传
    # properties → stats：上游含同名条目（基础值 + 面板值），按名称去重取最后一个
    assert len(full["properties"]) == 12
    assert len(vm.stats) == len({item["name"] for item in full["properties"]}) == 9
    assert len({row.name for row in vm.stats}) == len(vm.stats)  # 无重复行
    assert vm.stats[0].name == "击破特攻" and vm.stats[0].final == "201.0%" and vm.stats[0].base == ""
    # skills：8 项中 MazeNormal 的 type_text 为空被过滤 → 7 行
    assert len(vm.skills) == 7
    assert [s.type_label for s in vm.skills][:4] == ["普攻", "战技", "终结技", "天赋"]
    assert vm.skills[0].name == "指令-闪燃推进" and vm.skills[0].level == 6 and vm.skills[0].max_level == 10
    # 遗器：主词条 display、副词条 display+step
    assert len(vm.relics) == 6
    relic0 = vm.relics[0]
    assert relic0.name == "铁骑的索敌战盔" and relic0.level == 15 and relic0.rarity == 5
    assert relic0.main_affix_name == "生命值" and relic0.main_affix_value == "705"
    assert relic0.subs[0] == SubAffix(name="攻击力", value="42（强化4）")
    # 套装 num → count
    assert len(vm.relic_sets) == 3
    assert vm.relic_sets[0] == RelicSetVM(name="荡除蠹灾的铁骑", count=2)
    assert vm.relic_sets[1] == RelicSetVM(name="荡除蠹灾的铁骑", count=4)
    # 光锥：name/level/rank(叠影)/rarity
    assert vm.light_cone == LightConeRef(name="记一位星神的陨落", level=80, rank=5, rarity=5, icon_path="")


def test_map_character_light_cone_none() -> None:
    full = dict(_load("mihomo_full_one_character.json"))
    full["light_cone"] = None
    vm = map_character_detail(full, STUB_RESOLVER)
    assert vm.light_cone == LightConeRef(name="", level=0, rank=0, rarity=0, icon_path="")


def test_map_light_cone_owners() -> None:
    full = _load("mihomo_full_one_character.json")
    owner_vm = map_character_detail(full, STUB_RESOLVER)
    lc_vm = map_light_cone(full["light_cone"], [owner_vm], STUB_RESOLVER)
    assert lc_vm.name == "记一位星神的陨落" and lc_vm.rarity == 5 and lc_vm.path_name == "毁灭"
    # Mihomo 光锥对象无描述/叠影文案 → 安全空值（W3 可另并 wiki 资料重建）
    assert lc_vm.description == "" and lc_vm.skills == ()
    assert len(lcvm_owners := lc_vm.owners) == 1
    owner = lcvm_owners[0]
    assert owner.name == "流萤" and owner.level == 80 and owner.rank == 5 and owner.eidolon == 2
    # 不持该光锥的角色不进 owners
    other = map_character_detail({"id": "1407", "name": "遐蝶"}, STUB_RESOLVER)
    assert map_light_cone(full["light_cone"], [other], STUB_RESOLVER).owners == ()


def test_map_missing_fields_safe_defaults() -> None:
    vm = map_character_detail({}, STUB_RESOLVER)
    assert vm.name == "" and vm.level == 0 and vm.rarity == 0
    assert vm.stats == () and vm.skills == () and vm.relics == () and vm.relic_sets == ()
    assert vm.light_cone == LightConeRef("", 0, 0, 0, "")
    panel, audit, chars = map_mihomo_payload({}, STUB_RESOLVER)
    assert panel.uid == "" and panel.characters == ()
    assert audit.rows == () and chars == {}
    # 残缺条目跳过而不抛异常
    panel2, _, chars2 = map_mihomo_payload({"characters": [None, "x", {"id": "1", "name": "测试"}]},
                                           STUB_RESOLVER)
    assert len(panel2.characters) == 1 and set(chars2) == {"1"}


def test_iter_icon_paths_collects_all() -> None:
    payload = _load("mihomo_sr_info_parsed.json")
    paths = list(iter_icon_paths(payload))
    assert "icon/character/1310.png" in paths
    assert "icon/light_cone/24000.png" in paths
    assert len(paths) == len(set(paths))  # 去重保序


def _client(handler) -> MihomoApiClient:
    return MihomoApiClient(transport=httpx.MockTransport(handler))


def test_mihomo_api_success_returns_payload() -> None:
    payload = _load("mihomo_sr_info_parsed.json")
    handler = lambda request: httpx.Response(200, json=payload)
    got = asyncio.run(_client(handler).fetch_parsed("100895290", "rid-1"))
    assert got["player"]["uid"] == "100895290"
    assert len(got["characters"]) == 3


@pytest.mark.parametrize("status", [400, 404])
def test_mihomo_api_not_found(status: int) -> None:
    handler = lambda request: httpx.Response(status, json={"detail": "User not found"})
    with pytest.raises(DemiaogeError) as exc:
        asyncio.run(_client(handler).fetch_parsed("999999999", "rid-2"))
    assert exc.value.code == ErrorCode.DATA_NOT_FOUND
    assert str(exc.value) == "未找到该 UID 的资料，请确认对方已开启角色展示。"


def test_mihomo_api_display_off_unified_message() -> None:
    payload = {"player": {"uid": "1", "is_display": False}, "characters": []}
    handler = lambda request: httpx.Response(200, json=payload)
    with pytest.raises(DemiaogeError) as exc:
        asyncio.run(_client(handler).fetch_parsed("100000001", "rid-3"))
    assert exc.value.code == ErrorCode.DATA_NOT_FOUND
    assert str(exc.value) == "未找到该 UID 的资料，请确认对方已开启角色展示。"


def test_mihomo_api_network_and_other_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("boom")

    with pytest.raises(DemiaogeError) as exc:
        asyncio.run(_client(handler).fetch_parsed("100000001", "rid-4"))
    assert exc.value.code == ErrorCode.UPSTREAM_NETWORK
    assert str(exc.value) == "数据服务暂时不可用。"

    server_error = lambda request: httpx.Response(503, text="unavailable")
    with pytest.raises(DemiaogeError) as exc2:
        asyncio.run(_client(server_error).fetch_parsed("100000001", "rid-5"))
    assert exc2.value.code == ErrorCode.UPSTREAM_NETWORK

    garbage = lambda request: httpx.Response(200, text="not-json")
    with pytest.raises(DemiaogeError) as exc3:
        asyncio.run(_client(garbage).fetch_parsed("100000001", "rid-6"))
    assert exc3.value.code == ErrorCode.UPSTREAM_NETWORK

    wrong_shape = lambda request: httpx.Response(200, json=[1, 2, 3])
    with pytest.raises(MappingError):
        asyncio.run(_client(wrong_shape).fetch_parsed("100000001", "rid-7"))
