"""v0.4 渲染视图模型（View Model）。

API 适配层（W2 mapper）与渲染层（4 张卡片模板）之间的**固定契约**：
本模块全部为 frozen dataclass 纯数据类，字段只有 str/int/嵌套小 dataclass，
不依赖任何 API JSON 结构。W2 负责把 Mihomo / 米游社响应喂成这些对象，
渲染模板只认这里的字段。

图标约定：``*_path`` 字段为本地图标文件的绝对路径字符串；拿不到图标时传空串，
模板会自动用 ``placeholder_icon`` 占位图或色块兜底，不报错。
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PanelRow:
    """面板总览图里的单个角色行。"""

    name: str
    avatar_path: str
    level: int
    eidolon: int
    rarity: int
    path_name: str
    element_name: str
    element_color: str
    light_cone_name: str
    light_cone_level: int
    light_cone_rarity: int
    light_cone_icon: str


@dataclass(frozen=True)
class PanelVM:
    """`/hsr 面板` 面板总览图视图模型。"""

    uid: str
    nickname: str
    level: int
    world_level: int
    characters: tuple[PanelRow, ...]


@dataclass(frozen=True)
class AuditRow:
    """练度统计图里的单个角色格。"""

    name: str
    avatar_path: str
    level: int
    eidolon: int
    rarity: int
    path_name: str
    element_name: str
    element_color: str


@dataclass(frozen=True)
class AuditVM:
    """`/hsr 练度` 全角色练度统计图视图模型。"""

    uid: str
    nickname: str
    rows: tuple[AuditRow, ...]


@dataclass(frozen=True)
class StatRow:
    """单角色属性行：base → final。"""

    name: str
    base: str
    final: str


@dataclass(frozen=True)
class SkillRow:
    """单角色技能行。"""

    name: str
    level: int
    max_level: int
    type_label: str


@dataclass(frozen=True)
class LightConeRef:
    """角色所持光锥摘要（character_card 用）。"""

    name: str
    level: int
    rank: int
    rarity: int
    icon_path: str


@dataclass(frozen=True)
class SubAffix:
    """遗器副词条。"""

    name: str
    value: str


@dataclass(frozen=True)
class RelicVM:
    """单件遗器（含主词条与副词条）。"""

    name: str
    level: int
    rarity: int
    icon_path: str
    main_affix_name: str
    main_affix_value: str
    subs: tuple[SubAffix, ...]


@dataclass(frozen=True)
class RelicSetVM:
    """遗器套装效果行。"""

    name: str
    count: int


@dataclass(frozen=True)
class CharacterVM:
    """`/hsr 角色` 单角色详情图视图模型。"""

    name: str
    avatar_path: str
    rarity: int
    level: int
    promotion: int
    eidolon: int
    path_name: str
    element_name: str
    element_color: str
    stats: tuple[StatRow, ...]
    skills: tuple[SkillRow, ...]
    light_cone: LightConeRef
    relics: tuple[RelicVM, ...]
    relic_sets: tuple[RelicSetVM, ...]


@dataclass(frozen=True)
class LightConeSkillVM:
    """光锥技能（叠影效果）。"""

    title: str
    description: str


@dataclass(frozen=True)
class LightConeOwnerVM:
    """光锥持有者行（owners 为空 = 纯资料卡）。"""

    name: str
    level: int
    rank: int
    eidolon: int
    icon_path: str


@dataclass(frozen=True)
class LightConeVM:
    """`/hsr 光锥` 光锥资料图视图模型。"""

    name: str
    rarity: int
    path_name: str
    description: str
    skills: tuple[LightConeSkillVM, ...]
    owners: tuple[LightConeOwnerVM, ...]


def placeholder_icon(size: int, cache_dir: Path | None = None) -> str:
    """生成灰色圆角占位 PNG，返回其绝对路径字符串。

    - 默认写入系统临时目录 ``demiaoge_placeholders/``，同尺寸幂等复用。
    - 任何异常（如无 Pillow）返回空串，由模板降级为占位色块 div，绝不报错。
    """
    try:
        from PIL import Image, ImageDraw

        target_dir = Path(cache_dir) if cache_dir else Path(tempfile.gettempdir()) / "demiaoge_placeholders"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"placeholder_{size}.png"
        if not target.exists():
            edge = max(2, int(size) // 6)
            image = Image.new("RGBA", (int(size), int(size)), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle(
                [0, 0, int(size) - 1, int(size) - 1],
                radius=edge,
                fill=(64, 74, 104, 255),
                outline=(120, 140, 190, 255),
                width=2,
            )
            image.save(target, "PNG")
        return str(target.resolve())
    except Exception:
        return ""


@dataclass(frozen=True)
class ExpeditionVM:
    """实时便签·委托行（status: Finished/Ongoing/Started）。"""
    name: str
    status_text: str      # 固定中文："已完成" / "剩余 HH:MM:SS"
    finished: bool


@dataclass(frozen=True)
class NoteVM:
    """实时便签视图模型（/hsr 体力）：仅本人扫码凭据可查（W7 防串号）。"""
    uid: str
    current_stamina: int
    max_stamina: int
    recover_seconds: int          # 距满恢复秒数（已满为 0）
    accepted_expedition_num: int
    total_expedition_num: int
    expeditions: tuple[ExpeditionVM, ...] = ()
    daily_train_score: int = -1   # 每日实训活跃度；上游缺失为 -1
    daily_train_max: int = -1
    weekly_rogue_count: int = -1  # 每周模拟宇宙次数；上游缺失为 -1
    weekly_rogue_max: int = -1
    background_path: str = ""     # 体力卡背景（本地素材绝对路径，可空）
