"""`/hsr 角色` 单角色详情卡：头像徽章 + 属性表 + 技能条 + 光锥条 + 遗器网格。

遗器最多展示 6 件（含主/副词条），超出折叠为 "+n" 色块。
"""
from __future__ import annotations

from pathlib import Path

from .adaptive import render_adaptive_to_path
from .engine import HEADLESS_VIEWPORT_CHROME, clamp_height, content_digest, sanitize_cache_key, text_lines
from .style import card, document, element_dot, esc, img_tag, rarity_class, stars, stars_html
from .v2_models import CharacterVM

WINDOW_WIDTH = 900
CARD_WIDTH = 840
RELIC_SHOWN = 6
RELICS_PER_ROW = 3


def build_html(vm: CharacterVM) -> str:
    """CharacterVM → 完整 HTML 文本（纯函数，除幂等的占位图缓存外无副作用）。"""
    stat_rows = "".join(
        f"<tr><td>{esc(stat.name)}</td>"
        f'<td class="stat-base">{esc(stat.base)}</td>'
        f'<td class="stat-final">{esc(stat.final)}</td></tr>'
        for stat in vm.stats
    )
    skills = []
    for skill in vm.skills:
        max_level = int(skill.max_level)
        percent = 100.0 if max_level <= 0 else min(100.0, int(skill.level) / max_level * 100.0)
        skills.append(
            f'<div class="skill"><span class="skill-type">{esc(skill.type_label)}</span>'
            f'<span class="skill-name">{esc(skill.name)}</span>'
            f'<span class="bar"><i style="width:{round(percent, 1)}%"></i></span>'
            f'<span class="skill-lv">Lv.{int(skill.level)}/{max_level}</span></div>'
        )
    light_cone = vm.light_cone
    lc_strip = (
        f'<div class="lc-strip">{img_tag(light_cone.icon_path, "avatar", 48)}'
        f'<div class="grow">'
        f'<div class="c-name">{esc(light_cone.name)}{stars_html(light_cone.rarity)}</div>'
        f'<div class="c-sub">Lv.{int(light_cone.level)} · 叠影 {int(light_cone.rank)}</div>'
        f"</div></div>"
    )
    shown = vm.relics[:RELIC_SHOWN]
    folded = len(vm.relics) - len(shown)
    relic_cards = []
    for relic in shown:
        subs = "".join(f'<div class="relic-sub">{esc(sub.name)} +{esc(sub.value)}</div>' for sub in relic.subs)
        relic_cards.append(
            f'<div class="relic relic-{rarity_class(relic.rarity)}">'
            f'<div class="relic-head">{img_tag(relic.icon_path, "avatar", 40)}'
            f"<div style=\"min-width:0\"><div class=\"relic-name\">{esc(relic.name)}</div>"
            f'<div class="relic-lv">Lv.{int(relic.level)} · {stars(relic.rarity)}</div></div></div>'
            f'<div class="relic-main">{esc(relic.main_affix_name)} <b>{esc(relic.main_affix_value)}</b></div>'
            f"{subs}</div>"
        )
    fold_chip = f'<div style="margin-top:10px"><span class="fold">+{folded} 件</span></div>' if folded > 0 else ""
    sets = "".join(f'<span class="chip">{esc(item.name)} ×{int(item.count)}</span>' for item in vm.relic_sets)
    head = (
        '<div style="display:flex;align-items:center;gap:14px">'
        + img_tag(vm.avatar_path, f"avatar avatar-{rarity_class(vm.rarity)}", 72)
        + '<div style="min-width:0">'
        + f'<div class="name">{esc(vm.name)}{stars_html(vm.rarity)}</div>'
        + '<div class="sub">'
        + element_dot(vm.element_name, vm.element_color)
        + f'<span class="badge">{esc(vm.path_name)}</span>'
        + f'<span class="badge">Lv.{int(vm.level)}</span>'
        + f'<span class="badge">E{int(vm.eidolon)}</span>'
        + f'<span class="badge">晋阶 {int(vm.promotion)}</span></div></div></div>'
    )
    body = (
        f'<div class="title">属性（基础 → 最终）</div><table class="stats">{stat_rows}</table>'
        f'<div class="title">技能</div>{"".join(skills)}'
        f'<div class="title">光锥</div>{lc_strip}'
        f'<div class="title">遗器</div><div class="grid">{"".join(relic_cards)}</div>{fold_chip}'
        + (f'<div class="title">套装</div><div>{sets}</div>' if sets else "")
    )
    return document(card(head, body, CARD_WIDTH, foot="德谬歌 · 角色详情"))


def _height(vm: CharacterVM) -> int:
    """分区累加：头部/属性/技能（换行余量）/光锥/遗器（按行取最高格）/套装，夹在 [240, 4000]。"""
    height = 36 + 110 + 40 + 10
    height += (text_lines(vm.name, 25) - 1) * 40
    height += 46 + len(vm.stats) * 30
    height += 46 + sum(32 + (text_lines(skill.name, 13) - 1) * 20 for skill in vm.skills)
    height += 46 + 84
    shown = vm.relics[:RELIC_SHOWN]
    for start in range(0, len(shown), RELICS_PER_ROW):
        chunk = shown[start:start + RELICS_PER_ROW]
        max_subs = max((len(relic.subs) for relic in chunk), default=0)
        name_lines = max((text_lines(relic.name, 14) for relic in chunk), default=1)
        height += 10 + 20 + max(40, 17 + 18 * name_lines) + 28 + 19 * max_subs
    if len(vm.relics) > RELIC_SHOWN:
        height += 50
    if vm.relic_sets:
        height += 46 + -(-len(vm.relic_sets) // 5) * 28
    return clamp_height(height + HEADLESS_VIEWPORT_CHROME)


def render_to_path(vm: CharacterVM, cache_dir: Path) -> Path:
    """渲染并返回 PNG 文件路径（内容哈希缓存键：不同玩家同名角色不再串缓存）。"""
    html = build_html(vm)
    key = sanitize_cache_key(f"character_{vm.name}_{content_digest(html)}")
    render_adaptive_to_path(html, key, cache_dir, width=WINDOW_WIDTH, estimated_height=_height(vm))
    return Path(cache_dir) / f"{key}.png"


def render(vm: CharacterVM, cache_dir: Path) -> bytes:
    """渲染单角色详情 PNG（同步阻塞；异步调用方自行 to_thread）。"""
    return render_to_path(vm, cache_dir).read_bytes()
