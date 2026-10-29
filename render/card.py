"""轻量角色列表卡片渲染器。

Pillow 可用时输出 PNG 字节；不可用时提供 ASCII 兜底，不让查询功能失效。
"""

from __future__ import annotations

from io import BytesIO

from .viewmodel import ProfileCardViewModel

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - 由运行环境决定
    Image = ImageDraw = ImageFont = None  # type: ignore[assignment]


def pillow_available() -> bool:
    return Image is not None


def render_profile_image(view: ProfileCardViewModel):
    """绘制角色列表卡片并返回 PIL.Image.Image；无 Pillow 时返回 None。"""
    if Image is None or ImageDraw is None:
        return None
    row_height = 62
    width = 760
    height = 150 + max(1, len(view.characters)) * row_height
    image = Image.new("RGB", (width, height), (22, 27, 43))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default() if ImageFont else None
    draw.rectangle((18, 18, width - 18, height - 18), fill=(31, 39, 61), outline=(90, 112, 155), width=2)
    draw.text((42, 36), f"星穹铁道角色面板 · {view.nickname}", fill=(235, 240, 255), font=font)
    draw.text((42, 68), f"{view.uid_text}    {view.trailblaze_level_text}", fill=(170, 190, 220), font=font)
    y = 112
    for index, character in enumerate(view.characters):
        fill = (42, 52, 78) if index % 2 == 0 else (36, 45, 69)
        draw.rounded_rectangle((36, y, width - 36, y + row_height - 8), radius=8, fill=fill)
        draw.text((54, y + 16), character.name, fill=(250, 250, 255), font=font)
        draw.text((300, y + 16), character.level_text, fill=(190, 210, 238), font=font)
        draw.text((410, y + 16), character.eidolon_text, fill=(238, 202, 117), font=font)
        draw.text((520, y + 16), character.rarity_text, fill=(255, 214, 120), font=font)
        y += row_height
    return image


def image_to_png_bytes(image) -> bytes:
    if image is None:
        raise RuntimeError("Pillow 不可用")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def render_profile_ascii(view: ProfileCardViewModel) -> str:
    lines = [f"星穹铁道角色面板 · {view.nickname}", f"{view.uid_text} | {view.trailblaze_level_text}", "=" * 40]
    lines.extend(f"{c.name}：{c.level_text}，{c.eidolon_text}，{c.rarity_text}" for c in view.characters)
    return "\n".join(lines)
