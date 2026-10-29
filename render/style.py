"""v0.4 新卡片公共样式与拼装助手（深蓝风，延续 html_card.py 设计语言）。

只提供纯字符串拼装：``document`` 输出完整 HTML 文档骨架，
``esc``/``stars``/``img_tag``/``element_dot`` 是各卡片模板共用的零依赖小助手。

W7 美化：本地素材（data/assets，截取自 gsuid_core StarRailUID，GPL-3.0）——
官方风格字体 ``starrail_origin.ttf``、七系元素图标、星空页面底图。素材缺失时
全部自动回退为原深蓝纯色风格，渲染路径不因缺素材而失败。
"""
from __future__ import annotations

import html
import os
from pathlib import Path
from urllib.parse import quote

from .v2_models import placeholder_icon

ASSETS_DIR = Path(__file__).resolve().parents[1] / "data" / "assets"
_FONT_PATH = ASSETS_DIR / "fonts" / "starrail_origin.ttf"
_PAGE_BG = ASSETS_DIR / "cards" / "bg.png"

# 元素中文名 → 本地元素图标文件（StarRailUID 的 IconAttribute*.png）
_ELEMENT_ICONS = {
    "物理": "IconAttributePhysical.png",
    "火": "IconAttributeFire.png",
    "冰": "IconAttributeIce.png",
    "雷": "IconAttributeThunder.png",
    "风": "IconAttributeWind.png",
    "量子": "IconAttributeQuantum.png",
    "虚数": "IconAttributeImaginary.png",
}


def _file_uri(path: Path) -> str:
    """本地素材 → file:// URI（Windows 盘符 + 中文路径需 quote）。"""
    return "file:///" + quote(str(path).replace("\\", "/"))


def asset_css() -> str:
    """字体与页面底图注入（素材缺失时返回空串 → 自动回退纯色风格）。"""
    parts = []
    if _FONT_PATH.is_file():
        parts.append(f"@font-face{{font-family:'SRStarRail';src:url('{_file_uri(_FONT_PATH)}')}}")
    if _PAGE_BG.is_file():
        parts.append(
            "html,body{background:#0c1122}"
            f".page{{background:linear-gradient(rgba(10,14,28,.78),rgba(10,14,28,.9)),"
            f"url('{_file_uri(_PAGE_BG)}') center/cover no-repeat}}")
    return "".join(parts)


def page_bg_css(bg_path: Path, overlay: str = "rgba(10,14,28,.62)") -> str:
    """单卡页面背景覆盖（拼在 BASE_CSS/asset_css 之后即可生效）；素材缺失返回空串。

    供各卡片按类型/稀有度替换整页背景（如角色卡按星级换卡底）；遮罩保证前景可读。
    """
    if not bg_path or not bg_path.is_file():
        return ""
    return (f".page{{background:linear-gradient({overlay},{overlay}),"
            f"url('{_file_uri(bg_path)}') center/cover no-repeat}}")


def element_icon_path(element_name: str) -> str:
    """元素名 → 本地图标绝对路径；未收录返回空串（调用方回退彩色圆点）。"""
    filename = _ELEMENT_ICONS.get(str(element_name or "").strip())
    if not filename:
        return ""
    target = ASSETS_DIR / "icons" / "elements" / filename
    return str(target) if target.is_file() else ""


