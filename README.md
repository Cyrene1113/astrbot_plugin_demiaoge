# astrbot_plugin_demiaoge 德谬歌

崩坏：星穹铁道查询插件（v0.4.1）。UID/扫码绑定、角色练度面板图与 Wiki 查询，全部固定文案模板 + 固定字段映射，零 LLM 参与。

## 功能列表

- **UID 绑定**：`/hsr 绑定 <UID> [别名]`，免 Cookie 直查；每人最多 5 个账号、同 UID 自动去重、`/hsr 切换` 设置当前账号；凭据按发送者隔离、加密落盘。
- **扫码绑定**：`/hsr 扫码` 生成米游社登录二维码，手机确认后换取 stoken/cookie_token 加密保存（180 秒内有效）。
- **面板总览图**：`/hsr 面板`，玩家信息 + 角色列表（等级/E 数/命途/元素/光锥）。
- **练度统计图**：`/hsr 练度`，全部角色头像网格（按等级/E 数排序，5 星金框 4 星紫框）。
- **角色详情图**：`/hsr 角色 <名称>`，属性/技能/光锥/遗器/套装完整大图。
- **光锥资料图**：`/hsr 光锥 <名称>`，资料 + 叠影效果 + 持有者列表（带 UID/别名时）。
- **实时便签（体力）**：`/hsr 体力` 查询本人开拓力/委托/每日实训/周本，**只查自己的账号**（需扫码绑定）。
- **Wiki 查询**：`/hsr wiki <名称> [--image]`，本地静态资料（角色含技能/星魂、光锥、遗器）文字或图片卡片。
- **每日数据核对**：每天固定时间自动从 BWiki 拉取最新资料，校验清洗（剔除占位/空白条目）后与本地核对入库；管理员可 `/hsr 更新数据` 立即触发。
- **HTTP 端口**：插件自带 aiohttp 只读端点，按 UID 返回练度 JSON / 面板 PNG。
- 图片渲染：HTML 模板 → Microsoft Edge 无头截图 + **高度自适应裁剪**（成图与内容实际长度一致，无黑边不截断），官方风格字体 + 元素图标 + 星空底图（素材见 `data/assets/ASSETS_CREDITS.md`），TTL 数据缓存 + 内容哈希成图缓存（超期 PNG 每日自动回收）。

## 命令

与 `/hsr help` 输出逐字一致（`main.py` HELP_TEXT）：

```text
德谬歌 · 崩坏：星穹铁道查询
/hsr help（帮助）- 查看本帮助
/hsr 绑定 <UID> [别名] - 绑定 UID（别名缺省 default，可多账号，上限 5 个）
/hsr 切换 <别名> - 切换当前使用账号
/hsr 扫码 - 米游社扫码绑定（180 秒内确认有效，凭据加密保存）
/hsr 我的绑定 - 查看全部绑定（★ 为当前使用）
/hsr 解绑 [别名] - 删除绑定（缺省 default）
/hsr 面板 [UID|别名] - 面板总览图
/hsr 练度 [UID|别名] - 全角色练度统计图
/hsr 角色 <名称> [UID|别名] - 单角色详情图
/hsr 光锥 <名称> [UID|别名] - 光锥资料图（带 UID/别名时附持有者）
/hsr 体力 - 查询本人开拓力与委托（需扫码绑定，仅查自己的账号）
/hsr wiki <名称> [--image] - Wiki 查询（--image 输出图片卡片）
/hsr 更新缓存 - 管理员：清空面板数据缓存与成图缓存
/hsr 更新数据 - 管理员：立即与 BWiki 核对 Wiki 数据并入库（每日定时自动执行，时间可在配置调整）
```

UID 优先级：显式参数 > 本人 `当前账号` 指针（`/hsr 切换`）> `default` 绑定。兼容旧别名：`profile`/`panel` → 面板；`bind` → 新绑定方式说明。

绑定隔离与防串号：绑定数据按**消息发送者 ID** 一级隔离，任何人只能看到/操作自己的账号；`/hsr 体力` 一类需要凭据的命令只接受发送者本人的扫码凭据，命令参数**无法指定他人账号**。

## 配置项

与 `_conf_schema.json` 一致：

