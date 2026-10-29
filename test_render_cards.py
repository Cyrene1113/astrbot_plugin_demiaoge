"""W1-B 渲染卡片测试。

覆盖：
1. 四个模板 build_html 纯断言（关键文本、排序、折叠、html.escape 注入防护），无需 Edge。
2. Edge 截图验收：PNG 签名/体积/尺寸、缓存命中二次耗时下降，产物写
   data/render_cards_acceptance/ 供人工查看。Edge 缺失时整块 skip。

运行（父目录执行）：python -m pytest -q astrbot_plugin_demiaoge/test_render_cards.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from PIL import Image
import pytest

from astrbot_plugin_demiaoge.render import audit_card, character_card, lc_card, note_card, panel_card
from astrbot_plugin_demiaoge.render.engine import find_edge
from astrbot_plugin_demiaoge.render.v2_models import (
    AuditRow,
    AuditVM,
    CharacterVM,
    ExpeditionVM,
    NoteVM,
    LightConeOwnerVM,
    LightConeRef,
    LightConeSkillVM,
    LightConeVM,
    PanelRow,
    PanelVM,
    RelicSetVM,
    RelicVM,
    SkillRow,
    StatRow,
    SubAffix,
)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
OUTPUT = Path(__file__).parent / "data" / "render_cards_acceptance"
SCRIPT = "<script>alert(1)</script>"

requires_edge = pytest.mark.skipif(not find_edge(), reason="未找到 Microsoft Edge，跳过 Edge 截图验收")


def _panel_vm() -> PanelVM:
    """2 个 5 星 + 3 个 4 星角色，含长光锥名与 `<script>` 注入样例。"""
    return PanelVM(
        uid="100000001",
        nickname="汐涟",
        level=70,
        world_level=6,
        characters=(
            PanelRow("昔涟", "", 80, 6, 5, "记忆", "冰", "#4fc2f8", "爱如此刻永恒", 80, 5, ""),
            PanelRow("长夜月", "", 80, 1, 5, "毁灭", "物理", "#d97b8c", "记一位星神的陨落（超长光锥名称用于测试换行估算）", 70, 4, ""),
            PanelRow("三月七", "", 70, 6, 4, "存护", "冰", "#4fc2f8", "朗道的选择", 60, 4, ""),
            PanelRow("停云", "", 70, 0, 4, "谐乐", "雷", "#df6cf9", "但战斗还未结束", 60, 4, ""),
            PanelRow(f"镜流{SCRIPT}", "", 60, 0, 4, "毁灭", "冰", "#4fc2f8", "于夜色中", 50, 3, ""),
        ),
    )


def _audit_vm() -> AuditVM:
    """6 个角色（4 列网格恰好 2 行），预期排序 等级↓→E↓→稀有度↓。"""
    return AuditVM(
        uid="100000002",
        nickname="汐涟的练度",
        rows=(
            AuditRow("昔涟", "", 80, 6, 5, "记忆", "冰", "#4fc2f8"),
            AuditRow("长夜月", "", 80, 1, 5, "毁灭", "物理", "#d97b8c"),
            AuditRow("三月七", "", 70, 6, 4, "存护", "冰", "#4fc2f8"),
            AuditRow("丹恒", "", 75, 2, 4, "巡猎", "风", "#6fe0d4"),
            AuditRow("停云", "", 70, 0, 4, "谐乐", "雷", "#df6cf9"),
            AuditRow(f"镜流{SCRIPT}", "", 60, 0, 4, "毁灭", "冰", "#4fc2f8"),
        ),
    )


def _character_vm() -> CharacterVM:
    """9 行属性 + 5 条技能 + 光锥 + 8 件遗器（超 6 件折叠）+ 3 条套装；副词条含注入样例。"""
    return CharacterVM(
        name="昔涟",
        avatar_path="",
        rarity=5,
        level=80,
        promotion=6,
        eidolon=6,
        path_name="记忆",
        element_name="冰",
        element_color="#4fc2f8",
        stats=(
            StatRow("生命值", "1023", "1554"),
            StatRow("攻击力", "602", "913"),
            StatRow("防御力", "485", "736"),
            StatRow("速度", "96", "134"),
            StatRow("暴击率", "5.0%", "35.2%"),
            StatRow("暴击伤害", "50.0%", "160.0%"),
            StatRow("效果命中", "0%", "10.5%"),
            StatRow("效果抵抗", "0%", "12.0%"),
            StatRow("能量恢复效率", "100%", "111.1%"),
        ),
        skills=(
            SkillRow("致睡眠的温柔摇篮曲（超长普攻名称测试换行）", 6, 7, "普攻"),
            SkillRow("冰激凌的奇袭", 8, 12, "战技"),
            SkillRow("眠眠集会", 5, 5, "终结技"),
            SkillRow("睡美人", 9, 10, "天赋"),
            SkillRow("困了", 1, 1, "秘技"),
        ),
        light_cone=LightConeRef("爱如此刻永恒", 80, 1, 5, ""),
        relics=(
            RelicVM("晨昏交界的眸光之颈", 15, 5, "", "暴击伤害", "64.8%", (SubAffix("暴击率", "8.6%"), SubAffix("速度", "4"), SubAffix("攻击力", "12.3%"), SubAffix("生命值", "269"))),
            RelicVM("晨昏交界的眸光之手", 15, 5, "", "攻击力", "43.2%", (SubAffix("暴击伤害", "15.3%"), SubAffix("效果抵抗", "8.1%"), SubAffix("击破特攻", "12.4%"), SubAffix(f"速度{SCRIPT}", "4"))),
            RelicVM("沉陷沙海的默语之躯（超长遗器名称测试换行显示）", 12, 4, "", "效果命中", "28.0%", (SubAffix("速度", "5"), SubAffix("暴击率", "7.1%"))),
            RelicVM("沉陷沙海的默语之足", 15, 5, "", "速度", "25.0%", ()),
            RelicVM("折断的歌声", 9, 4, "", "生命值", "33.6%", (SubAffix("防御力", "54"),)),
            RelicVM("苍穹的帷幕", 6, 5, "", "能量恢复效率", "19.4%", ()),
            RelicVM("第七件不展示", 15, 5, "", "攻击力", "34.5%", ()),
            RelicVM("第八件不展示", 15, 4, "", "防御力", "40.1%", ()),
        ),
        relic_sets=(
            RelicSetVM("晨昏交界的眸光", 2),
            RelicSetVM("沉陷沙海的默语", 2),
            RelicSetVM("折断的歌声", 2),
        ),
    )


def _lc_vm() -> LightConeVM:
    """光锥资料 + 2 条技能 + 2 位持有者（其中 1 位名字带注入样例）。"""
    return LightConeVM(
        name="爱如此刻永恒",
        rarity=5,
        path_name="毁灭",
        description="使装备者的暴击伤害提高60%。当装备者当前暴击伤害大于等于180%时，战斗中使其暴击伤害额外提高36%（此处为一段非常长的描述文本，用于验证中文字数换行估算与溢出保护是否生效，重复一遍以加长：当装备者当前暴击伤害大于等于180%时，战斗中使其暴击伤害额外提高36%）。",
        skills=(
            LightConeSkillVM("约定", "当装备者施放攻击后，使装备者的暴击伤害提高24%，持续2回合；该效果对装备者自身的终结技伤害额外生效。"),
            LightConeSkillVM("叠影效果", "叠影等级越高，上述暴击伤害加成越高（叠影1：24%，叠影2：28%，叠影3：32%，叠影4：36%，叠影5：40%）。此处同样放一段长文本验证换行与高度估算。"),
        ),
        owners=(
            LightConeOwnerVM("昔涟", 80, 1, 6, ""),
            LightConeOwnerVM(f"镜流{SCRIPT}", 80, 2, 1, ""),
        ),
    )


def test_panel_build_html() -> None:
    html = panel_card.build_html(_panel_vm())
    assert html.startswith("<!doctype html>")
    for text in ("汐涟", "UID 100000001", "开拓等级 70", "世界等级 6", "角色 5", "昔涟", "长夜月", "三月七", "停云", "镜流", "爱如此刻永恒", "Lv.80 · E6", "角色展示"):
        assert text in html, text
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_audit_build_html() -> None:
    html = audit_card.build_html(_audit_vm())
    assert "汐涟的练度" in html and "已收录角色 6" in html
    assert "cell cell-r5" in html and "cell cell-r4" in html
    # 排序固定：等级↓ → E↓ → 稀有度↓
    order = ["昔涟", "长夜月", "丹恒", "三月七", "停云", "镜流"]
    positions = [html.index(name) for name in order]
    assert positions == sorted(positions), positions
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_character_build_html() -> None:
    html = character_card.build_html(_character_vm())
    for text in ("昔涟", "属性（基础 → 最终）", "1554", "160.0%", "111.1%", "技能", "Lv.5/5", "爱如此刻永恒", "叠影 1", "遗器", "64.8%", "+2 件", "套装", "晨昏交界的眸光 ×2"):
        assert text in html, text
    # 超 6 件折叠：第 7/8 件不得出现
    assert "第七件不展示" not in html and "第八件不展示" not in html
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_lc_build_html() -> None:
    html = lc_card.build_html(_lc_vm())
    for text in ("爱如此刻永恒", "命途 · 毁灭", "光锥描述", "约定", "叠影效果", "持有者", "Lv.80 · 叠影 1 · E6"):
        assert text in html, text
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_lc_build_html_without_owners() -> None:
    vm = LightConeVM(name="记忆中的模样", rarity=4, path_name="记忆", description="纯资料卡，不展示任何角色。", skills=(LightConeSkillVM("效果", "描述"),), owners=())
    html = lc_card.build_html(vm)
    assert "记忆中的模样" in html and '<div class="title">持有者</div>' not in html



def test_note_card_html_escapes_and_hides_missing_sections() -> None:
    """体力卡：名称注入转义；上游缺失的实训/周本区块不渲染；满体力文案。"""
    vm = NoteVM(uid="100000001", current_stamina=240, max_stamina=240, recover_seconds=0,
                accepted_expedition_num=1, total_expedition_num=4,
                expeditions=(ExpeditionVM("<script>x</script>", "已完成", True),))
    html = note_card.build_html(vm)
    assert "<script>x</script>" not in html and "&lt;script&gt;" in html
    assert "每日实训" not in html and "每周模拟宇宙" not in html
    assert "开拓力已满" in html and "bar-full" in html


def test_note_card_html_shows_progress_sections() -> None:
    vm = _note_vm()
    html = note_card.build_html(vm)
    assert "每日实训" in html and "每周模拟宇宙" in html
    assert "距离回满" in html and "剩余 01:23:45" in html


@requires_edge
def test_render_png_acceptance() -> None:
    """四张卡冷渲染 → PNG 签名/体积/尺寸断言 → 缓存命中二次耗时下降；产物留档人工查看。"""
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for png in OUTPUT.glob("*.png"):
        png.unlink()
    cases = [
        ("panel", _panel_vm(), panel_card),
        ("audit", _audit_vm(), audit_card),
        ("character", _character_vm(), character_card),
        ("lc", _lc_vm(), lc_card),
        ("note", _note_vm(), note_card),
    ]
    metrics = {}
    for label, vm, module in cases:
        started = time.perf_counter()
        png_path = module.render_to_path(vm, OUTPUT)
        data = png_path.read_bytes()
        cold = time.perf_counter() - started
        assert data[:8] == PNG_SIGNATURE, f"{label}: PNG 签名不符"
        assert len(data) > 5 * 1024, f"{label}: 体积仅 {len(data)} 字节"
        started = time.perf_counter()
        cached_path = module.render_to_path(vm, OUTPUT)
        cached = time.perf_counter() - started
        assert cached_path == png_path and cached_path.read_bytes() == data
        assert cached < cold, f"{label}: 缓存命中 {cached:.3f}s 应低于冷渲染 {cold:.3f}s"
        with Image.open(png_path) as image:
            width, height = image.size
        assert width in (panel_card.WINDOW_WIDTH, character_card.WINDOW_WIDTH,
                         note_card.WINDOW_WIDTH), (label, width)
        assert 240 <= height <= 4000, (label, width, height)
        metrics[label] = {"cold_seconds": round(cold, 3), "cached_seconds": round(cached, 3), "bytes": len(data), "size": [width, height]}
    (OUTPUT / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False))


def _note_vm() -> NoteVM:
    return NoteVM(uid="100000001", current_stamina=137, max_stamina=240, recover_seconds=7020,
                  accepted_expedition_num=4, total_expedition_num=4,
                  expeditions=(ExpeditionVM("奖励委托", "已完成", True),
                               ExpeditionVM("探索委托", "剩余 01:23:45", False)),
                  daily_train_score=500, daily_train_max=500,
                  weekly_rogue_count=2, weekly_rogue_max=2)


# ---------- W8 · 样式回归 ----------


def test_document_css_order_assets_after_base() -> None:
    """W8 回归：素材 CSS 必须拼在 BASE_CSS 之后——此前顺序颠倒，.page 星空底图
    被 BASE_CSS 同名规则覆盖，美化从未真正生效。"""
    from astrbot_plugin_demiaoge.render import style

    html = style.document("<main></main>")
    base_index = html.find(".page{padding:18px")
    asset_index = html.find(".page{background:")
    assert base_index != -1 and asset_index != -1
    assert asset_index > base_index
    # 自定义字体注入在 BASE_CSS 之后（html,body 的纯色背景同理被素材层覆盖）
    assert html.find("@font-face") > html.find("html,body{margin:0")


def test_page_bg_css_missing_file_returns_empty(tmp_path) -> None:
    from astrbot_plugin_demiaoge.render.style import page_bg_css

    assert page_bg_css(tmp_path / "ghost.png") == ""
    bg = tmp_path / "bg.png"
    bg.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    css = page_bg_css(bg)
    assert css.startswith(".page{background:") and "center/cover" in css
