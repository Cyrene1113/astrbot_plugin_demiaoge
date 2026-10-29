"""德谬歌：崩坏：星穹铁道查询插件（v0.4 集成层，唯一允许 import astrbot 的文件）。

组装 W1/W2 交付件（适配层/渲染/存储/缓存）并按 DEVELOPMENT.md §2 表格机械分发
``/hsr`` 子命令。所有回复均为固定文案模板，零 LLM 参与。

异步纪律：命令生成器只做 await/yield——渲染与二维码落盘走 ``asyncio.to_thread``、
网络全异步（httpx）、扫码轮询 ``await asyncio.sleep``、图标下载后台预热任务；
事件循环上不执行阻塞 I/O。所有图片一律以**文件路径**发送（AstrBot
``event.image_result`` 只接受 URL/路径字符串，传 bytes 会 TypeError）。
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from .adapters.icon_cache import IconCache
from .adapters.mihomo_api import MihomoApiClient
from .adapters.mihoyo_auth import MihoyoQrAuth
from .domain.errors import DemiaogeError
from .render.html_card import render_entry_to_path
from .services.bind_service import (
    NO_STORE_MESSAGE,
    POLL_INTERVAL_SECONDS,
    POLL_MAX_TIMES,
    QrBindSession,
    QR_HINT_TEXT,
    SCANNED_TEXT,
    TIMEOUT_TEXT,
)
from .services.cache_service import (
    CARD_CACHE_CLEAN_INTERVAL_SECONDS,
    ProfileCache,
    clean_card_cache,
)
from .services.http_server import HsrHttpServer
from .services.panel_service import PanelService
from .services.request_context import RequestContext
from .services.uid_resolver import (
    ALIAS_MESSAGE,
    DEFAULT_ALIAS,
    UID_MESSAGE,
    is_valid_alias,
    is_valid_uid,
    resolve_uid,
)
from .services.wiki_service import WikiService
from .services.wiki_update_service import WikiUpdateService
from .storage.credentials import CredentialStore

# ---------------- 固定文案 ----------------

MAX_BINDINGS_PER_OWNER = 5  # 每人绑定数量上限（防滥用；更新既有别名不计入）

HELP_TEXT = (
    "德谬歌 · 崩坏：星穹铁道查询\n"
    "/hsr help（帮助）- 查看本帮助\n"
    "/hsr 绑定 <UID> [别名] - 绑定 UID（别名缺省 default，可多账号，上限 5 个）\n"
    "/hsr 切换 <别名> - 切换当前使用账号\n"
    "/hsr 扫码 - 米游社扫码绑定（180 秒内确认有效，凭据加密保存）\n"
    "/hsr 我的绑定 - 查看全部绑定（★ 为当前使用）\n"
    "/hsr 解绑 [别名] - 删除绑定（缺省 default）\n"
    "/hsr 面板 [UID|别名] - 面板总览图\n"
    "/hsr 练度 [UID|别名] - 全角色练度统计图\n"
    "/hsr 角色 <名称> [UID|别名] - 单角色详情图\n"
    "/hsr 光锥 <名称> [UID|别名] - 光锥资料图（带 UID/别名时附持有者）\n"
    "/hsr 体力 - 查询本人开拓力与委托（需扫码绑定，仅查自己的账号）\n"
    "/hsr wiki <名称> [--image] - Wiki 查询（--image 输出图片卡片）\n"
    "/hsr 更新缓存 - 管理员：清空面板数据缓存与成图缓存\n"
    "/hsr 更新数据 - 管理员：立即与 BWiki 核对 Wiki 数据并入库（每日定时自动执行，时间可在配置调整）"
)
BIND_USAGE_TEXT = "用法：/hsr 绑定 <UID> [别名]，例如 /hsr 绑定 100000001 小号"
BIND_MIGRATION_TEXT = "绑定方式已更新：请使用 /hsr 绑定 <UID> [别名] 或 /hsr 扫码（米游社 App 扫码登录）。"
BIND_UPDATED_TEXT = "绑定已更新：{alias}（UID:{uid}）。"
BIND_DUPLICATE_TEXT = "该 UID 已绑定为别名 {other}，无需重复绑定；如需切换请 /hsr 切换 {other}。"
BIND_LIMIT_TEXT = "绑定数量已达上限（{limit} 个）。请先 /hsr 解绑 <别名> 释放名额。"
SWITCH_USAGE_TEXT = "用法：/hsr 切换 <别名>"
SWITCH_DONE_TEXT = "已切换当前使用账号：{alias}（UID:{uid}）。"
CHARACTER_USAGE_TEXT = "用法：/hsr 角色 <名称> [UID|别名]，例如 /hsr 角色 流萤"
LIGHT_CONE_USAGE_TEXT = "用法：/hsr 光锥 <名称> [UID|别名]，例如 /hsr 光锥 于夜色中"
INTERNAL_ERROR_TEXT = "内部错误，请稍后再试。（request_id:{request_id}）"
REFRESH_DONE_TEXT = "缓存已更新：面板数据缓存与成图缓存已清空。"
BIND_SUCCESS_TEXT = "绑定成功：{alias}（UID:{uid}）。"
NO_BINDING_LIST_TEXT = "暂无绑定。请使用 /hsr 绑定 <UID> 或 /hsr 扫码。"

WIKI_USAGE_TEXT = "用法：/hsr wiki <名称> [--image]，例如 /hsr wiki 希儿 --image"
SYNC_STARTED_TEXT = "Wiki 数据更新已在后台启动（约 5-10 分钟），完成后写入 data/wiki_sync_audit.json 并记录日志。"
SYNC_RUNNING_TEXT = "Wiki 数据更新正在进行中，请稍后再试。"
SYNC_DENIED_TEXT = "该命令仅管理员可用。"


# ---------------- mock 适配器（adapter=mock 时无网调试用） ----------------

def _mock_payload(uid: str) -> dict[str, Any]:
    """固定离线面板数据（字段形状同 api_notes §2 实测 schema 的最小子集）。"""

    def character(char_id: str, name: str, path_name: str, element_name: str,
                  element_color: str, lc_name: str, lc_id: str) -> dict[str, Any]:
        return {
            "id": char_id,
            "name": name,
            "rarity": 5,
            "rank": 2,
            "level": 80,
            "promotion": 6,
            "icon": f"icon/character/{char_id}.png",
            "path": {"id": path_name, "name": path_name, "icon": ""},
            "element": {"id": element_name, "name": element_name, "color": element_color, "icon": ""},
            "skills": [
                {"name": "普攻", "level": 6, "max_level": 10, "type_text": "普攻"},
                {"name": "战技", "level": 9, "max_level": 12, "type_text": "战技"},
            ],
            "light_cone": {
                "id": lc_id, "name": lc_name, "rarity": 5, "rank": 1, "level": 80,
                "promotion": 6, "icon": f"icon/light_cone/{lc_id}.png", "path": {"name": path_name},
            },
            "relics": [],
            "relic_sets": [],
            "properties": [{"name": "生命值", "display": "6000"}],
        }

    return {
        "player": {
            "uid": uid,
            "nickname": "德谬歌Mock",
            "level": 70,
            "world_level": 6,
            "avatar": {"id": "202006", "name": "通缉令", "icon": "icon/avatar/IconHead_202006.png"},
            "is_display": True,
        },
        "characters": [
            character("1310", "流萤", "毁灭", "火", "#F84F36", "记一位星神的陨落", "24000"),
            character("1003", "布洛妮娅", "同谐", "风", "#00FF9C", "于夜色中", "23013"),
        ],
    }


class _MockMihomoClient:
    """adapter=mock 的离线客户端：对任意 UID 返回固定 payload（每次新构造，防串改）。"""

    async def fetch_parsed(self, uid: str, request_id: str) -> dict[str, Any]:
        return _mock_payload(uid)


# ---------------- 插件入口 ----------------


@register("德谬歌", "AstrBot", "崩坏：星穹铁道查询插件", "0.4.1")
class DemiaogePlugin(Star):
    """插件入口：组装依赖并处理 /hsr 子命令（分发表见 DEVELOPMENT.md §2）。"""

    def __init__(self, context: Context, config: dict | None = None) -> None:
        super().__init__(context, config)
        self.config = config or {}
        plugin_dir = Path(__file__).resolve().parent
        data_dir = plugin_dir / "data"
        self.data_dir = data_dir

        # Wiki（沿用 v0.3：拆分文件优先，缺则回退 wiki.json）
        split_files = [data_dir / name for name in
                       ("characters.json", "light_cones.json", "relics.json", "wiki.json")]
        wiki_files = split_files if all(path.exists() for path in split_files) else [data_dir / "wiki.json"]
        self.wiki_service = WikiService(wiki_files, data_dir / "aliases.json")

        # 凭据存储（master_key 未配置 → 绑定功能禁用，查询类命令不受影响）
        master_key = self.config.get("master_key") or os.getenv("DEMIAOGE_MASTER_KEY")
        self.store: CredentialStore | None = None
        if master_key:
            with contextlib.suppress(ValueError):
                self.store = CredentialStore(data_dir / "credentials.json", str(master_key))

        # 缓存 / 图标 / 渲染缓存目录
        try:
            ttl_minutes = int(self.config.get("cache_ttl_minutes", 10))
        except (TypeError, ValueError):
            ttl_minutes = 10
        self.cache = ProfileCache(data_dir / "profile_cache", ttl_seconds=max(1, ttl_minutes) * 60)
        self.icon_cache = IconCache(root=data_dir / "icons")
        self.card_dir = data_dir / "card_cache"

        # Edge 路径（render/engine.find_edge 读环境变量 DEMIAOGE_EDGE；不改 W1 文件）
        edge_path = str(self.config.get("edge_path") or "").strip()
        if edge_path:
            os.environ["DEMIAOGE_EDGE"] = edge_path

        # 数据适配器（mihomo=线上；mock=离线调试）
        adapter_name = str(self.config.get("adapter", "mihomo")).lower()
        self._mihomo_client: Any = _MockMihomoClient() if adapter_name == "mock" else MihomoApiClient()
        self.panel_service = PanelService(self._mihomo_client, self.cache, self.icon_cache, self.store,
                                          self.wiki_service, self.card_dir)

        # 公共查询端口
        host = str(self.config.get("http_host", "127.0.0.1"))
        try:
            port = int(self.config.get("http_port", 8765))
        except (TypeError, ValueError):
            port = 8765
        self.http_server = HsrHttpServer(lambda: self.panel_service, host=host, port=port)

        # Wiki 数据周期核对（每日固定时间与 BWiki 核对入库）
        self.wiki_updater = WikiUpdateService(
            data_dir, daily_time=str(self.config.get("auto_update_time", "04:30")))
        self._update_task: asyncio.Task | None = None
        self._update_sync_task: asyncio.Task | None = None
        self._sync_running = False
        self._cache_gc_task: asyncio.Task | None = None

    # ---------- 生命周期 ----------

    async def initialize(self) -> None:
        await super().initialize()
        if bool(self.config.get("http_enabled", True)):
            started = await self.http_server.start()
            if not started:
                logger.warning("[demiaoge] HTTP 端口 %s:%s 启动失败（可能被占用），公共查询端口未启用。",
                               self.http_server.host, self.http_server.port)
            else:
                logger.info("[demiaoge] 公共查询端口已启动：http://%s:%s/hsr/profile",
                            self.http_server.host, self.http_server.port)
        if bool(self.config.get("auto_update", True)):
            self._update_task = asyncio.create_task(self.wiki_updater.schedule_loop())
        # 成图缓存每日回收（内容哈希键下旧图永不复用，超期自动清理防目录膨胀）
        self._cache_gc_task = asyncio.create_task(self._card_cache_gc_loop())

    async def _card_cache_gc_loop(self) -> None:
        """启动时先清一轮，之后每 24h 回收 card_cache 中超期 PNG（磁盘 I/O 走 to_thread）。"""
        try:
            while True:
                try:
                    removed = await asyncio.to_thread(clean_card_cache, self.card_dir)
                    if removed:
                        logger.info("[demiaoge] 成图缓存回收：%d 个超期 PNG 已清理。", removed)
                except Exception:
                    logger.warning("[demiaoge] 成图缓存回收失败，24h 后重试。", exc_info=True)
                await asyncio.sleep(CARD_CACHE_CLEAN_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            raise

    async def terminate(self) -> None:
        for task_attr in ("_cache_gc_task", "_update_task", "_update_sync_task"):
            task = getattr(self, task_attr, None)
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
                setattr(self, task_attr, None)
        with contextlib.suppress(Exception):
            await self.panel_service.wait_background()  # 收尾：兼容保留（图标解析已收敛进关键路径）
        with contextlib.suppress(Exception):
            await self.icon_cache.aclose()  # 收尾：关闭图标下载共享连接池
        mihomo_aclose = getattr(self._mihomo_client, "aclose", None)
        if mihomo_aclose is not None:
            with contextlib.suppress(Exception):
                await mihomo_aclose()  # 收尾：关闭 Mihomo 主路径共享连接池
        with contextlib.suppress(Exception):
            await self.http_server.stop()
        await super().terminate()

    # ---------- 命令入口 ----------

    @filter.command("hsr")
    async def hsr(self, event: AstrMessageEvent):
        """命令总入口：机械解析子命令并分发；异常统一转固定文案。"""
        request = RequestContext.create()
        parts = (event.message_str or "").strip().split()
        sub = parts[1] if len(parts) > 1 else "help"
        owner_id = str(event.get_sender_id())
        try:
            async for result in self._dispatch(event, request, parts, sub, owner_id):
                yield result
        except DemiaogeError as exc:
            # DemiaogeError 未定义 .message 属性，文案即异常首参（str(exc)）。
            yield event.plain_result(str(exc))
        except Exception:
            logger.exception("[demiaoge] request_id=%s 处理 /hsr 命令时发生未预期异常", request.request_id)
            yield event.plain_result(INTERNAL_ERROR_TEXT.format(request_id=request.request_id))

    def _route(self, sub: str):
        """§2 分发表；未知子命令返回 None → 帮助。旧别名：profile/panel→面板，bind→绑定说明。"""
        key = sub.lower()
        return {
            "help": self._cmd_help,
            "帮助": self._cmd_help,
            "绑定": self._cmd_bind,
            "切换": self._cmd_switch,
            "扫码": self._cmd_scan,
            "我的绑定": self._cmd_bindings,
            "解绑": self._cmd_unbind,
            "面板": self._cmd_panel,
            "profile": self._cmd_panel,
            "panel": self._cmd_panel,
            "练度": self._cmd_audit,
            "体力": self._cmd_note,
            "角色": self._cmd_character,
            "光锥": self._cmd_light_cone,
            "wiki": self._cmd_wiki,
            "更新缓存": self._cmd_refresh,
            "更新数据": self._cmd_sync_wiki,
            "bind": self._cmd_bind_legacy,
        }.get(key)

    async def _dispatch(self, event: AstrMessageEvent, request: RequestContext,
                        parts: list[str], sub: str, owner_id: str):
        handler = self._route(sub)
        if handler is None:
            yield event.plain_result(HELP_TEXT)
            return
        async for result in handler(event, request, parts, owner_id):
            yield result

    # ---------- 各子命令（均为 async 生成器） ----------

    async def _cmd_help(self, event, request, parts, owner_id):
        yield event.plain_result(HELP_TEXT)

    async def _cmd_bind_legacy(self, event, request, parts, owner_id):
        """旧 /hsr bind <Cookie> 路径已删除；无参/带参统一回新绑定说明。"""
        yield event.plain_result(BIND_MIGRATION_TEXT)

    async def _cmd_bind(self, event, request, parts, owner_id):
        tokens = [part for part in parts[2:] if not part.startswith("--")]
        if not tokens:
            yield event.plain_result(BIND_USAGE_TEXT)
            return
        uid = tokens[0]
        if not is_valid_uid(uid):
            yield event.plain_result(UID_MESSAGE)
            return
        # 别名多于一个 token 视为含空白 → 走别名不合法文案（别名规则：不含空白）。
        alias = " ".join(tokens[1:]) if len(tokens) > 1 else DEFAULT_ALIAS
        if not is_valid_alias(alias):
            yield event.plain_result(ALIAS_MESSAGE)
            return
        if self.store is None:
            yield event.plain_result(NO_STORE_MESSAGE)
            return
        # 防冲突：同人同 UID 只保留一条绑定（换别名重复绑无意义）。
        existing_alias = self.store.find_uid(owner_id, uid)
        if existing_alias is not None and existing_alias != alias:
            yield event.plain_result(BIND_DUPLICATE_TEXT.format(other=existing_alias))
            return
        # 防滥用：每人绑定数量上限（更新既有别名不计入新增）。
        accounts = self.store.list_accounts(owner_id)
        is_new_alias = all(item.get("alias") != alias for item in accounts)
        if is_new_alias and len(accounts) >= MAX_BINDINGS_PER_OWNER:
            yield event.plain_result(BIND_LIMIT_TEXT.format(limit=MAX_BINDINGS_PER_OWNER))
            return
        # UID 绑定无 Cookie：占位存 uid 本身（bind_type=uid 时业务层不得使用 cookie 字段）。
        self.store.bind(owner_id, alias, uid, uid=uid, bind_type="uid")
        # 新增绑定自动设为当前使用账号（更新既有别名不动指针）。
        if is_new_alias:
            self.store.set_current(owner_id, alias)
            yield event.plain_result(BIND_SUCCESS_TEXT.format(alias=alias, uid=uid))
        else:
            yield event.plain_result(BIND_UPDATED_TEXT.format(alias=alias, uid=uid))

    async def _cmd_switch(self, event, request, parts, owner_id):
        """`/hsr 切换 <别名>`：设置本人当前使用账号（防串号配套，多账号免记别名）。"""
        alias = next((part for part in parts[2:] if not part.startswith("--")), "")
        if not alias:
            yield event.plain_result(SWITCH_USAGE_TEXT)
            return
        if self.store is None:
            yield event.plain_result(NO_STORE_MESSAGE)
            return
        try:
            bundle = self.store.get_bundle(owner_id, alias)
        except ValueError:
            bundle = None  # 凭据解密/完整性校验失败：按未绑定处理，回固定文案
        if bundle is None or not bundle.get("uid"):
            yield event.plain_result(NO_BINDING_MESSAGE)
            return
        self.store.set_current(owner_id, alias)
        yield event.plain_result(SWITCH_DONE_TEXT.format(alias=alias, uid=bundle["uid"]))

    async def _cmd_scan(self, event, request, parts, owner_id):
        if self.store is None:
            yield event.plain_result(NO_STORE_MESSAGE)
            return
        session = QrBindSession(MihoyoQrAuth(), self.store, request.request_id)
        ticket, _url, png, fallback_text = await session.step_create()
        if png is not None:
            qr_path = await asyncio.to_thread(
                session.save_qr_png, png, self.data_dir / "card_cache", ticket)
            yield event.image_result(str(qr_path))
            yield event.plain_result(QR_HINT_TEXT)
        else:
            yield event.plain_result(fallback_text)
        scanned_notified = False
        for _ in range(POLL_MAX_TIMES):
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            status, bundle, stop_text = await session.step_poll(ticket)
            if stop_text:
                yield event.plain_result(stop_text)
                return
            if status == "Confirmed" and bundle is not None:
                yield event.plain_result(session.finish_bind(owner_id, DEFAULT_ALIAS, bundle))
                self.store.set_current(owner_id, DEFAULT_ALIAS)  # 扫码绑定后设为当前账号
                return
            if status == "Scanned" and not scanned_notified:
                scanned_notified = True
                yield event.plain_result(SCANNED_TEXT)
        yield event.plain_result(TIMEOUT_TEXT)

    async def _cmd_bindings(self, event, request, parts, owner_id):
        if self.store is None:
            yield event.plain_result(NO_STORE_MESSAGE)
            return
        accounts = self.store.list_accounts(owner_id)
        if not accounts:
            yield event.plain_result(NO_BINDING_LIST_TEXT)
            return
        current = self.store.get_current(owner_id)
        lines = ["当前绑定："]
        lines.extend(
            f"{'★' if account.get('alias') == current else '-'} {account.get('alias', '')}：UID {account.get('uid') or '未填写'}"
            + ("（当前使用）" if account.get("alias") == current else "")
            for account in accounts)  # 凭据永不回显；绑定时间未存储故不显示
        yield event.plain_result("\n".join(lines))

    async def _cmd_unbind(self, event, request, parts, owner_id):
        alias = next((part for part in parts[2:] if not part.startswith("--")), DEFAULT_ALIAS)
        if self.store is None:
            yield event.plain_result(NO_STORE_MESSAGE)
            return
        removed = self.store.unbind(owner_id, alias)
        yield event.plain_result("解绑成功。" if removed else "未找到该绑定。")

    async def _cmd_panel(self, event, request, parts, owner_id):
        uid, error = self._resolve_target(parts, owner_id)
        if uid is None:
            yield event.plain_result(error)
            return
        png_path = await self.panel_service.panel_png(uid, request.request_id)
        yield event.image_result(str(png_path))

    async def _cmd_audit(self, event, request, parts, owner_id):
        uid, error = self._resolve_target(parts, owner_id)
        if uid is None:
            yield event.plain_result(error)
            return
        png_path = await self.panel_service.audit_png(uid, request.request_id)
        yield event.image_result(str(png_path))

    async def _cmd_note(self, event, request, parts, owner_id):
        """实时便签：只查发送者本人账号（防串号——凭据仅按 owner_id 取）。"""
        alias = next((part for part in parts[2:] if not part.startswith("--")), None)
        png_path = await self.panel_service.note_png(owner_id, request.request_id, alias)
        yield event.image_result(str(png_path))

    async def _cmd_character(self, event, request, parts, owner_id):
        tokens = [part for part in parts[2:] if not part.startswith("--")]
        if not tokens:
            yield event.plain_result(CHARACTER_USAGE_TEXT)
            return
        # 机械规则：最后一个 token 为 UID/别名（≥2 个 token 时），其余合并为名称。
        if len(tokens) >= 2:
            name, target = " ".join(tokens[:-1]), tokens[-1]
        else:
            name, target = tokens[0], None
        uid, error = resolve_uid(target, self.store, owner_id)
        if uid is None:
            yield event.plain_result(error)
            return
        png_path = await self.panel_service.character_png(uid, name, request.request_id)
        yield event.image_result(str(png_path))

    async def _cmd_light_cone(self, event, request, parts, owner_id):
        tokens = [part for part in parts[2:] if not part.startswith("--")]
        if not tokens:
            yield event.plain_result(LIGHT_CONE_USAGE_TEXT)
            return
        if len(tokens) >= 2:
            name, target = " ".join(tokens[:-1]), tokens[-1]
        else:
            name, target = tokens[0], None
        uid = None
        if target is not None:
            uid, error = resolve_uid(target, self.store, owner_id)
            if uid is None:
                yield event.plain_result(error)
                return
        # 未带 UID/别名 → 纯资料卡（不带持有者行）。
        png_path = await self.panel_service.light_cone_png(uid, name, request.request_id)
        yield event.image_result(str(png_path))

    async def _cmd_wiki(self, event, request, parts, owner_id):
        """兼容保留 v0.3 行为：默认文本；--image → render_entry 出图。"""
        image_requested = "--image" in parts[2:]
        keyword = " ".join(part for part in parts[2:] if part != "--image").strip()
        if not keyword:
            yield event.plain_result(WIKI_USAGE_TEXT)
            return
        if not image_requested:
            yield event.plain_result(self.wiki_service.query(keyword))
            return
        matches = self.wiki_service.search(keyword)
        if not matches:
            yield event.plain_result(self.wiki_service.query(keyword))
            return
        if len(matches) > 1 and matches[0].searchable_text() == matches[1].searchable_text():
            yield event.plain_result(self.wiki_service.query(keyword) + "\n请补充完整名称后再生成图片。")
            return
        try:
            image_path = await asyncio.to_thread(
                render_entry_to_path, matches[0], self.data_dir / "card_cache")
        except RuntimeError as exc:
            yield event.plain_result(f"图片卡片渲染失败：{exc}\n文字结果：\n{self.wiki_service.format_entry(matches[0])}")
            return
        yield event.image_result(str(image_path))

    async def _cmd_refresh(self, event, request, parts, owner_id):
        admins = {str(item) for item in (self.config.get("admins") or [])}
        if owner_id not in admins:
            yield event.plain_result("该命令仅管理员可用。")
            return
        # 磁盘清理放 to_thread，不占事件循环；card_cache 含二维码与内容哈希成图，一并清理。
        await asyncio.to_thread(self._clear_render_caches)
        yield event.plain_result(REFRESH_DONE_TEXT)

    def _clear_render_caches(self) -> None:
        self.cache.invalidate()
        if self.card_dir.exists():
            for png_path in self.card_dir.glob("*.png"):
                with contextlib.suppress(OSError):
                    png_path.unlink()

    async def _cmd_sync_wiki(self, event, request, parts, owner_id):
        """管理员：立即与 BWiki 核对一次 Wiki 数据（后台执行，完成后记日志与审计）。"""
        admins = {str(item) for item in (self.config.get("admins") or [])}
        if owner_id not in admins:
            yield event.plain_result(SYNC_DENIED_TEXT)
            return
        if self._sync_running:
            yield event.plain_result(SYNC_RUNNING_TEXT)
            return
        self._sync_running = True

        def _finished() -> None:
            self._sync_running = False
            report = self.wiki_updater.last_report
            if report is not None:
                logger.info("[demiaoge] %s", self.wiki_updater.format_report(report).replace("\n", " | "))

        async def _job() -> None:
            try:
                await asyncio.to_thread(self.wiki_updater.run_sync_once)
            finally:
                _finished()

        self._update_sync_task = asyncio.create_task(_job())
        self._update_sync_task.add_done_callback(
            lambda task: None if task.cancelled() else task.exception())
        yield event.plain_result(SYNC_STARTED_TEXT)

    # ---------- 工具 ----------

    def _resolve_target(self, parts: list[str], owner_id: str) -> tuple[str | None, str]:
        """面板/练度的 UID 解析：显式参数 > 绑定别名 > 本人 default 绑定。"""
        target = next((part for part in parts[2:] if not part.startswith("--")), None)
        return resolve_uid(target, self.store, owner_id)
