"""WikiEntry 的自适应 HTML 卡片（渲染执行已下沉到 render/engine.py，本模块只负责模板）。"""
from __future__ import annotations

import html
from pathlib import Path

from ..domain.wiki_models import WikiEntry
from .adaptive import render_adaptive_to_path
from .engine import find_edge as _find_edge
from .engine import sanitize_cache_key
from .engine import wrapped_lines as _wrapped_lines

CSS = """*{box-sizing:border-box}html,body{margin:0;padding:0;background:#10162a;color:#e8ecf8;font-family:'Microsoft YaHei','PingFang SC',sans-serif}.page{padding:18px;background:linear-gradient(180deg,#10162a,#182342)}.card{width:760px;margin:0 auto;border-radius:16px;overflow:hidden;background:linear-gradient(160deg,#1a2340,#12182b);border:1px solid #506aa0;box-shadow:0 8px 32px #0007}.head{padding:22px 26px 16px;background:linear-gradient(135deg,#506ec855,#1e28501a);border-bottom:1px solid #8caaf033}.name{font-size:30px;font-weight:bold}.stars{color:#f5c542;margin-left:14px}.tags{margin-top:10px}.tag{display:inline-block;font-size:13px;padding:4px 11px;margin:0 7px 4px 0;border-radius:99px;background:#5a78c044;color:#c9d6f5}.body{padding:18px 26px 20px}.desc{font-size:15px;line-height:1.7;color:#c3cce2;margin:0 0 16px;white-space:pre-wrap;overflow-wrap:anywhere}.title{font-size:16px;font-weight:bold;color:#8fb0f0;border-left:4px solid #8fb0f0;padding-left:9px;margin:16px 0 10px}.item{background:#28345a73;border-left:3px solid #5f7fd0;border-radius:9px;padding:11px 14px;margin:8px 0}.item b{color:#dfe8ff;display:block;overflow-wrap:anywhere}.item p{font-size:13px;line-height:1.7;color:#a9b6d8;margin:5px 0 0;white-space:pre-wrap;overflow-wrap:anywhere}.foot{padding:11px 26px;color:#7484a8;border-top:1px solid #8caaf022;font-size:12px}"""


def esc(value: object) -> str:
    return html.escape(str(value or ""))


# 兼容别名：旧版私有探测函数名保持可用。
_edge_path = _find_edge


def build_html(entry: WikiEntry) -> str:
    tags = "".join(f'<span class="tag">{esc(tag)}</span>' for tag in entry.tags)
    sections = []
    if entry.skills:
        items = "".join(f'<div class="item"><b>{esc(name)}</b><p>{esc(description)}</p></div>' for name, description in entry.skills)
        sections.append(f'<div class="title">技能 / 效果</div>{items}')
    if entry.eidolons:
        items = "".join(f'<div class="item"><b>{esc(name)}</b><p>{esc(description)}</p></div>' for name, description in entry.eidolons)
        sections.append(f'<div class="title">星魂</div>{items}')
    rarity = "★" * entry.rarity
    return f'<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><style>{CSS}</style></head><body><div class="page"><main class="card"><header class="head"><span class="name">{esc(entry.name)}</span><span class="stars">{rarity}</span><div class="tags">{tags}</div></header><section class="body"><div class="desc">{esc(entry.description)}</div>{"".join(sections)}</section><footer class="foot">德谬歌 · 本地 Wiki 数据 {esc(entry.version)}</footer></main></div></body></html>'


def _height(entry: WikiEntry) -> int:
    """按 CSS 实际行高估算 viewport，尽量只保留 18px 页面边距。"""
    height = 18 + 22 + 36 + 16 + 18 + 20 + 18 + 20 + 11 + 18
    height += _wrapped_lines(entry.description, 64) * 25
    height += max(1, len(entry.tags) // 5 + 1) * 26
    for name, description in (*entry.skills, *entry.eidolons):
        height += 16 + 10 + 22 + _wrapped_lines(name, 64) * 18 + _wrapped_lines(description, 86) * 22 + 10
    return max(220, min(3200, height))


def render_entry_to_path(entry: WikiEntry, cache_dir: Path, edge: str | None = None) -> Path:
    """渲染并返回 PNG 文件路径（AstrBot image_result 只收路径字符串，不收 bytes）。

    wiki 条目为本地静态数据，缓存键沿用 `{类别}_{名称}`（更新数据后用 /hsr 更新缓存 清理）。
    """
    key = sanitize_cache_key(f"{entry.category}_{entry.name}")
    render_adaptive_to_path(
        build_html(entry),
        key,
        cache_dir,
        width=820,
        estimated_height=_height(entry),
        edge=edge,
    )
    return Path(cache_dir) / f"{key}.png"


def render_entry(entry: WikiEntry, cache_dir: Path, edge: str | None = None) -> bytes:
    """渲染并返回 PNG；首次截图与缓存命中耗时由 engine 统一记录。"""
    return render_entry_to_path(entry, cache_dir, edge=edge).read_bytes()
