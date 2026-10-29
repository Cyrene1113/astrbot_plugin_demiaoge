"""`/hsr 体力` 实时便签卡：开拓力 + 委托 + 每日实训/周本（数据缺失自动隐藏）。

数据仅来自本人扫码凭据（W7 防串号，见 panel_service.note_png）。
背景素材截取自 gsuid_core StarRailUID（GPL-3.0，见 data/assets/ASSETS_CREDITS.md），
缺失时回退纯色渐变。渲染走 render/adaptive.py 高度自适应裁剪。
W8：文件 URI 与字体注入复用 render/style.py 公共助手（行为不变）。
"""
from __future__ import annotations

from pathlib import Path

from .adaptive import render_adaptive_to_path
from .engine import content_digest, sanitize_cache_key
from .style import _file_uri, card, document, esc
from .v2_models import NoteVM

WINDOW_WIDTH = 820

_ASSETS = Path(__file__).resolve().parents[1] / "data" / "assets"
_NOTE_BG = _ASSETS / "cards" / "note_bg.png"
_FONT = _ASSETS / "fonts" / "starrail_origin.ttf"


def _background_css() -> str:
    """体力卡背景：本地素材存在时整页 cover + 深色遮罩保证可读性。"""
    if _NOTE_BG.is_file():
        return (f".page{{background:linear-gradient(rgba(12,17,34,.86),rgba(12,17,34,.86)),"
                f"url('{_file_uri(_NOTE_BG)}') center/cover no-repeat}}")
    return ""


def _font_face_css() -> str:
    if _FONT.is_file():
        return f"@font-face{{font-family:'SRStarRail';src:url('{_file_uri(_FONT)}')}}"
    return ""


def _seconds_to_hms(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _expedition_rows(vm: NoteVM) -> str:
    if not vm.expeditions:
        return '<div class="empty">当前没有进行中的委托</div>'
    rows = []
    for item in vm.expeditions:
        state = "done" if item.finished else ""
        rows.append(
            f'<div class="exp {state}"><span class="exp-name">{esc(item.name)}</span>'
            f'<span class="exp-status">{esc(item.status_text)}</span></div>')
    return "".join(rows)


def build_html(vm: NoteVM) -> str:
    full = vm.current_stamina >= vm.max_stamina and vm.max_stamina > 0
    ratio = 0 if vm.max_stamina <= 0 else min(100, round(vm.current_stamina * 100 / vm.max_stamina))
    if full:
        recover_text = "开拓力已满"
        bar_class = "bar-full"
    else:
        recover_text = f"距离回满 {_seconds_to_hms(vm.recover_seconds)}"
        bar_class = "bar"
    daily_section = ""
    if vm.daily_train_score >= 0:
        daily_section = (f'<div class="title">每日实训</div>'
                         f'<div class="row"><span>{esc(str(vm.daily_train_score))} / {esc(str(vm.daily_train_max))}</span></div>')
    rogue_section = ""
    if vm.weekly_rogue_count >= 0:
        rogue_section = (f'<div class="title">每周模拟宇宙</div>'
                         f'<div class="row"><span>{esc(str(vm.weekly_rogue_count))} / {esc(str(vm.weekly_rogue_max))} 次</span></div>')
    body_bg = _background_css()
    font_face = _font_face_css()
    font_stack = "'SRStarRail','Microsoft YaHei','PingFang SC',sans-serif" if font_face else "'Microsoft YaHei','PingFang SC',sans-serif"
    css = (
        "*{box-sizing:border-box}html,body{margin:0;padding:0;background:#0c1122;"
        f"color:#e8ecf8;font-family:{font_stack}}}"
        + (font_face or "")
        + body_bg
        + ".page{padding:18px}.card{width:760px;margin:0 auto;border-radius:16px;overflow:hidden;"
        "background:linear-gradient(160deg,rgba(30,40,72,.92),rgba(16,22,42,.94));"
        "border:1px solid #506aa0;box-shadow:0 8px 32px #0007}"
        ".head{padding:20px 26px 14px;background:linear-gradient(135deg,#506ec855,#1e28501a);"
        "border-bottom:1px solid #8caaf033}"
        ".head .name{font-size:26px;font-weight:bold}.head .uid{margin-left:12px;color:#8fa4cc;font-size:14px}"
        ".body{padding:18px 26px 20px}"
        ".stamina-num{font-size:40px;font-weight:bold;color:#f5c542}"
        ".stamina-num small{font-size:20px;color:#8fa4cc}"
        ".recover{margin-left:14px;color:#a9b6d8;font-size:14px}"
        f".{bar_class}{{height:14px;border-radius:99px;background:#28345a;margin:12px 0 6px;overflow:hidden}}"
        f".{bar_class}>i{{display:block;height:100%;background:linear-gradient(90deg,#f5c542,#e8a23a);border-radius:99px}}"
        ".bar-full>i{background:linear-gradient(90deg,#7ee08a,#57b96a)}"
        ".title{font-size:16px;font-weight:bold;color:#8fb0f0;border-left:4px solid #8fb0f0;"
        "padding-left:9px;margin:16px 0 10px}"
        ".exp{display:flex;justify-content:space-between;background:#28345a73;border-left:3px solid #5f7fd0;"
        "border-radius:9px;padding:10px 14px;margin:8px 0;font-size:14px}"
        ".exp.done{border-left-color:#57b96a}.exp.done .exp-status{color:#7ee08a}"
        ".exp-name{color:#dfe8ff}.exp-status{color:#a9b6d8}"
        ".row{background:#28345a73;border-radius:9px;padding:10px 14px;font-size:14px;color:#dfe8ff}"
        ".empty{color:#7484a8;font-size:13px;padding:6px 2px}"
        ".foot{padding:11px 26px;color:#7484a8;border-top:1px solid #8caaf022;font-size:12px}"
    )
    return (
        f'<!doctype html><html lang="zh-CN"><head><meta charset="UTF-8"><style>{css}</style></head>'
        f'<body><div class="page"><main class="card">'
        f'<header class="head"><span class="name">实时便签</span>'
        f'<span class="uid">UID {esc(vm.uid)}</span></header>'
        f'<section class="body">'
        f'<div><span class="stamina-num">{esc(str(vm.current_stamina))}'
        f'<small> / {esc(str(vm.max_stamina))}</small></span>'
        f'<span class="recover">{esc(recover_text)}</span></div>'
        f'<div class="{bar_class}"><i style="width:{ratio}%"></i></div>'
        f'<div class="title">委托</div>'
        f'<div class="row">接受 {esc(str(vm.accepted_expedition_num))} / {esc(str(vm.total_expedition_num))}</div>'
        f'{_expedition_rows(vm)}'
        f'{daily_section}{rogue_section}'
        f'</section>'
        f'<footer class="foot">德谬歌 · 实时便签（数据可能存在延迟，以游戏内为准）</footer>'
        f'</main></div></body></html>'
    )


def render_to_path(vm: NoteVM, cache_dir: Path) -> Path:
    """渲染并返回 PNG 文件路径（内容哈希缓存键 + 高度自适应裁剪）。"""
    html = build_html(vm)
    key = sanitize_cache_key(f"note_{vm.uid}_{content_digest(html)}")
    render_adaptive_to_path(html, key, cache_dir, width=WINDOW_WIDTH, estimated_height=620)
    return Path(cache_dir) / f"{key}.png"


def render(vm: NoteVM, cache_dir: Path) -> bytes:
    """渲染实时便签 PNG（同步阻塞；异步调用方自行 to_thread）。"""
    return render_to_path(vm, cache_dir).read_bytes()
