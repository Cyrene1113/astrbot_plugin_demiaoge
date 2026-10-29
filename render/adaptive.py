"""高度自适应渲染包装（W6）：哨兵注入 + 像素扫描裁剪。

问题：Edge ``--headless=new`` 下 PNG 高 = 窗口高，但排版视口只有窗口高 − 94px，
按估算高度直出会留下底部黑边，估算过矮又会截断内容。

方案：渲染前在 ``</body>`` 前注入 3px 全宽洋红哨兵块（卡片调色板不会出现），
截图后自底向上扫描像素定位哨兵，把哨兵以下的无头窗口余量/铬带整体裁掉——
成图与内容实际高度一致，既不留黑边也不截断（估算过矮自动以 2 倍高度重试一次，
仍失败回退整窗截图）。估算值只决定首次窗口大小，不影响最终成图高度。

纯 PIL 像素操作，无命令执行；Pillow 缺失时跳过裁剪与重试（行为与 v0.4.0 一致）。
缓存文件即裁剪后成品：二次查询走引擎缓存命中，不再重复裁剪。
W8：新增 ``render_adaptive_to_path``——缓存命中直接返回路径，不整图读入内存；
bytes 版保留为兼容封装。
"""
from __future__ import annotations

import logging
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - 由运行环境决定
    Image = None  # type: ignore[assignment]

from .engine import (
    HEADLESS_VIEWPORT_CHROME,
    clamp_height,
    render_html_to_png_path,
    sanitize_cache_key,
)

LOGGER = logging.getLogger("demiaoge.render")

SENTINEL_COLOR = (255, 0, 255)  # 洋红；要求整行 ≥50% 像素命中，防止内容色误判
SENTINEL_HTML = '<div style="height:3px;width:100%;background:#ff00ff"></div>'
MIN_CROP_HEIGHT = 240


def _inject_sentinel(html: str) -> str:
    """在页面末尾（</body> 前）注入哨兵块；无闭合标签时补齐后注入。"""
    normalized = html if "</body>" in html else html + "</body></html>"
    return normalized.replace("</body>", SENTINEL_HTML + "</body>")


def _crop_to_sentinel(png_path: Path) -> bool:
    """自底向上定位哨兵块并就地裁剪 PNG；找到并裁剪返回 True。"""
    if Image is None:
        return False
    with Image.open(png_path) as img:
        rgb = img.convert("RGB")
        width, height = rgb.size
        center_x = width // 2
        cut = None
        for y in range(height - 1, -1, -1):
            if rgb.getpixel((center_x, y)) != SENTINEL_COLOR:
                continue
            sample = [rgb.getpixel((x, y)) for x in range(1, width, max(1, width // 40))]
            if sum(1 for pixel in sample if pixel == SENTINEL_COLOR) >= len(sample) * 0.5:
                cut = y
                break
        if cut is None or cut < MIN_CROP_HEIGHT:  # 裁得过小视为异常，保留原图
            return False
        # 裁到哨兵块的顶部行（自底向上首行是块的最后一行，需上溯整块，
        # 否则残留 1-2px 洋红边）。crop 的 lower 边界为排他，故正好切在块顶。
        while cut > 0 and rgb.getpixel((center_x, cut - 1)) == SENTINEL_COLOR:
            cut -= 1
        rgb.crop((0, 0, width, cut)).save(png_path, format="PNG")
        LOGGER.info("card cropped: %d->%d", height, cut)
        return True


def render_adaptive_to_path(
    html: str,
    cache_key: str,
    cache_dir: Path,
    width: int = 820,
    estimated_height: int = 900,
    edge: str | None = None,
) -> Path:
    """渲染 HTML 为 PNG 并裁剪到内容实际高度，返回 PNG 文件路径；缓存语义与引擎一致。

    - 缓存键沿用 sanitize 后的 ``cache_key``（调用方已拼入内容哈希）。
    - 首窗 = 估算高 + 铬带余量；哨兵不可见（估算过矮）→ 2 倍高度重试一次。
    - Pillow 缺失时直接走引擎原行为（不裁剪、不重试）。
    """
    cache_dir = Path(cache_dir).resolve()  # 与引擎一致：Edge 子进程 CWD 不同，须绝对路径
    key = sanitize_cache_key(cache_key)
    target = cache_dir / f"{key}.png"
    if target.exists():
        # 缓存文件即成品（首次渲染时已裁剪）：直接命中，避免把"已裁剪无哨兵"
        # 误判为"估算过矮"而删缓存重渲染。
        return target
    page_html = _inject_sentinel(html)
    if Image is None:  # pragma: no cover - 由运行环境决定
        return render_html_to_png_path(page_html, key, cache_dir, width=width,
                                       estimated_height=estimated_height, edge=edge)
    first_window = clamp_height(estimated_height + HEADLESS_VIEWPORT_CHROME)
    windows = (first_window, min(4000, first_window * 2))
    cropped = False
    for index, window in enumerate(windows):
        if index > 0:
            target.unlink(missing_ok=True)  # 仅重试前清掉上一轮整窗截图
        render_html_to_png_path(page_html, key, cache_dir, width=width,
                                estimated_height=window, edge=edge)
        cropped = _crop_to_sentinel(target)
        if cropped or index + 1 == len(windows):
            break
        LOGGER.info("sentinel missing at window=%d, retry at %d", window, windows[index + 1])
    if not cropped:
        LOGGER.info("card adaptive fallback (uncropped): %s", key)
    return target


def render_adaptive(
    html: str,
    cache_key: str,
    cache_dir: Path,
    width: int = 820,
    estimated_height: int = 900,
    edge: str | None = None,
) -> bytes:
    """渲染 HTML 为 PNG 并裁剪，返回 PNG bytes（``render_adaptive_to_path`` 的兼容封装）。"""
    return render_adaptive_to_path(
        html, cache_key, cache_dir, width=width,
        estimated_height=estimated_height, edge=edge,
    ).read_bytes()