| 配置项 | 类型 | 说明 | 默认值 |
|---|---|---|---|
| `adapter` | string | 数据适配器（mihomo=线上 Mihomo API；mock=离线调试） | `mihomo` |
| `master_key` | string | 凭据加密主密钥；留空则读环境变量 `DEMIAOGE_MASTER_KEY`，未配置时绑定功能禁用 | `""` |
| `http_enabled` | bool | 启用公共查询端口 | `true` |
| `http_host` | string | HTTP 监听地址 | `127.0.0.1` |
| `http_port` | int | HTTP 端口（`/hsr/profile` 与 `/hsr/profile.png`） | `8765` |
| `cache_ttl_minutes` | int | 面板数据缓存分钟（同 UID 查询在 TTL 内直接用缓存） | `10` |
| `edge_path` | string | Edge 浏览器路径（留空自动探测；也可用环境变量 `DEMIAOGE_EDGE`） | `""` |
| `admins` | list | 管理员 ID 列表（可用 `/hsr 更新缓存`、`/hsr 更新数据`） | `[]` |
| `auto_update` | bool | 每日自动核对 Wiki 数据（失败自动保留本地） | `true` |
| `auto_update_time` | string | 每日核对时间 HH:MM（24 小时制） | `04:30` |

## HTTP 端点

`initialize()` 时启动 aiohttp（默认 `127.0.0.1:8765`，`http_host`/`http_port` 可改；端口被占仅告警不阻塞插件加载）：

- `GET /hsr/profile?uid=<UID>` → 练度 JSON：`{player, characters:[{name, level, eidolon, path, element, light_cone}]}`，仅公开数据，无任何凭据输出。
- `GET /hsr/profile.png?uid=<UID>` → 面板总览 PNG（`image/png`）。
- 错误统一 JSON：缺 uid → 400 `{"error":"missing uid"}`；查不到或未公开 → 404 `user_not_found_or_not_public`；上游异常 → 502 `upstream`。
- 只读端点；对外网暴露请自行评估风险（默认仅本机监听）。

## 数据来源与致谢

- **面板数据**：[Mihomo API](https://api.mihomo.me)（`api.mihomo.me`，MetaCubeX/mihomo 官方 ASSET），免 Cookie，需对方游戏内开启「角色展示」。
- **图标资源**：[StarRailRes](https://github.com/Mar-7th/StarRailRes)，按需下载缓存到 `data/icons/`。下载源多路回退（jsDelivr 三镜像 → raw.githubusercontent.com），首次查询当场下载并落盘（限时 8 秒，超时出占位图不阻塞），之后全部走本地缓存。
- **静态资料**：BWiki（崩坏：星穹铁道官方 WIKI）。插件每日定时全量核对（限速 + 抖动 + 校验清洗），也可 `/hsr 更新数据` 手动触发或 `python scripts/fetch_wiki.py` 手动执行；同步审计在 `data/wiki_sync_audit.json`。
- **设计对标**：云崽插件 [xiaoyao-cvs](https://github.com/ctrlcvs/xiaoyao-cvs)（扫码登录流程）与 [miao-plugin](https://github.com/yoimiya-kokomi/miao-plugin)（UID 直查/面板卡片理念）。
- 本插件为独立实现，与上述项目无代码依赖；仅极少量字段映射参考其公开源码，详见 `docs/api_notes.md`。

## 测试

从插件父目录 `C:\Users\14476\.astrbot\data\plugins` 运行：

```text
python -m pytest -q astrbot_plugin_demiaoge/
```

全部用例离线（网络一律 MockTransport/monkeypatch）；`test_sync_data.py` 依赖工作区原始爬取数据，路径不存在时自动 skip。渲染验收脚本（真 Edge，产出 4 张图到 `data/render_v4_acceptance/`）：

```text
python astrbot_plugin_demiaoge/scripts/acceptance_v4.py
```

## 已知限制

- **图标占位**：成图命令在关键路径限时 8 秒解析图标（jsDelivr 多源下载），超时或全部源不可达时对应图标回退占位灰块，不阻塞出图；负缓存 10 分钟内不重复尝试。网络恢复后直接重查即可补齐（本地缓存优先，无需清空 `data/icons/`）。
- **扫码需真机**：`/hsr 扫码` 需真实米游社 App 扫码确认，180 秒超时/过期/取消/风控各有固定文案；未实网验证完整 stoken 兑换链路。
- **salt 轮换风险**：DS 签名 salt 与扫码端点取自开源实现核实值，米哈游可能随版本轮换；权威记录与探测方法见 `docs/api_notes.md`，失效时按该文档更新 `adapters/ds.py` 与 `adapters/mihoyo_auth.py`。
- UID 绑定不存 Cookie（凭据字段为占位值）；米游社 game_record Cookie 路径仅作 Mihomo 失败且有扫码凭据时的降级。
