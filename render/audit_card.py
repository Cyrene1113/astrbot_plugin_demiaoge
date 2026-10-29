"""`/hsr 练度` 全角色练度统计卡：网格布局（头像+名字+Lv+E，5星金边 4星紫边）。

排序在 build_html 内固定实现（等级降序 → E 降序 → 稀有度降序），机械可复现。
"""
from __future__ import annotations

from pathlib import Path

from .adaptive import render_adaptive_to_path
from .engine import HEADLESS_VIEWPORT_CHROME, clamp_height, content_digest, sanitize_cache_key, text_lines
from .style import card, document, element_dot, element_icon_inline, esc, img_tag, rarity_class
from .v2_models import AuditVM

WINDOW_WIDTH = 820
CARD_WIDTH = 760
PER_ROW = 4


def build_html(vm: AuditVM) -> str:
    """AuditVM → 完整 HTML 文本；网格排序固定为 level↓, eidolon↓, rarity↓。"""
    ordered = sorted(vm.rows, key=lambda row: (-int(row.level), -int(row.eidolon), -int(row.rarity)))
    cells = []
    for row in ordered:
        avatar = img_tag(row.avatar_path, f"avatar avatar-{rarity_class(row.rarity)}", 56)
        cells.append(
            f'<div class="cell cell-{rarity_class(row.rarity)}">{avatar}'
            f'<div class="cell-name">{element_icon_inline(row.element_name, row.element_color)}{esc(row.name)}</div>'
            f'<div class="cell-sub">Lv.{int(row.level)} · E{int(row.eidolon)} · {esc(row.path_name)}</div>'
            f"</div>"
        )
    head = (
        f'<div class="name">{esc(vm.nickname)}</div>'
        f'<div class="sub"><span class="badge">UID {esc(vm.uid)}</span>'
        f'<span class="badge">已收录角色 {len(vm.rows)}</span>'
        f'<span class="badge">按 等级 → 星魂 → 稀有度 排序</span></div>'
    )
    body = f'<div class="title">练度统计</div><div class="grid">{"".join(cells)}</div>'
    return document(card(head, body, CARD_WIDTH, foot="德谬歌 · 练度统计"))


def _height(vm: AuditVM) -> int:
    """页面边距 + 头部 + 每 4 格一行（格高 + 名字换行余量）+ 页脚，夹在 [240, 4000]。"""
    height = 36 + 135 + 46 + 40 + 20
    height += (text_lines(vm.nickname, 25) - 1) * 40
    for start in range(0, len(vm.rows), PER_ROW):
        chunk = vm.rows[start:start + PER_ROW]
        name_lines = max(text_lines(row.name, 11) for row in chunk)
        height += 137 + (name_lines - 1) * 19
    return clamp_height(height + HEADLESS_VIEWPORT_CHROME)


def render_to_path(vm: AuditVM, cache_dir: Path) -> Path:
    """渲染并返回 PNG 文件路径（内容哈希缓存键：数据一变即自动重渲染）。"""
    html = build_html(vm)
    key = sanitize_cache_key(f"audit_{vm.uid}_{content_digest(html)}")
    render_adaptive_to_path(html, key, cache_dir, width=WINDOW_WIDTH, estimated_height=_height(vm))
    return Path(cache_dir) / f"{key}.png"


def render(vm: AuditVM, cache_dir: Path) -> bytes:
    """渲染练度统计 PNG（同步阻塞；异步调用方自行 to_thread）。"""
    return render_to_path(vm, cache_dir).read_bytes()