# 深蓝主题公共样式（调色板与 html_card.py 一致：#10162a/#1a2340/#506aa0/#f5c542）。
BASE_CSS = """*{box-sizing:border-box}html,body{margin:0;padding:0;background:#10162a;color:#e8ecf8;font-family:'SRStarRail','Microsoft YaHei','PingFang SC',sans-serif}
.page{padding:18px;background:linear-gradient(180deg,#10162a,#182342)}
.card{margin:0 auto;border-radius:16px;overflow:hidden;background:linear-gradient(160deg,#1a2340,#12182b);border:1px solid #506aa0;box-shadow:0 8px 32px #0007}
.head{padding:20px 26px 14px;background:linear-gradient(135deg,#506ec855,#1e28501a);border-bottom:1px solid #8caaf033}
.name{font-size:28px;font-weight:bold;overflow-wrap:anywhere}
.stars{margin-left:12px;font-size:19px}
.stars-r5{color:#f5c542}
.stars-r4{color:#b37ff3}
.sub{margin-top:8px;color:#a9b6d8;font-size:14px;overflow-wrap:anywhere}
.chip{display:inline-block;font-size:13px;padding:4px 11px;margin:0 7px 4px 0;border-radius:99px;background:#5a78c044;color:#c9d6f5}
.badge{display:inline-block;font-size:12px;padding:3px 10px;border-radius:99px;background:#28345a99;border:1px solid #8caaf044;color:#c9d6f5;margin:0 8px 6px 0;vertical-align:middle}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px;vertical-align:-1px}
.el-icon{vertical-align:-3px;margin-right:5px}
.body{padding:16px 26px 20px}
.title{font-size:16px;font-weight:bold;color:#8fb0f0;border-left:4px solid #8fb0f0;padding-left:9px;margin:14px 0 10px}
.foot{padding:11px 26px;color:#7484a8;border-top:1px solid #8caaf022;font-size:12px}
.avatar{display:block;object-fit:cover;background:#28345a;border-radius:10px}
.avatar-r5{border:2px solid #f5c542}
.avatar-r4{border:2px solid #b37ff3}
.row{display:flex;align-items:center;background:#28345a73;border-left:3px solid #5f7fd0;border-radius:10px;padding:8px 14px;margin:8px 0}
.grow{flex:1;min-width:0;margin:0 12px}
.c-name{font-size:16px;font-weight:bold;color:#dfe8ff;overflow-wrap:anywhere}
.c-sub{font-size:12px;color:#a9b6d8;margin-top:4px;overflow-wrap:anywhere}
.c-lc{font-size:13px;color:#e8d9a8;margin-top:4px;overflow-wrap:anywhere}
.grid{display:flex;flex-wrap:wrap;gap:10px}
.cell{width:164px;background:#28345a73;border-radius:10px;padding:10px 8px;text-align:center}
.cell-r5{border:1px solid #f5c542}
.cell-r4{border:1px solid #b37ff3}
.cell-name{font-size:13px;font-weight:bold;color:#dfe8ff;margin-top:6px;overflow-wrap:anywhere}
.cell-sub{font-size:12px;color:#a9b6d8;margin-top:3px}
.stats{width:100%;border-collapse:collapse;font-size:14px}
.stats td{padding:5px 8px;border-bottom:1px solid #8caaf01f;color:#c3cce2;overflow-wrap:anywhere}
.stats .stat-final{text-align:right;color:#e8ecf8;font-weight:bold}
.stats .stat-base{color:#8b97b5}
.skill{display:flex;align-items:center;margin:7px 0}
.skill-type{width:64px;font-size:12px;color:#8fb0f0}
.skill-name{width:170px;font-size:13px;color:#dfe8ff;font-weight:bold;margin-right:10px;overflow-wrap:anywhere}
.bar{flex:1;height:10px;background:#28345a;border-radius:99px;overflow:hidden}
.bar i{display:block;height:100%;background:linear-gradient(90deg,#5f7fd0,#8fb0f0)}
.skill-lv{width:76px;text-align:right;font-size:13px;color:#a9b6d8}
.lc-strip{display:flex;align-items:center;background:#28345a73;border-left:3px solid #f5c542;border-radius:10px;padding:10px 14px}
.relic{width:252px;background:#28345a73;border:1px solid #8caaf02e;border-radius:10px;padding:10px}
.relic-r5{border-color:#f5c54266}
.relic-r4{border-color:#b37ff366}
.relic-head{display:flex;align-items:center;gap:9px}
.relic-name{font-size:13px;font-weight:bold;color:#dfe8ff;overflow-wrap:anywhere}
.relic-lv{font-size:12px;color:#a9b6d8;margin-top:2px}
.relic-main{font-size:13px;color:#f0e6c8;margin-top:8px;overflow-wrap:anywhere}
.relic-main b{color:#f5c542}
.relic-sub{font-size:12px;color:#a9b6d8;margin-top:2px;overflow-wrap:anywhere}
.fold{display:inline-block;padding:10px 18px;border-radius:10px;background:#28345a73;color:#8fb0f0;font-size:14px;border:1px dashed #5f7fd0}
.item{background:#28345a73;border-left:3px solid #5f7fd0;border-radius:9px;padding:11px 14px;margin:8px 0}
.item b{color:#dfe8ff;display:block;overflow-wrap:anywhere}
.item p{font-size:13px;line-height:1.7;color:#a9b6d8;margin:5px 0 0;white-space:pre-wrap;overflow-wrap:anywhere}"""


