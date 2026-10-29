from pathlib import Path
import runpy
import sys

import pytest

# 数据同步依赖工作区原始爬取数据（本机维护窗口产物）；该路径不存在时跳过，
# 不影响其余离线测试（既有环境问题，W4 起以 skipif 显式标注而非报失败）。
_WIKI_SOURCE = Path(r"C:\Users\14476\.astrbot\data\workspaces\_FriendMessage_1447653277\hsr_wiki_data")

pytestmark = pytest.mark.skipif(
    not _WIKI_SOURCE.exists(),
    reason=f"工作区 Wiki 原始数据不存在（{_WIKI_SOURCE}），仅在维护窗口所在环境执行",
)


def test_sync_verified_wiki_data():
    source = _WIKI_SOURCE
    output = Path(__file__).parent / "data"
    sys.argv = ["convert_wiki", "--source", str(source), "--output", str(output)]
    runpy.run_module("scripts.convert_wiki", run_name="__main__")
    for name in ("characters.json", "light_cones.json", "relics.json"):
        assert (output / name).exists()
