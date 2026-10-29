from __future__ import annotations

import json
import time
from pathlib import Path

from PIL import Image

from astrbot_plugin_demiaoge.render.html_card import render_entry
from astrbot_plugin_demiaoge.services.wiki_service import WikiService


def test_render_acceptance() -> None:
    root = Path(__file__).parent
    data = root / "data"
    output = data / "render_acceptance"
    output.mkdir(exist_ok=True)
    service = WikiService([data / "characters.json", data / "light_cones.json", data / "relics.json", data / "wiki.json"])
    character = service._exact_entry("昔涟")
    light_cone = service._exact_entry("爱如此刻永恒")
    assert character is not None, "missing character"
    assert light_cone is not None, "missing light cone"
    assert len(character.skills) >= 4 and len(character.eidolons) >= 3, (len(character.skills), len(character.eidolons))
    assert light_cone.skills and "速度提高" in light_cone.skills[0][1], light_cone.skills
    measurements = {}
    for entry in (character, light_cone):
        target = output / f"{entry.category}_{entry.name}.png"
        target.unlink(missing_ok=True)
        started = time.perf_counter()
        try:
            render_entry(entry, output)
        except Exception as exc:
            print("render_error", type(exc).__name__, repr(exc))
            raise
        cold = time.perf_counter() - started
        started = time.perf_counter()
        render_entry(entry, output)
        cached = time.perf_counter() - started
        with Image.open(target) as image:
            width, height = image.size
            pixels = image.convert("RGB").getdata()
            dark_ratio = sum(1 for pixel in pixels if max(pixel) < 12) / (width * height)
        assert width >= 760 and 220 <= height <= 3200
        assert dark_ratio < 0.35
        measurements[entry.name] = {"path": str(target.resolve()), "cold_seconds": cold, "cached_seconds": cached, "size": [width, height], "dark_ratio": dark_ratio}
    (output / "metrics.json").write_text(json.dumps(measurements, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(measurements, ensure_ascii=False))
