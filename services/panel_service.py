"""核心用例编排（DEVELOPMENT.md §4 数据流，全机械）：取数 → 固定映射 → 渲染。

- 禁止 import astrbot；全部协作者（client/cache/icon_cache/store/wiki_service）
  由构造注入，离线可测。
- 异步纪律：事件循环上不做阻塞工作——网络全异步（httpx）、Edge 截图 / payload
  缓存磁盘 I/O / 卡片映射一律 ``asyncio.to_thread``；图标解析在命令关键路径上
  限时 await（ICON_WAIT_SECONDS，超时/失败静默 → 渲染占位兜底，负缓存防重复
  打网络），渲染只引用本地已落盘的图标文件。
- 成图：卡片渲染（engine 内容哈希缓存键）落盘 ``card_dir/{key}.png``，本服务
  返回 **PNG 文件路径**（AstrBot ``image_result`` 只收路径字符串，不收 bytes）；
  同一份数据重复查询由引擎缓存命中，数据变化即换键重渲染。
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..adapters.mihomo_mapper import (
    iter_icon_paths,
    map_character_detail,
    map_mihomo_payload,
)
from ..adapters.mihoyo_record import MihoyoRecordClient, resolve_server
from ..domain.errors import DemiaogeError, ErrorCode
from ..render import audit_card, character_card, lc_card, note_card, panel_card
from ..render.v2_models import (
    ExpeditionVM,
    LightConeOwnerVM,
    LightConeSkillVM,
    LightConeVM,
    NoteVM,
)

# 固定文案（与 DEVELOPMENT.md §2 / 任务规格一致，绝不透传上游原文）。
CHARACTER_NOT_FOUND_MESSAGE = "未在对方展示列表中找到该角色。"
CHARACTER_AMBIGUOUS_MESSAGE = "名称有歧义，请补充完整角色名。"
LIGHT_CONE_NOT_FOUND_MESSAGE = "未收录该光锥，请检查名称。"
RENDER_FAILED_MESSAGE = "图片渲染失败，请稍后再试。"
NOTE_NO_BINDING_MESSAGE = "尚未绑定账号，请先 /hsr 绑定 <UID> 或 /hsr 扫码。"
NOTE_NEED_QR_MESSAGE = "体力查询需要扫码绑定（/hsr 扫码）：UID 绑定没有所需凭据，且只能查询本人的账号。"

# render_fn 注入点：kind ∈ {"panel","audit","character","lc","note"}；渲染落盘并返回 PNG 路径。
RenderFn = Callable[[str, Any, Path], Path]

# 成图命令关键路径上等待图标下载的上限：超时/失败不阻塞出图（渲染层占位兜底）。
# 图标源（jsDelivr 镜像）单张 <1s，信号量 6 并发，整面板几十张通常 3-5s 内完成；
# 之后全部走本地磁盘缓存，二次查询零网络。
ICON_WAIT_SECONDS = 8.0


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

_DEFAULT_RENDERERS: dict[str, Callable[[Any, Path], Path]] = {
    "panel": panel_card.render_to_path,
    "audit": audit_card.render_to_path,
    "character": character_card.render_to_path,
    "lc": lc_card.render_to_path,
    "note": note_card.render_to_path,
}


class _LocalIconResolver:
    """同步只读图标解析：仅查 ``icons_root/rel_path`` 本地文件，绝不触发下载。

    与 IconCache.resolve 的语义对齐（空路径 / 含 ``..`` 一律 ""），供 mapper 把
    相对图标路径换成本地绝对路径；拿不到返回 ""，渲染层自动占位。
    """

    def __init__(self, root: Path | None) -> None:
        self._root = Path(root) if root is not None else None

    def __call__(self, rel_path: str) -> str:
        rel = (rel_path or "").strip().lstrip("/")
        if not rel or ".." in rel or self._root is None:
            return ""
        local = self._root / rel
        if local.is_file():
            with contextlib.suppress(OSError):
                return str(local.resolve())
        return ""


class PanelService:
    """面板/练度/角色/光锥四种成图 + payload 取数的统一编排。"""

    def __init__(self, client: Any, cache: Any, icon_cache: Any, store: Any,
                 wiki_service: Any, card_dir: Path, render_fn: RenderFn | None = None,
                 record_client: Any = None) -> None:
        self._client = client
        self._cache = cache
        self._icon_cache = icon_cache
        self._store = store
        self._wiki = wiki_service
        self._card_dir = Path(card_dir)
        self._render_fn: RenderFn = render_fn or self._default_render
        self._icon_resolver = _LocalIconResolver(getattr(icon_cache, "root", None))
        self._record_client = record_client if record_client is not None else MihoyoRecordClient()

    # ---------- 取数 ----------

    async def get_payload(self, uid: str, request_id: str) -> tuple[dict[str, Any], bool]:
        """payload 取数：TTL 缓存命中直接返回；未命中走 client 后回填缓存。

        返回 ``(payload, 是否来自缓存)``；client 的 DemiaogeError 原样向上抛。
        缓存磁盘读写（JSON 可达数百 KB）放 to_thread，不占事件循环。
        """
        cached = await asyncio.to_thread(self._cache.get, str(uid))
        if cached is not None:
            return cached, True
        payload = await self._client.fetch_parsed(str(uid), request_id)
        await asyncio.to_thread(self._cache.put, str(uid), payload)
        return payload, False

    # ---------- 成图用例（返回 PNG 文件路径） ----------

    async def panel_png(self, uid: str, request_id: str) -> Path:
        """`/hsr 面板`：面板总览图，返回 PNG 文件路径。"""
        return await self._typed_png("panel", uid, request_id)

    async def audit_png(self, uid: str, request_id: str) -> Path:
        """`/hsr 练度`：全角色练度统计图，返回 PNG 文件路径。"""
        return await self._typed_png("audit", uid, request_id)

    async def character_png(self, uid: str, name: str, request_id: str) -> Path:
        """`/hsr 角色`：单角色详情图（名字走 wiki 别名 → payload 匹配）。"""
        payload, _ = await self.get_payload(uid, request_id)
        await self._resolve_icons(payload)
        char_dict = self._match_character(payload, name)
        vm = await asyncio.to_thread(map_character_detail, char_dict, self._icon_resolver)
        return await self._render_to_path("character", vm)

    async def light_cone_png(self, uid: str | None, name: str, request_id: str) -> Path:
        """`/hsr 光锥`：光锥资料图。

        资料（描述/叠影）来自 wiki 光锥条目；uid 非空时附加持有者行
        （payload 中装备该光锥的角色），uid 为 None 时为纯资料卡。
        """
        entry = self._resolve_light_cone_entry(name)
        owners: tuple[LightConeOwnerVM, ...] = ()
        if uid:
            payload, _ = await self.get_payload(uid, request_id)
            await self._resolve_icons(payload)
            owners = await asyncio.to_thread(self._collect_owners, payload, entry.name, name)
        vm = LightConeVM(
            name=entry.name,
            rarity=entry.rarity,
            # 首个 tag 为命途（解析顺序：命途 → 光锥TAG），其余 TAG 不进命途位。
            path_name=entry.tags[0] if entry.tags else "",
            description=entry.description,
            skills=tuple(LightConeSkillVM(title=skill_name, description=skill_desc)
                         for skill_name, skill_desc in entry.skills),
            owners=owners,
        )
        return await self._render_to_path("lc", vm)

    # ---------- 内部：机械步骤 ----------

    async def note_png(self, owner_id: str, request_id: str,
                       alias: str | None = None) -> Path:
        """`/hsr 体力`：实时便签图（开拓力/委托/实训/周本）。

        防串号（W7 硬约束）：owner_id 必须来自事件发送者，凭据只从
        ``store.get_bundle(owner_id, alias)`` 取——绝不接受消息参数指定他人账号。
        UID 绑定无 stoken/cookie，无法查 note → 固定提示引导扫码绑定。
        """
        if self._store is None:
            raise DemiaogeError(ErrorCode.AUTH_MISSING, NOTE_NO_BINDING_MESSAGE, request_id)
        target_alias = alias or self._store.get_current(owner_id) or "default"
        bundle = self._store.get_bundle(owner_id, target_alias)
        if bundle is None or not bundle.get("uid"):
            raise DemiaogeError(ErrorCode.AUTH_MISSING, NOTE_NO_BINDING_MESSAGE, request_id)
        if bundle.get("bind_type") != "qr" or not bundle.get("cookie"):
            raise DemiaogeError(ErrorCode.AUTH_MISSING, NOTE_NEED_QR_MESSAGE, request_id)
        uid = str(bundle["uid"])
        data = await self._record_client.fetch_note(
            uid, resolve_server(uid), str(bundle["cookie"]), request_id)
        vm = self._note_viewmodel(uid, data)
        return await self._render_to_path("note", vm)

    def _note_viewmodel(self, uid: str, data: dict[str, Any]) -> NoteVM:
        """上游 note JSON → NoteVM（固定字段表，缺失安全默认值，UI 自动隐藏空区块）。"""

        def _int(item: dict[str, Any], key: str, default: int = 0) -> int:
            try:
                return int(item.get(key, default))
            except (TypeError, ValueError):
                return default

        expeditions: list[ExpeditionVM] = []
        for item in data.get("expeditions") or []:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "")
            if status == "Finished":
                expeditions.append(ExpeditionVM(
                    name=str(item.get("name") or "委托"), status_text="已完成", finished=True))
            else:
                seconds = _int(item, "remaining_time")
                hours, rest = divmod(max(0, seconds), 3600)
                minutes, secs = divmod(rest, 60)
                expeditions.append(ExpeditionVM(
                    name=str(item.get("name") or "委托"),
                    status_text=f"剩余 {hours:02d}:{minutes:02d}:{secs:02d}",
                    finished=False))
        # 每日实训 / 周本字段在不同版本命名不一，按固定候选键依次取首个可用值。
        train = data.get("daily_train") or {}
        rogue = data.get("weekly_rogue") or {}
        train_score = _int(train, "current_train_score", -1) if isinstance(train, dict) else -1
        train_max = _int(train, "max_train_score", -1) if isinstance(train, dict) else -1
        if train_score < 0:
            train_score = _int(data, "current_train_score", -1)
            train_max = _int(data, "max_train_score", -1)
        rogue_count = _int(rogue, "current", -1) if isinstance(rogue, dict) else -1
        rogue_max = _int(rogue, "max", -1) if isinstance(rogue, dict) else -1
        return NoteVM(
            uid=uid,
            current_stamina=_int(data, "current_stamina"),
            max_stamina=_int(data, "max_stamina"),
            recover_seconds=max(0, _int(data, "stamina_recover_time")),
            accepted_expedition_num=_int(data, "accepted_expedition_num"),
            total_expedition_num=_int(data, "total_expedition_num"),
            expeditions=tuple(expeditions),
            daily_train_score=train_score,
            daily_train_max=train_max,
            weekly_rogue_count=rogue_count,
            weekly_rogue_max=rogue_max,
        )

    async def _typed_png(self, kind: str, uid: str, request_id: str) -> Path:
        """面板/练度共用：取数 → 图标解析 → 映射 → 渲染落盘（引擎按内容哈希缓存键去重）。"""
        payload, _ = await self.get_payload(uid, request_id)
        await self._resolve_icons(payload)
        panel_vm, audit_vm, _ = await asyncio.to_thread(map_mihomo_payload, payload, self._icon_resolver)
        return await self._render_to_path(kind, panel_vm if kind == "panel" else audit_vm)

    def _match_character(self, payload: dict[str, Any], name: str) -> dict[str, Any]:
        """payload 角色按名字匹配：wiki 别名→canonical → 精确相等 → 唯一包含。

        0 命中 / >1 命中分别回固定文案（DATA_NOT_FOUND）。
        """
        needle = (name or "").strip()
        characters = [item for item in payload.get("characters", []) if isinstance(item, dict)]
        if not needle:
            raise DemiaogeError(ErrorCode.DATA_NOT_FOUND, CHARACTER_NOT_FOUND_MESSAGE)
        canonical = needle
        entry = self._wiki._exact_entry(needle) if self._wiki is not None else None
        if entry is not None and entry.category == "角色":
            canonical = entry.name
        exact = [item for item in characters
                 if item.get("name") in (needle, canonical)]
        if len(exact) == 1:
            return exact[0]
        if len(exact) > 1:
            raise DemiaogeError(ErrorCode.DATA_NOT_FOUND, CHARACTER_AMBIGUOUS_MESSAGE)
        contains = [item for item in characters
                    if needle in str(item.get("name") or "")
                    or (canonical != needle and canonical in str(item.get("name") or ""))]
        if len(contains) == 1:
            return contains[0]
        if len(contains) > 1:
            raise DemiaogeError(ErrorCode.DATA_NOT_FOUND, CHARACTER_AMBIGUOUS_MESSAGE)
        raise DemiaogeError(ErrorCode.DATA_NOT_FOUND, CHARACTER_NOT_FOUND_MESSAGE)

    def _resolve_light_cone_entry(self, name: str) -> Any:
        """wiki 光锥条目：精确/别名优先，其次按类别过滤的搜索排名，无 → 固定文案。"""
        needle = (name or "").strip()
        if self._wiki is not None and needle:
            entry = self._wiki._exact_entry(needle)
            if entry is not None and entry.category == "光锥":
                return entry
            for candidate in self._wiki.search(needle):
                if candidate.category == "光锥":
                    return candidate
        raise DemiaogeError(ErrorCode.DATA_NOT_FOUND, LIGHT_CONE_NOT_FOUND_MESSAGE)

    def _collect_owners(self, payload: dict[str, Any], *names: str) -> tuple[LightConeOwnerVM, ...]:
        """payload 中装备了给定名字光锥的角色 → 持有者行。

        W8 轻量化：直接机械遍历 payload（字段规则与 map_mihomo_payload 一致：
        rank=light_cone.rank 叠影、eidolon=角色 rank、icon=角色头像），不再为
        提取持有者而整面板构建 CharacterVM（几十个角色的遗器/技能全量映射是浪费）。
        """
        wanted = {name for name in names if name}
        owners: list[LightConeOwnerVM] = []
        for item in payload.get("characters", []):
            if not isinstance(item, dict):
                continue
            light_cone = item.get("light_cone")
            if not isinstance(light_cone, dict) or str(light_cone.get("name") or "") not in wanted:
                continue
            owners.append(LightConeOwnerVM(
                name=str(item.get("name") or ""),
                level=_safe_int(item.get("level")),
                rank=_safe_int(light_cone.get("rank")),
                eidolon=_safe_int(item.get("rank")),
                icon_path=self._icon_resolver(str(item.get("icon") or "")),
            ))
        return tuple(owners)

    # ---------- 内部：图标解析 / 渲染 / 成图缓存 ----------

    async def _resolve_icons(self, payload: dict[str, Any]) -> None:
        """命令关键路径上的图标解析（限时 ICON_WAIT_SECONDS）。

        本地已有 → 直接命中；缺的当场下载（W8：jsDelivr 多源，首次查询即出全图标，
        不再是"第一次灰块、第二次才有图"）。超时/网络失败静默返回，渲染层占位兜底，
        IconCache 的失败负缓存保证同一坏路径短时间内不重复打网络。
        """
        if self._icon_cache is None:
            return
        try:
            paths = list(iter_icon_paths(payload))
        except Exception:
            return  # 路径收集失败不阻塞出图（渲染层有占位兜底）
        if not paths:
            return
        try:
            await asyncio.wait_for(
                self._icon_cache.resolve_many(paths), timeout=ICON_WAIT_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:
            return  # 下载失败/超时 → 占位出图，绝不阻塞命令

    async def wait_background(self) -> None:
        """兼容保留（W8 前 fire-and-forget 预热的收尾接口）：图标解析已全部收敛进
        命令关键路径，当前无后台任务；保留空实现供 main.terminate/测试调用。"""
        return None

    async def _render_to_path(self, kind: str, vm: Any) -> Path:
        """渲染 PNG 并落盘（阻塞 Edge 子进程放 to_thread）；失败统一固定文案。"""
        try:
            return await asyncio.to_thread(self._render_fn, kind, vm, self._card_dir)
        except DemiaogeError:
            raise
        except Exception:
            raise DemiaogeError(ErrorCode.RENDER_FAILED, RENDER_FAILED_MESSAGE) from None

    @staticmethod
    def _default_render(kind: str, vm: Any, cache_dir: Path) -> Path:
        renderer = _DEFAULT_RENDERERS.get(kind)
        if renderer is None:
            raise ValueError(f"unknown card kind: {kind}")
        return renderer(vm, cache_dir)
