"""异步纪律守护测试：静态扫描运行时源码，防止阻塞调用混回事件循环路径。

背景：AstrBot 在单一 asyncio 事件循环上调度所有插件/消息处理，任何同步网络、
subprocess、阻塞 sleep 都会卡住整个对话进程。本项目约定：
- 网络：一律 httpx.AsyncClient（adapters/*）；
- 阻塞渲染（Edge 子进程）：收敛在 render/engine.py，调用方 asyncio.to_thread；
- 磁盘 I/O（payload 缓存 / 二维码落盘）：调用方 asyncio.to_thread；
- 等待：await asyncio.sleep，禁止 time.sleep；
- 图片发送：event.image_result 只收 URL/路径字符串，传 bytes 会 TypeError。

本测试为纯静态检查，无网络、无渲染，毫秒级完成。
运行（父目录）：python -m pytest -q astrbot_plugin_demiaoge/test_async_hygiene.py
"""
from __future__ import annotations

import re
from pathlib import Path

PLUGIN_DIR = Path(__file__).parent

# subprocess 仅允许出现在 render/engine.py（Edge 截图，同步实现，由调用方 to_thread）。
SUBPROCESS_ALLOWED_FILES = {"engine.py"}

# 维护脚本豁免：wiki_crawler.py 是维护窗口手动运行的 CLI（python -m services.wiki_crawler），
# 从不进入插件事件循环，允许用同步库；运行时命令路径的模块不豁免。
MAINTENANCE_SCRIPTS = {"wiki_crawler.py"}

# 运行时源码范围（tests / scripts 不在此列）。
RUNTIME_SUBDIRS = ("adapters", "services", "render", "domain", "storage")


def _runtime_sources() -> list[Path]:
    paths = [path for subdir in RUNTIME_SUBDIRS
             for path in sorted((PLUGIN_DIR / subdir).glob("*.py"))
             if path.name not in MAINTENANCE_SCRIPTS]
    paths.append(PLUGIN_DIR / "main.py")
    return [path for path in paths if path.exists()]


def test_no_sync_http_or_blocking_sleep_in_runtime_code() -> None:
    """同步 HTTP 库与阻塞 sleep 不得出现在任何运行时模块。"""
    banned = [
        (r"^\s*(import|from)\s+urllib\.request\b", "urllib.request（同步网络）"),
        (r"^\s*import\s+requests\b", "requests（同步网络）"),
        (r"\burlopen\(", "urlopen（同步网络）"),
        (r"\btime\.sleep\(", "time.sleep（阻塞 sleep，应 await asyncio.sleep）"),
    ]
    for path in _runtime_sources():
        text = path.read_text(encoding="utf-8")
        for pattern, label in banned:
            assert re.search(pattern, text, re.M) is None, \
                f"{path.relative_to(PLUGIN_DIR)} 含阻塞调用：{label}"


def test_subprocess_confined_to_engine() -> None:
    """subprocess 只允许在渲染引擎（engine.py）内使用。"""
    for path in _runtime_sources():
        if path.name in SUBPROCESS_ALLOWED_FILES:
            continue
        text = path.read_text(encoding="utf-8")
        assert re.search(r"\bsubprocess\.(run|Popen|check_output|check_call)\(", text) is None, \
            f"{path.relative_to(PLUGIN_DIR)} 直接使用 subprocess（阻塞），" \
            "应收敛到 render/engine.py 并由 asyncio.to_thread 调用"


def test_all_image_results_receive_path_string() -> None:
    """main.py 中每个 image_result 调用都必须传 str(...) 路径（bytes 会 TypeError）。"""
    main_text = (PLUGIN_DIR / "main.py").read_text(encoding="utf-8")
    matches = re.findall(r"image_result\(([^)]*)\)", main_text)
    assert matches, "main.py 应存在 image_result 发送点（防正则失配）"
    for arg in matches:
        assert arg.strip().startswith("str("), \
            f"image_result 参数必须是 str(路径)：image_result({arg.strip()})"


def test_blocking_io_wrapped_in_to_thread() -> None:
    """service 层的缓存/落盘调用点必须经 asyncio.to_thread（关键路径抽查）。"""
    panel_text = (PLUGIN_DIR / "services" / "panel_service.py").read_text(encoding="utf-8")
    for call in ("self._cache.get", "self._cache.put", "self._render_fn"):
        pattern = rf"asyncio\.to_thread\({re.escape(call)}"
        assert re.search(pattern, panel_text), \
            f"panel_service 中 {call} 未包裹 asyncio.to_thread"

    bind_text = (PLUGIN_DIR / "services" / "bind_service.py").read_text(encoding="utf-8")
    assert "asyncio.to_thread(qr_png_bytes" in bind_text, \
        "bind_service 中二维码生成未包裹 asyncio.to_thread"
