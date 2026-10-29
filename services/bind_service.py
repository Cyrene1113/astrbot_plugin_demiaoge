"""扫码绑定流程服务：单步状态机 + 凭据落盘（轮询循环由 main 层命令生成器驱动）。

包装 MihoyoQrAuth 单步原语（api_notes §5 状态机固定文案）：
- ``step_create``：创建二维码 → (ticket, url, png|None, 降级文本|None)；
- ``step_poll``：单次轮询 → (status, bundle|None, 终止文案|None)；
  Created/Scanned 返回终止文案 None 由调用方继续轮询（Scanned 提示一次）；
- ``finish_bind``：store.bind 落盘 → 固定成功文案。
Timeout（90 次 × 2s）由 main 层轮询循环计数产生，文案常量也集中在本模块。

禁止 import astrbot；store 只需实现 ``bind(owner_id, alias, cookie, uid, bind_type,
stoken, mid)``（CredentialStore 已满足）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..adapters.mihoyo_auth import CookieBundle, MihoyoQrAuth
from ..adapters.qr_image import qr_png_bytes
from ..domain.errors import DemiaogeError, ErrorCode
from ..render.engine import sanitize_cache_key

# 固定文案（api_notes §5 扫码状态机，逐字使用）。
QR_HINT_TEXT = "请用米游社App扫描二维码：App → 我的 → 右上角扫一扫"
SCANNED_TEXT = "已扫码，请在手机上确认。"
EXPIRED_TEXT = "二维码已失效，请重新发送 绑定。"
CANCELLED_TEXT = "已取消扫码。"
RISK_TEXT = "触发了安全验证，请稍后再试。"
TIMEOUT_TEXT = "绑定超时，请重新发送 绑定。"
QR_FALLBACK_TEXT = "二维码生成失败，请直接打开链接登录：{url}"
NO_STORE_MESSAGE = "未配置凭据加密主密钥，绑定功能不可用。"
EMPTY_CREDENTIAL_MESSAGE = "登录成功但未取得有效凭据，请重试。"

# 轮询节奏（DEVELOPMENT.md §2：180s 超时）。
POLL_INTERVAL_SECONDS = 2
POLL_MAX_TIMES = 90


class QrBindSession:
    """一次扫码绑定的单步状态机；每次实例对应一次 ``/hsr 扫码`` 会话。"""

    def __init__(self, auth: MihoyoQrAuth, store: Any, request_id: str = "") -> None:
        self._auth = auth
        self._store = store
        self._request_id = request_id
        self.ticket = ""
        self.url = ""

    async def step_create(self) -> tuple[str, str, bytes | None, str | None]:
        """创建二维码 → (ticket, url, png_bytes|None, 降级文本|None)。

        qr_png_bytes（CPU 二维码编码）放 to_thread 不占事件循环；
        失败（None）时降级为文本：携带登录 URL 的固定文案。
        create_login 的 DemiaogeError（固定文案"二维码生成失败，请稍后再试。"）原样上抛。
        """
        ticket, url = await self._auth.create_login(self._request_id)
        self.ticket, self.url = ticket, url
        png = await asyncio.to_thread(qr_png_bytes, url)
        if png is not None:
            return ticket, url, png, None
        return ticket, url, None, QR_FALLBACK_TEXT.format(url=url)

    @staticmethod
    def save_qr_png(png: bytes, qr_dir: Path, ticket: str) -> Path:
        """二维码 bytes 落盘（.tmp + replace 原子写），返回可发送的文件路径。

        AstrBot ``image_result`` 只收路径字符串；调用方自行 to_thread。
        """
        qr_dir = Path(qr_dir)
        qr_dir.mkdir(parents=True, exist_ok=True)
        target = qr_dir / f"qr_{sanitize_cache_key(ticket)[:24]}.png"
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_bytes(png)
        tmp.replace(target)
        return target

    async def step_poll(self, ticket: str) -> tuple[str, CookieBundle | None, str | None]:
        """单次轮询 → (status, bundle|None, 终止文案|None)。

        - Confirmed → (status, bundle, None)；
        - Expired/Cancelled/Risk → 各回 api_notes §5 固定文案并终止；
        - Created/Scanned → 终止文案 None，调用方继续轮询（Scanned 提示一次）。
        """
        result = await self._auth.query_login(ticket, self._request_id)
        status = result.status
        if status == "Confirmed":
            if result.cookies is not None:
                return status, result.cookies, None
            # Confirmed 却没解析到任何 cookie/user_info：按风控处理，不透传细节。
            return "Risk", None, RISK_TEXT
        if status == "Expired":
            return status, None, EXPIRED_TEXT
        if status == "Cancelled":
            return status, None, CANCELLED_TEXT
        if status == "Risk":
            return status, None, RISK_TEXT
        return status, None, None  # Created / Scanned → 继续轮询

    def finish_bind(self, owner_id: str, alias: str, bundle: CookieBundle) -> str:
        """凭据落盘 → 固定成功文案「绑定成功：<别名>（UID:xxx，凭据已加密保存）」。

        cookie 用 bundle.as_cookie_header() 整串加密存储；stoken/mid 分开传。
        """
        if self._store is None:
            raise DemiaogeError(ErrorCode.STORAGE_FAILED, NO_STORE_MESSAGE, self._request_id)
        cookie = bundle.as_cookie_header()
        uid = bundle.stuid or bundle.ltuid
        if not cookie.strip() or not uid:
            raise DemiaogeError(ErrorCode.AUTH_MISSING, EMPTY_CREDENTIAL_MESSAGE, self._request_id)
        self._store.bind(owner_id, alias, cookie, uid=uid, bind_type="qr",
                         stoken=bundle.stoken, mid=bundle.mid)
        return f"绑定成功：{alias}（UID:{uid}，凭据已加密保存）"
