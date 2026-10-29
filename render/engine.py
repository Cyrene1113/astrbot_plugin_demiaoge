"""Edge 无头截图渲染引擎。

从 html_card.py 平移抽取（v0.4 W1-B）：临时 HTML → Edge 无头截图 → 临时 PNG 原子替换缓存。
注意：必须保持「临时文件 + shot.replace(target) 原子替换」写法，绝不回退旧版直接覆盖的写法
（旧版对已存在目标文件覆盖不生效，见 CODE_MAP.md 坑点 1）。

高度自适应（W6）：页面末尾注入洋红哨兵块，截图后自底向上像素扫描定位哨兵，
把哨兵以下的无头窗口余量/铬带整体裁掉——成图与内容实际高度一致，既不裁切
（估算过矮时自动以 2 倍高度重试一次）也不留黑边。估算值只决定首次窗口大小，
不再影响最终成图高度。

本模块为同步阻塞实现，异步调用方自行 `asyncio.to_thread` 包裹。
"""
from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import tempfile
import time
from pathlib import Path

try:  # 裁剪依赖 Pillow；缺失时跳过裁剪（回退整窗截图，不阻塞主流程）
    from PIL import Image
except ImportError:  # pragma: no cover - 由运行环境决定
    Image = None  # type: ignore[assignment]

LOGGER = logging.getLogger("demiaoge.render")

EDGE_FLAGS = (
    "--headless=new",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",
    "--hide-scrollbars",
    "--no-first-run",
    "--no-default-browser-check",
    "--run-all-compositor-stages-before-draw",
    "--force-device-scale-factor=1",
)

# 实测（标尺页，Edge --headless=new）：PNG 高 = --window-size 高，但实际排版视口
# 只有 window_height - 94（窗口边框/标题栏在无头模式下仍被计入 window-size）。
# 调用方若直接把内容高度当 window 高，底部（通常是页脚）会被裁掉约 94px。
# 引擎为兼容旧 html_card 行为不擅自加偏移；新卡片应传 estimated_height = 内容高 + 本常量。
HEADLESS_VIEWPORT_CHROME = 100  # 实测 94，留 6px 余量


def find_edge() -> str:
    """探测 Microsoft Edge 可执行文件：环境变量 DEMIAOGE_EDGE → 两个常见安装路径。"""
    candidates = [
        os.getenv("DEMIAOGE_EDGE"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    return next((path for path in candidates if path and Path(path).exists()), "")


def wrapped_lines(text: str, chars_per_line: int) -> int:
    """按中文字符宽度估算浏览器换行行数，显式换行也会计入。"""
    return sum(max(1, (len(line) + chars_per_line - 1) // chars_per_line) for line in text.splitlines() or [""])


def text_lines(text: str, chars_per_line: float) -> int:
    """按显示宽度估算换行行数：CJK/全角字符记 1，拉丁/数字记 0.55，显式换行计入。

    比 wrapped_lines 更适合 "Lv.80 · E6" 这类中英混排文本，避免系统性高估。
    """
    lines = 0
    for line in str(text or "").splitlines() or [""]:
        width = sum(1.0 if ord(char) > 0x2E80 else 0.55 for char in line)
        lines += max(1, -(-int(width * 100) // int(chars_per_line * 100)))
    return max(1, lines)


def clamp_height(height: int, low: int = 240, high: int = 4000) -> int:
    """估算高度夹在 [240, 4000]，避免过小裁切内容或超出截图窗口上限。"""
    return max(low, min(high, int(height)))


def sanitize_cache_key(cache_key: str) -> str:
    """Windows 文件名非法字符（<>:"/\\|?*）替换为下划线，其余原样保留。"""
    key = str(cache_key or "card")
    for char in '<>:"/\\|?*':
        key = key.replace(char, "_")
    return key


def content_digest(html: str) -> str:
    """HTML 内容哈希（sha256 前 12 位）：拼入缓存键，数据一变键即变、自动重渲染。"""
    return hashlib.sha256(str(html).encode("utf-8")).hexdigest()[:12]


def render_html_to_png_path(
    html: str,
    cache_key: str,
    cache_dir: Path,
    width: int = 820,
    estimated_height: int = 900,
    edge: str | None = None,
) -> Path:
    """渲染 HTML 为 PNG 并缓存，返回 PNG 文件路径；命中缓存直接返回路径（W8：不再整图读入内存）。

    - 缓存文件：``cache_dir/{cache_key}.png``（cache_key 先经 sanitize_cache_key 清洗）。
    - 截图先写 ``{cache_key}.tmp.png``，成功后 ``replace`` 原子替换为目标文件。
    - 首次截图与缓存命中均记录 ``card rendered/cache hit`` 耗时日志（demiaoge.render）。
    - ``edge`` 为兼容入参：显式指定 Edge 路径时优先使用（html_card 旧签名保留）。
    """
    started = time.perf_counter()
    # Edge 子进程的工作目录与当前进程不同，相对路径会导致截图写盘失败——统一绝对化。
    cache_dir = Path(cache_dir).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = sanitize_cache_key(cache_key)
    target = cache_dir / f"{key}.png"
    if target.exists():
        LOGGER.info("card cache hit: %s %.3fs", key, time.perf_counter() - started)
        return target
    executable = edge or find_edge()
    if not executable:
        raise RuntimeError("未找到 Microsoft Edge，请设置 DEMIAOGE_EDGE")
    profile = cache_dir / ".edge-profile"
    with tempfile.NamedTemporaryFile("w", suffix=".html", prefix="demiaoge-", delete=False, encoding="utf-8") as stream:
        stream.write(html)
        page = Path(stream.name)
    shot = target.with_name(f"{target.stem}.tmp.png")
    try:
        command = [
            executable,
            *EDGE_FLAGS,
            f"--window-size={width},{estimated_height}",
            f"--user-data-dir={profile}",
            f"--screenshot={shot}",
            page.as_uri(),
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if result.returncode or not shot.exists():
            raise RuntimeError(f"Edge 截图失败: {result.stderr[-300:]}")
        shot.replace(target)
        LOGGER.info("card rendered: %s %.3fs", key, time.perf_counter() - started)
        return target
    finally:
        page.unlink(missing_ok=True)
        shot.unlink(missing_ok=True)


def render_html_to_png(
    html: str,
    cache_key: str,
    cache_dir: Path,
    width: int = 820,
    estimated_height: int = 900,
    edge: str | None = None,
) -> bytes:
    """渲染 HTML 为 PNG 并缓存，返回 PNG bytes（``render_html_to_png_path`` 的兼容封装）。"""
    return render_html_to_png_path(
        html, cache_key, cache_dir, width=width,
        estimated_height=estimated_height, edge=edge,
    ).read_bytes()
