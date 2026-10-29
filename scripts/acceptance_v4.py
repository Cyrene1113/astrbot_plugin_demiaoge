"""v0.4 最终验收图生成脚本（W4）：真 Edge 渲染 4 张卡片到 data/render_v4_acceptance/。

- 数据：`data/fixtures/mihomo_sr_info_parsed.json`（W1-A 实测快照），经 fake client
  注入 PanelService（写法与 test_panel_service.py 一致），离线确定性。
- 图标：MockTransport 恒 404 → 走模板占位灰块。验收只考渲染链路，不依赖网络；
  真实图标效果（jsDelivr 多源下载）另用已预热 data/icons 的环境目检。
- 输出：panel/audit/character/lc 四张 PNG，打印每张路径 / 像素尺寸 / 文件大小 / 耗时。

运行（父目录或任意位置均可）：
    python astrbot_plugin_demiaoge/scripts/acceptance_v4.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
PARENT_DIR = PLUGIN_DIR.parent
if str(PARENT_DIR) not in sys.path:
    sys.path.insert(0, str(PARENT_DIR))

import httpx  # noqa: E402

from astrbot_plugin_demiaoge.adapters.icon_cache import IconCache  # noqa: E402
from astrbot_plugin_demiaoge.render.engine import find_edge  # noqa: E402
from astrbot_plugin_demiaoge.services.cache_service import ProfileCache  # noqa: E402
from astrbot_plugin_demiaoge.services.panel_service import PanelService  # noqa: E402
from astrbot_plugin_demiaoge.services.wiki_service import WikiService  # noqa: E402

FIXTURE = PLUGIN_DIR / "data" / "fixtures" / "mihomo_sr_info_parsed.json"
OUT_DIR = PLUGIN_DIR / "data" / "render_v4_acceptance"
REQUEST_ID = "acceptance-v4"


class FixtureClient:
    """fake client：对任意 UID 返回 fixture 深拷贝（防缓存对象被串改）。"""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    async def fetch_parsed(self, uid: str, request_id: str) -> dict:
        return json.loads(json.dumps(self._payload))


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    """从 PNG 头解析 (宽, 高)；非 PNG 返回 None。"""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


async def _main() -> int:
    edge = find_edge()
    if not edge:
        print("[acceptance-v4] 未找到 Microsoft Edge，无法真渲染；可设 DEMIAOGE_EDGE 后重试。")
        return 1
    print(f"[acceptance-v4] Edge：{edge}")

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    uid = str(payload["player"]["uid"])
    data_dir = PLUGIN_DIR / "data"
    wiki = WikiService([data_dir / "characters.json", data_dir / "light_cones.json"],
                       data_dir / "aliases.json")
    # 恒 404：图标解析立即失败返回 ""，绝不触碰真实网络 → 占位灰块（验收只考渲染链路）。
    offline_transport = httpx.MockTransport(lambda request: httpx.Response(404, text="offline"))
    with tempfile.TemporaryDirectory(prefix="demiaoge-acceptance-") as tmp:
        service = PanelService(
            FixtureClient(payload),
            ProfileCache(Path(tmp) / "profile_cache", ttl_seconds=600),
            IconCache(root=Path(tmp) / "icons", transport=offline_transport),
            None,
            wiki,
            OUT_DIR,  # 四张成图均落在该目录（panel/audit 由服务写，character/lc 由 engine 写）
        )
        jobs = [
            ("面板总览 panel_png", lambda: service.panel_png(uid, REQUEST_ID)),
            ("练度统计 audit_png", lambda: service.audit_png(uid, REQUEST_ID)),
            ("角色详情 character_png(流萤)", lambda: service.character_png(uid, "流萤", REQUEST_ID)),
            ("光锥资料 light_cone_png(记一位星神的陨落)",
             lambda: service.light_cone_png(uid, "记一位星神的陨落", REQUEST_ID)),
        ]
        results: list[tuple[str, Path, float]] = []
        failed = False
        for title, call in jobs:
            started = time.perf_counter()
            try:
                png_path = await call()
            except Exception as exc:  # 验收脚本要看到全部失败，不吞异常
                print(f"[acceptance-v4] {title} 失败：{type(exc).__name__}: {exc}")
                failed = True
                continue
            elapsed = time.perf_counter() - started
            data = png_path.read_bytes()
            dims = _png_dimensions(data)
            size_kb = len(data) / 1024
            dim_text = f"{dims[0]}x{dims[1]}px" if dims else "非 PNG"
            print(f"[acceptance-v4] {title}\n"
                  f"    路径：{png_path}\n"
                  f"    尺寸：{dim_text}（{size_kb:.1f} KB）  耗时：{elapsed:.2f}s")
            results.append((title, png_path, elapsed))
        await service.wait_background()

    if failed or len(results) != 4:
        print(f"[acceptance-v4] 验收未通过：成功 {len(results)}/4 张。")
        return 1
    total = sum(elapsed for _, _, elapsed in results)
    print(f"[acceptance-v4] 4/4 张验收图已生成于 {OUT_DIR}（合计渲染耗时 {total:.2f}s；"
          f"验收用离线 MockTransport，图标为占位灰块属预期；真实图标效果见 data/icons 预热后的环境）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
