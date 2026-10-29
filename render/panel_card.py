"""`/hsr 面板` 面板总览卡：头部玩家信息 + 角色行列表（3-10 行自适应）。

纯字符串拼 HTML + html.escape，渲染走 render/engine.py（Edge 截图 + 原子替换缓存）。
"""
from __future__ import annotations

from pathlib import Path

from .adaptive import render_adaptive_to_path
from .engine import HEADLESS_VIEWPORT_CHROME, clamp_height, content_digest, sanitize_cache_key, text_lines
from .style import card, document, element_dot, esc, img_tag, rarity_class, stars_html
from .v2_models import PanelVM

WINDOW_WIDTH = 820
CARD_WIDTH = 760


def build_html(vm: PanelVM) -> str:
    """PanelVM → 完整 HTML 文本（纯函数，除幂等的占位图缓存外无副作用）。"""
    rows = []
    for row in vm.characters:
        lv_e = f"Lv.{int(row.level)} · E{int(row.eidolon)}"
        lc_text = f"光锥：{row.light_cone_name or '未装备'} Lv.{int(row.light_cone_level)}"
        avatar = img_tag(row.avatar_path, f"avatar avatar-{rarity_class(row.rarity)}", 56)
        lc_icon = img_tag(row.light_cone_icon, "avatar", 28)
        rows.append(
            f'<div class="row">{avatar}'
            f'<div class="grow">'
            f'<div class="c-name">{esc(row.name)}{stars_html(row.rarity)}</div>'
            f'<div class="c-sub">{element_dot(row.element_name, row.element_color)}'
            f'<span class="badge">{esc(row.path_name)}</span>'
            f'<span class="badge">{esc(lv_e)}</span></div>'
            f'<div class="c-lc" style="display:flex;align-items:center;gap:7px">{lc_icon}<span>{esc(lc_text)}</span></div>'
            f"</div></div>"
        )
    head = (
        f'<div class="name">{esc(vm.nickname)}</div>'
        f'<div class="sub"><span class="badge">UID {esc(vm.uid)}</span>'
        f'<span class="badge">开拓等级 {int(vm.level)}</span>'
        f'<span class="badge">世界等级 {int(vm.world_level)}</span>'
        f'<span class="badge">角色 {len(vm.characters)}</span></div>'
    )
    body = f'<div class="title">角色展示</div>{"".join(rows)}'
    return document(card(head, body, CARD_WIDTH, foot="德谬歌 · 面板总览"))


def _height(vm: PanelVM) -> int:
    """页面边距 + 头部 + 每行（行高 + 光锥/徽章/名字换行余量）+ 页脚，夹在 [240, 4000]。"""
    height = 36 + 135 + 46 + 40 + 20
    head_badges = f"UID {vm.uid} 开拓等级 {int(vm.level)} 世界等级 {int(vm.world_level)} 角色 {len(vm.characters)}"
    height += (text_lines(head_badges, 48) - 1) * 26
    height += (text_lines(vm.nickname, 25) - 1) * 40
    for row in vm.characters:
        lc_text = f"光锥：{row.light_cone_name or '未装备'} Lv.{int(row.light_cone_level)}"
        badge_text = f"{row.element_name} {row.path_name} Lv.{int(row.level)} · E{int(row.eidolon)}"
        height += 118
        height += (text_lines(lc_text, 40) - 1) * 20
        height += (text_lines(row.name, 30) - 1) * 22
        height += (text_lines(badge_text, 40) - 1) * 26
    return clamp_height(height + HEADLESS_VIEWPORT_CHROME)


def render_to_path(vm: PanelVM, cache_dir: Path) -> Path:
    """渲染并返回 PNG 文件路径（内容哈希缓存键：数据一变即自动重渲染）。

    缓存键 = panel_{uid}_{html哈希}：同 uid 数据变化不再命中旧图；
    高度自适应裁剪（render/adaptive.py）使成图与内容实际高度一致。
    发送图片用本路径（AstrBot image_result 只收路径字符串，不收 bytes）。
    """
    html = build_html(vm)
    key = sanitize_cache_key(f"panel_{vm.uid}_{content_digest(html)}")
    render_adaptive_to_path(html, key, cache_dir, width=WINDOW_WIDTH, estimated_height=_height(vm))
    return Path(cache_dir) / f"{key}.png"


def render(vm: PanelVM, cache_dir: Path) -> bytes:
    """渲染面板总览 PNG（同步阻塞；异步调用方自行 to_thread）。"""
    return render_to_path(vm, cache_dir).read_bytes()
