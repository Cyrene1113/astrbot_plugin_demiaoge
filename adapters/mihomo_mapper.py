"""Mihomo `sr_info_parsed` schema → 渲染视图模型（固定字段表，禁猜字段）。

字段名严格按 ``docs/api_notes.md`` §2 实测 schema 写死（证据 fixture：
``data/fixtures/mihomo_sr_info_parsed.json`` / ``mihomo_full_one_character.json``）：
- ``rank`` → 星魂 E 数、``promotion`` → 突破阶、``skills[].type_text`` → 技能标签；
- ``light_cone.rank`` → 叠影、``relics[].main_affix.display`` → 主词条、
  ``sub_affix[].display``(+``step``) → 副词条、``relic_sets[].num`` → 套件数；
- ``properties[]`` → CharacterVM.stats（最终面板，每条一行，base 列留空）；
- ``element.color`` 直接透传；``statistics/attributes/additions`` 本期用不上，忽略。

所有 map_* 为纯函数（仅 icon_resolver 注入）；缺失字段一律安全默认值
（``""`` / 0 / 空元组），不抛异常。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any

from ..render.v2_models import (
    AuditRow,
    AuditVM,
    CharacterVM,
    LightConeRef,
    LightConeOwnerVM,
    LightConeVM,
    PanelRow,
    PanelVM,
    RelicSetVM,
    RelicVM,
    SkillRow,
    StatRow,
    SubAffix,
)

# icon_resolver：相对路径 → 本地绝对路径（拿不到给 ""，渲染层自行占位）。
IconResolver = Callable[[str], str]


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ("" if value is None else str(value))


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _sub_value(sub: dict[str, Any]) -> str:
    """副词条展示值：display 为主；带强化档时附注（渲染层会在值前再加一个“+”）。"""
    display = _str(sub.get("display"))
    step = _int(sub.get("step"))
    return f"{display}（强化{step}）" if step > 0 and display else display


def _light_cone_ref(lc: Any, icon_resolver: IconResolver) -> LightConeRef:
    """light_cone 为 null / 缺失时返回全空 LightConeRef。"""
    data = _dict(lc)
    if not data:
        return LightConeRef(name="", level=0, rank=0, rarity=0, icon_path="")
    return LightConeRef(
        name=_str(data.get("name")),
        level=_int(data.get("level")),
        rank=_int(data.get("rank")),
        rarity=_int(data.get("rarity")),
        icon_path=icon_resolver(_str(data.get("icon"))),
    )


def map_character_detail(char: dict[str, Any], icon_resolver: IconResolver) -> CharacterVM:
    """单个角色 dict → CharacterVM（字段表写死，见模块 docstring）。"""
    data = _dict(char)
    path = _dict(data.get("path"))
    element = _dict(data.get("element"))
    # properties 含同名条目（如两个"攻击力"：基础值与面板最终值），按名称去重取最后
    # 一个（上游顺序即基础在前、最终在后），避免卡片属性表出现重复行。
    stats_by_name: dict[str, StatRow] = {}
    for item in _list(data.get("properties")):
        if not isinstance(item, dict):
            continue
        stat_name = _str(item.get("name"))
        if not stat_name:
            continue
        stats_by_name[stat_name] = StatRow(
            name=stat_name, base="", final=_str(item.get("display")))
    stats = tuple(stats_by_name.values())
    # type_text 为空的条目是无名占位技能（如 MazeNormal，name 为纯数字 id），不进卡片。
    skills = tuple(
        SkillRow(
            name=_str(item.get("name")),
            level=_int(item.get("level")),
            max_level=_int(item.get("max_level")),
            type_label=_str(item.get("type_text")),
        )
        for item in _list(data.get("skills"))
        if isinstance(item, dict) and _str(item.get("type_text"))
    )
    relics = tuple(
        RelicVM(
            name=_str(item.get("name")),
            level=_int(item.get("level")),
            rarity=_int(item.get("rarity")),
            icon_path=icon_resolver(_str(item.get("icon"))),
            main_affix_name=_str(_dict(item.get("main_affix")).get("name")),
            main_affix_value=_str(_dict(item.get("main_affix")).get("display")),
            subs=tuple(
                SubAffix(name=_str(sub.get("name")), value=_sub_value(sub))
                for sub in _list(item.get("sub_affix"))
                if isinstance(sub, dict)
            ),
        )
        for item in _list(data.get("relics"))
        if isinstance(item, dict)
    )
    relic_sets = tuple(
        RelicSetVM(name=_str(item.get("name")), count=_int(item.get("num")))
        for item in _list(data.get("relic_sets"))
        if isinstance(item, dict)
    )
    return CharacterVM(
        name=_str(data.get("name")),
        avatar_path=icon_resolver(_str(data.get("icon"))),
        rarity=_int(data.get("rarity")),
        level=_int(data.get("level")),
        promotion=_int(data.get("promotion")),
        eidolon=_int(data.get("rank")),
        path_name=_str(path.get("name")),
        element_name=_str(element.get("name")),
        element_color=_str(element.get("color")),
        stats=stats,
        skills=skills,
        light_cone=_light_cone_ref(data.get("light_cone"), icon_resolver),
        relics=relics,
        relic_sets=relic_sets,
    )


def _panel_row(vm: CharacterVM) -> PanelRow:
    return PanelRow(
        name=vm.name,
        avatar_path=vm.avatar_path,
        level=vm.level,
        eidolon=vm.eidolon,
        rarity=vm.rarity,
        path_name=vm.path_name,
        element_name=vm.element_name,
        element_color=vm.element_color,
        light_cone_name=vm.light_cone.name,
        light_cone_level=vm.light_cone.level,
        light_cone_rarity=vm.light_cone.rarity,
        light_cone_icon=vm.light_cone.icon_path,
    )


def _audit_row(vm: CharacterVM) -> AuditRow:
    return AuditRow(
        name=vm.name,
        avatar_path=vm.avatar_path,
        level=vm.level,
        eidolon=vm.eidolon,
        rarity=vm.rarity,
        path_name=vm.path_name,
        element_name=vm.element_name,
        element_color=vm.element_color,
    )


def map_mihomo_payload(payload: dict[str, Any], icon_resolver: IconResolver,
                       ) -> tuple[PanelVM, AuditVM, dict[str, CharacterVM]]:
    """parsed 面板 JSON → (面板总览 VM, 练度统计 VM, {角色id: CharacterVM})。"""
    data = _dict(payload)
    player = _dict(data.get("player"))
    uid = _str(player.get("uid"))
    nickname = _str(player.get("nickname"))
    level = _int(player.get("level"))
    world_level = _int(player.get("world_level"))

    characters: dict[str, CharacterVM] = {}
    panel_rows: list[PanelRow] = []
    audit_rows: list[AuditRow] = []
    for item in _list(data.get("characters")):
        if not isinstance(item, dict):
            continue
        vm = map_character_detail(item, icon_resolver)
        char_id = _str(item.get("id"))
        if char_id:
            characters[char_id] = vm
        panel_rows.append(_panel_row(vm))
        audit_rows.append(_audit_row(vm))
    return (
        PanelVM(uid=uid, nickname=nickname, level=level, world_level=world_level,
                characters=tuple(panel_rows)),
        AuditVM(uid=uid, nickname=nickname, rows=tuple(audit_rows)),
        characters,
    )


def map_light_cone(lc: dict[str, Any], owner_chars: Sequence[CharacterVM],
                   icon_resolver: IconResolver) -> LightConeVM:
    """光锥 dict + 持有该光锥的角色 VM → 光锥资料卡 VM。

    Mihomo 光锥对象不含描述与叠影文案（api_notes §2.2），description/skills 留安全
    空值，由调用方（W3）如需补充资料可另行合并 wiki 数据后重建 VM。
    """
    data = _dict(lc)
    name = _str(data.get("name"))
    owners = tuple(
        LightConeOwnerVM(
            name=vm.name,
            level=vm.level,
            rank=vm.light_cone.rank,
            eidolon=vm.eidolon,
            icon_path=vm.avatar_path,
        )
        for vm in owner_chars
        if isinstance(vm, CharacterVM) and vm.light_cone.name == name
    )
    return LightConeVM(
        name=name,
        rarity=_int(data.get("rarity")),
        path_name=_str(_dict(data.get("path")).get("name")),
        description="",
        skills=(),
        owners=owners,
    )


def iter_icon_paths(payload: dict[str, Any]) -> Iterable[str]:
    """收集面板 payload 里全部相对图标路径（去重保序），供 resolve_many 预热缓存。"""
    data = _dict(payload)
    player = _dict(data.get("player"))
    paths: list[str] = []
    avatar_icon = _str(_dict(player.get("avatar")).get("icon"))
    if avatar_icon:
        paths.append(avatar_icon)
    for item in _list(data.get("characters")):
        if not isinstance(item, dict):
            continue
        for value in (item.get("icon"), _dict(item.get("light_cone")).get("icon")):
            rel = _str(value)
            if rel:
                paths.append(rel)
        for relic in _list(item.get("relics")):
            if isinstance(relic, dict) and _str(relic.get("icon")):
                paths.append(_str(relic.get("icon")))
    seen: set[str] = set()
    ordered: list[str] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered
