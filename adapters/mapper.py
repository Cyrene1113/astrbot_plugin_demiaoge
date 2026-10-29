"""米游社响应到德谬歌领域模型的保守映射。"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..domain.errors import MappingError
from ..domain.models import CharacterSummary, PlayerProfile


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _first(item: dict[str, Any], *keys: str, default: Any = "") -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return default


def _characters(data: dict[str, Any]) -> tuple[CharacterSummary, ...]:
    raw = _first(data, "avatars", "avatar_list", "characters", default=[])
    if isinstance(raw, dict):
        raw = raw.get("list", [])
    if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes, dict)):
        return ()
    result: list[CharacterSummary] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(_first(item, "name", "item_name", "avatar_name", default="未知角色"))
        identity = str(_first(item, "id", "avatar_id", default=name))
        if identity in seen:
            continue
        seen.add(identity)
        result.append(CharacterSummary(
            name=name,
            level=_int(_first(item, "level", "cur_level", default=0)),
            eidolons=_int(_first(item, "rank", "eidolon_level", "rank_level", default=0)),
            rarity=_int(_first(item, "rarity", "star", default=5), 5),
        ))
    return tuple(result)


def map_profile(data: dict[str, Any], fallback_uid: str = "") -> PlayerProfile:
    """兼容 index/getCharacter/getMultiCharacter 的 data 结构。"""
    if not isinstance(data, dict):
        raise MappingError()
    role = data.get("role") if isinstance(data.get("role"), dict) else data
    uid = str(_first(role, "uid", "game_uid", "role_id", default=fallback_uid))
    if not uid:
        raise MappingError()
    nickname = str(_first(role, "nickname", "name", default="开拓者"))
    level = _int(_first(role, "level", "game_level", default=0))
    return PlayerProfile(uid=uid, nickname=nickname, level=level, characters=_characters(data))


def map_roles(payload: dict[str, Any]) -> list[dict[str, str]]:
    """提取 getUserGameRolesByCookie 的角色列表，仅保留非敏感字段。"""
    data = payload.get("data") if isinstance(payload, dict) else None
    items = data.get("list", []) if isinstance(data, dict) else []
    if not isinstance(items, list):
        raise MappingError()
    return [{
        "uid": str(_first(item, "game_uid", "uid", default="")),
        "nickname": str(_first(item, "nickname", default="")),
        "region": str(_first(item, "region", default="")),
    } for item in items if isinstance(item, dict)]
