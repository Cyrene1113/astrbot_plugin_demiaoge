"""渲染专用 ViewModel：渲染层不直接依赖领域模型字段。"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.models import PlayerProfile


ATTRIBUTE_NAMES = {
    "physical": "物理",
    "fire": "火",
    "ice": "冰",
    "lightning": "雷",
    "wind": "风",
    "quantum": "量子",
    "imaginary": "虚数",
}


@dataclass(frozen=True)
class CharacterCardViewModel:
    name: str
    level_text: str
    eidolon_text: str
    rarity_text: str


@dataclass(frozen=True)
class ProfileCardViewModel:
    uid_text: str
    nickname: str
    trailblaze_level_text: str
    characters: tuple[CharacterCardViewModel, ...]


def _safe_level(value: int) -> int:
    return max(0, min(int(value), 100))


def _mask_uid(uid: str) -> str:
    """只展示 UID 尾号，避免把账号标识完整放入图片。"""
    uid = str(uid or "")
    return f"****{uid[-4:]}" if len(uid) > 4 else "****"


def _stars(rarity: int) -> str:
    return "★" * max(0, min(int(rarity), 5)) or "未定"


def to_profile_viewmodel(profile: PlayerProfile) -> ProfileCardViewModel:
    characters = tuple(
        CharacterCardViewModel(
            name=str(character.name or "未知角色"),
            level_text=f"Lv.{_safe_level(character.level)}",
            eidolon_text=f"E{max(0, min(int(character.eidolons), 6))}",
            rarity_text=_stars(character.rarity),
        )
        for character in profile.characters
    )
    return ProfileCardViewModel(
        uid_text=_mask_uid(profile.uid),
        nickname=str(profile.nickname or "开拓者"),
        trailblaze_level_text=f"开拓等级 {_safe_level(profile.level)}",
        characters=characters,
    )
