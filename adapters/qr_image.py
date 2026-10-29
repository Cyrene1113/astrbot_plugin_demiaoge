"""二维码 PNG 生成（扫码绑定的图片输出）。

优先使用 ``qrcode`` 库（PIL 图像工厂，白边用默认 border=4，box_size=8 保证扫得清）。
任何失败（未安装 / 生成异常）返回 ``None``，调用方降级为文本发送 URL。
"""

from __future__ import annotations

import io

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def qr_png_bytes(content: str, box_size: int = 8) -> bytes | None:
    """内容 → PNG 二维码字节；失败返回 None（调用方降级为文本 URL）。"""
    if not content:
        return None
    try:
        import qrcode

        image = qrcode.make(content, box_size=max(8, int(box_size)))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        data = buffer.getvalue()
        return data if data.startswith(PNG_SIGNATURE) else None
    except Exception:  # ImportError / 生成异常一律降级，绝不阻塞主流程
        return None
