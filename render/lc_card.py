"""`/hsr 光锥` 光锥资料卡：名称/稀有度/命途/描述/技能；owners 非空时追加持有者行。"""
from __future__ import annotations

from pathlib import Path

from .adaptive import render_adaptive_to_path
from .engine import HEADLESS_VIEWPORT_CHROME, clamp_height, content_digest, sanitize_cache_key, text_lines
from .style import card, document, esc, img_tag, stars_html
from .v2_models import LightConeVM

WINDOW_WIDTH = 820
CARD_WIDTH = 760


def build_html(vm: LightConeVM) -> str:
    """LightConeVM → 完整 HTML 文本（纯函数，除幂等的占位图缓存外无副作用）。"""
    desc = f'<div class="item"><b>光锥描述</b><p>{esc(vm.description)}</p></div>'
    skills = "".join(
        f'<div class="item"><b>{esc(skill.title)}</b><p>{esc(skill.description)}</p></div>'
        for skill in vm.skills
    )
    owners_section = ""
    if vm.owners:
        rows = "".join(
            f'<div class="row">{img_tag(owner.icon_path, "avatar", 48)}'
            f'<div class="grow">'
            f'<div class="c-name">{esc(owner.name)}</div>'
            f'<div class="c-sub">Lv.{int(owner.level)} · 叠影 {int(owner.rank)} · E{int(owner.eidolon)}</div>'
            f"</div></div>"
            for owner in vm.owners
        )
        owners_section = f'<div class="title">持有者</div>{rows}'
    head = (
        f'<div class="name">{esc(vm.name)}{stars_html(vm.rarity)}</div>'
        f'<div class="sub"><span class="badge">命途 · {esc(vm.path_name)}</span>'
        f'<span class="badge">稀有度 {int(vm.rarity)}</span></div>'
    )
    body = f'{desc}<div class="title">技能 / 叠影效果</div>{skills}{owners_section}'
    return document(card(head, body, CARD_WIDTH, foot="德谬歌 · 光锥资料"))


def _height(vm: LightConeVM) -> int:
    """页面边距 + 头部 + 描述/技能逐条按显示宽度换行估算 + 持有者行高，夹在 [240, 4000]。"""
    height = 36 + 110 + 40 + 10
    height += (text_lines(vm.name, 25) - 1) * 40
    height += 65 + text_lines(vm.description, 52) * 22
    height += 46
    for skill in vm.skills:
        height += 65 + text_lines(skill.description, 52) * 22
    if vm.owners:
        height += 46 + len(vm.owners) * 84
    return clamp_height(height + HEADLESS_VIEWPORT_CHROME)


def render_to_path(vm: LightConeVM, cache_dir: Path) -> Path:
    """渲染并返回 PNG 文件路径（内容哈希缓存键：带/不带持有者不再共用一张旧图）。"""
    html = build_html(vm)
    key = sanitize_cache_key(f"lc_{vm.name}_{content_digest(html)}")
    render_adaptive_to_path(html, key, cache_dir, width=WINDOW_WIDTH, estimated_height=_height(vm))
    return Path(cache_dir) / f"{key}.png"


def render(vm: LightConeVM, cache_dir: Path) -> bytes:
    """渲染光锥资料 PNG（同步阻塞；异步调用方自行 to_thread）。"""
    return render_to_path(vm, cache_dir).read_bytes()