def esc(value: object) -> str:
    """html.escape 一切动态文本，杜绝注入。"""
    return html.escape(str(value or ""))


def stars(rarity: int) -> str:
    """稀有度星星文本（0-5 夹取）。"""
    return "★" * max(0, min(int(rarity), 5))


def stars_html(rarity: int) -> str:
    """带 5 星金 / 4 星紫着色的星星片段。"""
    level = "stars-r5" if int(rarity) >= 5 else "stars-r4"
    return f'<span class="stars {level}">{stars(rarity)}</span>'


def element_dot(element_name: str, element_color: str) -> str:
    """元素徽章：优先用本地元素图标（官方美术），无素材时回退彩色圆点。

    两种形态都经 esc 转义，杜绝属性逃逸。
    """
    name = esc(element_name)
    icon = element_icon_path(element_name)
    if icon:
        src = esc(_file_uri(Path(icon)))
        return (f'<span class="badge"><img class="el-icon" src="{src}" '
                f'width="16" height="16" alt="">{name}</span>')
    if element_color:
        return f'<span class="badge"><span class="dot" style="background:{esc(element_color)}"></span>{name}</span>'
    return f'<span class="badge">{name}</span>'


def element_icon_inline(element_name: str, element_color: str = "", size: int = 14) -> str:
    """紧凑元素标记（练度卡网格用）：本地图标优先，回退彩色圆点。"""
    icon = element_icon_path(element_name)
    if icon:
        src = esc(_file_uri(Path(icon)))
        return (f'<img src="{src}" width="{int(size)}" height="{int(size)}" '
                f'style="vertical-align:-2px;margin-right:4px" alt="">')
    if element_color:
        return f'<span class="dot" style="background:{esc(element_color)}"></span>'
    return ""


def img_tag(path: str, css_class: str, size: int) -> str:
    """图标引用：本地路径存在时用 ``Path.as_uri()`` 引用；缺失时尝试 PIL 占位图；
    占位图也不可用时降级为占位色块 div，任何情况都不报错。"""
    src = ""
    if path and os.path.exists(path):
        src = Path(path).as_uri()
    else:
        placeholder = placeholder_icon(size)
        if placeholder:
            src = Path(placeholder).as_uri()
    if src:
        return f'<img class="{esc(css_class)}" src="{esc(src)}" width="{int(size)}" height="{int(size)}" alt="">'
    return f'<div class="{esc(css_class)}" style="width:{int(size)}px;height:{int(size)}px"></div>'


def rarity_class(rarity: int) -> str:
    """5 星金边 / 4 星紫边的 CSS 类名。"""
    return "r5" if int(rarity) >= 5 else "r4"


def document(body: str, extra_css: str = "") -> str:
    """完整 HTML 文档骨架（深蓝页面 + 本地素材字体/星空底图 + 公共样式）。

    CSS 拼接顺序即优先级（W8 修复）：BASE_CSS（纯色回退）→ asset_css()（素材背景/
    字体覆盖纯色）→ extra_css（单卡覆盖最高）。此前 asset_css 在前，.page 的星空
    底图被 BASE_CSS 同名规则覆盖——美化从未真正生效。
    """
    css = BASE_CSS + asset_css() + extra_css
    return f'<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><style>{css}</style></head><body><div class="page">{body}</div></body></html>'


def card(head: str, body: str, width: int, foot: str = "德谬歌 · 崩坏：星穹铁道查询") -> str:
    """单张卡片骨架：head + body + foot，宽度内联指定（页面 18px 边距 + 卡片 <= 窗口宽）。"""
    return (
        f'<main class="card" style="width:{int(width)}px">'
        f'<header class="head">{head}</header>'
        f'<section class="body">{body}</section>'
        f'<footer class="foot">{foot}</footer>'
        f"</main>"
    )
