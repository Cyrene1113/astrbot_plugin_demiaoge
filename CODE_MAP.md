# 德谬歌项目 · 代码地图

> 建立时间：2026-08-06 22:05（CST）
> 最后更新：2026-10-27（W8：图标多源补齐 + W7 美化失效修复 + 缓存自动回收 + 渲染提速）
> 用途：任何 agent 接手本项目时，先读本地图再动手，不必从头翻文件。
> 配合使用：规格权威 `DEVELOPMENT.md`，波次过程记录 `docs/wave_notes.md`，上游 API 权威笔记 `docs/api_notes.md`。

## 一、一句话总览

德谬歌 = 「崩坏：星穹铁道查询插件」v0.4.1：UID/扫码绑定（凭据加密落盘）→ Mihomo API 免 Cookie 直查 → 固定字段映射 → HTML 模板 + Edge 无头截图产出面板/练度/角色/光锥/便签五种卡片，另带本地 Wiki 查询与只读 HTTP 查询端口。全程纯机械固定流程，零 LLM 参与。

## 二、路径速查

| 角色 | 路径 |
|---|---|
| 插件本体 | `C:\Users\14476\.astrbot\data\plugins\astrbot_plugin_demiaoge\` |
| 旧版骨架（勿再改） | `C:\Users\14476\.astrbot\data\plugins\astrbot_plugin_seashell\` |
| 开发档案（规格权威） | 插件目录 `DEVELOPMENT.md` |
| 波次过程记录 | 插件目录 `docs/wave_notes.md`（W1-A/W2/W3/W4） |
| 上游 API 权威笔记 | 插件目录 `docs/api_notes.md`（fixtures 为证据） |
| 本代码地图 | 插件目录 `CODE_MAP.md`（本文件） |

## 三、插件本体结构（astrbot_plugin_demiaoge）

模块化分层：`main.py` 入口（唯一 import astrbot 的文件）→ adapters（数据源） / domain（模型） / services（业务） / render（渲染） / storage（凭据） / scripts（维护） / data（数据）。

### 命令入口（main.py，421 行，DemiaogePlugin，@register 版本 0.4.0）

命令表与 `/hsr help`（HELP_TEXT）逐字一致：

| 命令 | 说明 | 主要依赖 |
|---|---|---|
| `/hsr help`（帮助） | 查看本帮助 | - |
| `/hsr 绑定 <UID> [别名]` | 绑定 UID（别名缺省 default；每人上限 5、同 UID 去重、新增自动设为当前） | CredentialStore / uid_resolver |
| `/hsr 切换 <别名>` | 切换本人当前使用账号（防串号配套） | CredentialStore.set_current |
| `/hsr 扫码` | 米游社扫码绑定（180 秒内确认有效，凭据加密保存） | MihoyoQrAuth / QrBindSession |
| `/hsr 我的绑定` | 查看全部绑定 | CredentialStore |
| `/hsr 解绑 [别名]` | 删除绑定（缺省 default） | CredentialStore |
| `/hsr 面板 [UID\|别名]` | 面板总览图 | PanelService / panel_card |
| `/hsr 练度 [UID\|别名]` | 全角色练度统计图 | PanelService / audit_card |
| `/hsr 体力` | 实时便签图（开拓力/委托/实训/周本；**仅本人扫码凭据**） | PanelService.note_png / note_card / MihoyoRecordClient.fetch_note |
| `/hsr 角色 <名称> [UID\|别名]` | 单角色详情图 | PanelService / character_card |
| `/hsr 光锥 <名称> [UID\|别名]` | 光锥资料图（带 UID/别名时附持有者） | PanelService / lc_card |
| `/hsr wiki <名称> [--image]` | Wiki 查询（--image 输出图片卡片） | WikiService / html_card |
| `/hsr 更新缓存` | 管理员：清空面板数据缓存与成图缓存 | ProfileCache |
| `/hsr 更新数据` | 管理员：立即与 BWiki 核对 Wiki 数据并入库（每日定时自动执行） | WikiUpdateService / fetch_wiki |

UID 优先级：显式参数 > 绑定别名 > 本人 default 绑定。兼容旧别名：`profile`/`panel` → 面板；`bind` → 新绑定方式说明（`BIND_MIGRATION_TEXT`）。异常统一转固定文案（`DemiaogeError` → `str(exc)`；其余 → 内部错误 + request_id）。

### 模块职责速查（v0.4 全量）

| 模块 | 文件 | 职责 | 关键符号 |
|---|---|---|---|
| 入口 | `main.py` | 命令分发/固定文案/生命周期（HTTP 启停、每日成图缓存回收）；`_MockMihomoClient` 离线调试 | `DemiaogePlugin` / `HELP_TEXT` / `_card_cache_gc_loop` |
| adapters | `ds.py` | 米游社 DS 签名（md5） | `ds_simple` / `ds_bq` |
| adapters | `mihomo_api.py` | Mihomo API 客户端（免 Cookie 主路径，`GET /sr_info_parsed/{uid}`） | `MihomoApiClient.fetch_parsed` |
| adapters | `mihomo_mapper.py` | 固定字段表映射：payload → PanelVM/AuditVM/CharacterVM | `map_mihomo_payload` / `map_character_detail` / `map_light_cone` / `iter_icon_paths` |
| adapters | `mihoyo_record.py` | 米游社 game_record 降级客户端（DS + Cookie） | `MihoyoRecordClient.fetch_index/fetch_profile/fetch_note` / `resolve_server` |
| adapters | `mihoyo_auth.py` | 米游社扫码登录状态机（passport web 变体） | `MihoyoQrAuth.create_login/query_login/complete_with_stoken` / `CookieBundle` / `QrPollResult` |
| adapters | `icon_cache.py` | StarRailRes 图标下载缓存（**W8 多源回退**：jsDelivr 三镜像 → raw 兜底、sticky 成功源、失败负缓存 10min、共享连接池、PNG 签名校验、重试+超时+原子写） | `IconCache.resolve/resolve_many/local_path/aclose` |
| adapters | `qr_image.py` | 登录二维码 PNG 生成（qrcode 库） | `qr_png_bytes` |
| adapters | `wiki_sources.py` | v0.3 遗留接口骨架（在线源，未接线） | - |
| adapters | `mock_profile.py` / `mapper.py` | v0.3 遗留（mapper 仍被 mihoyo_record.fetch_profile 复用） | `map_profile` / `map_roles` |
| adapters | ~~`mihoyo_profile.py`~~ | 已删除（2026-10-27）：v0.4 未接线的同步 urllib 死代码，违反异步纪律 | - |
| services | `uid_resolver.py` | UID/别名合法性校验与解析（显式参 > current 指针 > default） | `is_valid_uid` / `is_valid_alias` / `resolve_uid` |
| services | `panel_service.py` | 四种成图统一编排：取数（TTL 缓存，磁盘 I/O 走 to_thread）→ **图标关键路径限时解析（8s，超时占位）** → 映射（to_thread）→ 渲染（to_thread）；**返回 PNG 文件路径** | `PanelService.panel_png/audit_png/character_png/light_cone_png/note_png/get_payload` |
| services | `bind_service.py` | 扫码绑定会话（create→poll 2s×90 次→落盘）与固定文案；二维码生成/落盘走 to_thread | `QrBindSession.step_create/step_poll/finish_bind/save_qr_png` |
| services | `http_server.py` | aiohttp 只读查询端口（/hsr/profile、/hsr/profile.png，后者 FileResponse 流式发图） | `HsrHttpServer.start/stop/create_app` / `project_profile` |
| services | `cache_service.py` | 面板 payload 缓存：内存 + 磁盘 `data/profile_cache/{uid}.json`（TTL）；**W8 `clean_card_cache`：成图缓存按 mtime 超期回收（默认 7 天，main 每日跑）** | `ProfileCache.get/put/invalidate` / `clean_card_cache` |
| services | `wiki_service.py` | Wiki 查询核心：精确→别名→包含排序 | `WikiService`（query/search/format_entry） |
| services | `wiki_update_service.py` | 每日定时核对 BWiki：快照→全量拉取清洗入库→差异核对→审计；阻塞爬取走 to_thread | `WikiUpdateService.run_sync_once/schedule_loop/diff_report/format_report` |
| services | `wiki_crawler.py` | 旧增量爬虫（维护窗口手动 CLI，允许同步库） | 命令行脚本 |
| services | `request_context.py` | 请求上下文（request_id） | `RequestContext.create()` |
| services | `profile_service.py` | v0.3 遗留（v0.4 未接线） | - |
| domain | `wiki_models.py` / `alias_models.py` | `WikiEntry` / `AliasTable` | - |
| domain | `models.py` / `errors.py` | 通用模型 / 错误码与业务异常（`.code`/`.message`/`.request_id`） | `ErrorCode` / `DemiaogeError` |
| render | `engine.py` | Edge 无头截图引擎：临时 HTML → 截图 → 原子替换缓存；`content_digest` 内容哈希缓存键；**W8 `render_html_to_png_path`（命中返回路径不读 bytes）**；日志统一 `logging`（demiaoge.render） | `render_html_to_png_path` / `find_edge` / `content_digest` / `sanitize_cache_key` / `HEADLESS_VIEWPORT_CHROME` |
| render | `adaptive.py` | 高度自适应包装：注入洋红哨兵块 → 像素扫描裁掉无头窗口余量（无黑边/无截断，估算过矮自动 2 倍重试）；纯 PIL 无命令执行；**W8 `render_adaptive_to_path`** | `render_adaptive_to_path` / `_crop_to_sentinel` |
| render | `style.py` | 卡片公共 CSS/组件（深蓝风 + 本地素材字体/星空底图/元素图标，缺失自动回退）；**W8 修复 CSS 拼接顺序（素材层必须在 BASE_CSS 之后，否则被同名规则覆盖——W7 美化因此从未生效）**；新增 `page_bg_css` | `document/card/img_tag/stars_html/element_dot/asset_css/page_bg_css/element_icon_path` |
| render | `note_card.py` | 实时便签卡（开拓力进度条 + 委托 + 实训/周本，缺字段自动隐藏）；W8 文件 URI/字体注入复用 style 助手 | `build_html` / `render_to_path` |
| data | `assets/` | W7 本地素材：官方风格字体、七系元素图标、星空底图、体力卡背景（截取自 StarRailUID，见 ASSETS_CREDITS.md；W8 起真正生效） | - |
| render | `v2_models.py` | v0.4 视图模型（11 个 VM dataclass + 占位图标） | `PanelVM` / `AuditVM` / `CharacterVM` / `LightConeVM` / `placeholder_icon` |
| render | `panel_card.py` | 面板总览卡（头部玩家信息 + 角色行） | `build_html` / `render_to_path` / `render` |
| render | `audit_card.py` | 练度统计卡（头像网格，等级→E 排序） | `build_html` / `render_to_path` / `render` |
| render | `character_card.py` | 单角色详情卡（属性/技能/光锥/遗器/套装） | `build_html` / `render_to_path` / `render` |
| render | `lc_card.py` | 光锥资料卡（叠影 + 持有者列表） | `build_html` / `render_to_path` / `render` |
| render | `html_card.py` | Wiki 卡片（v0.3 兼容，engine 薄封装） | `render_entry_to_path` / `render_entry` |
| render | `card.py` / `viewmodel.py` | v0.3 遗留 Pillow 卡片（未接线） | - |
| storage | `credentials.py` | 凭据加密存储（PBKDF2+XOR+HMAC），v2 结构含 bind_type/stoken/mid，向下兼容 v0.3；**W8 文件损坏容错（JSON 解析失败备份 `.corrupt-<ts>` 后按空库处理；OSError 瞬时锁不上抛为损坏）** | `CredentialStore.bind/unbind/list_accounts/get_bundle` |
| scripts | `convert_wiki.py` / `fetch_wiki.py` | 工作区数据转换 / BWiki 全量抓取（校验清洗+同名去重+审计；SSRF 白名单；WAF 抖动限速） | 命令行脚本 / `run(categories, workers)` |
| scripts | `acceptance_v4.py` | v0.4 验收图生成（fixture + 真 Edge 出 4 张 PNG；图标走离线 MockTransport 属预期） | 命令行脚本 |

### 关键配置

- 环境变量：`DEMIAOGE_MASTER_KEY`（凭据加密主密钥）、`DEMIAOGE_EDGE`（Edge 路径，缺省自动探测常见安装位置）
- 配置项（`_conf_schema.json`，10 项）：`adapter`（mihomo/mock，默认 mihomo）、`master_key`、`http_enabled`（默认 true）、`http_host`（默认 127.0.0.1）、`http_port`（默认 8765）、`cache_ttl_minutes`（默认 10）、`auto_update`（每日核对，默认 true）、`auto_update_time`（默认 04:30）、`edge_path`、`admins`
- 运行依赖（`requirements.txt`）：httpx>=0.27、qrcode>=7.4；pillow/cryptography/aiohttp 随 AstrBot 环境自带

## 四、数据文件（插件 data/）

| 文件/目录 | 内容 | 备注 |
|---|---|---|
| `characters.json` / `light_cones.json` / `relics.json` | BWiki 快照静态资料 | 只读，维护窗口经 `scripts/fetch_wiki.py` 更新 |
| `wiki.json` | 旧全量备份（拆分文件齐全时不被读取） | 兜底 |
| `aliases.json` | 别名/黑话表 | 独立维护 |
| `wiki_backup_20260806_new_pipeline.zip` | 旧数据打包备份 | 勿删 |
| `wiki_backup_*_pre_recrawl.zip` | W6 全量重爬前备份（含 19 条 PAGENAME 脏数据的现场） | 勿删 |
| `wiki_sync_audit.json` | 同步审计报告（含 W6 起 `diff_check` 核对差异与 `dropped_invalid` 剔除清单） | fetch_wiki / 定时核对产物 |
| `fixtures/` | W1-A 实测快照（`mihomo_sr_info_parsed.json` 等）+ `_` 前缀源码/过程证据 | fixtures 参与离线测试；`_` 前缀不参与业务 |
| `profile_cache/` | 面板 payload 磁盘缓存 `{uid}.json`（含 fetched_at） | TTL 由 cache_ttl_minutes 控制 |
| `icons/` | StarRailRes 图标下载缓存（保留相对路径结构） | 下载失败留空 → 模板占位 |
| `card_cache/` | 已渲染卡片 PNG 缓存 | wiki 卡片 + 面板/练度成图 |
| `render_acceptance/` / `render_cards_acceptance/` | 旧渲染验收产物 | v0.3 / W1-B |
| `render_v4_acceptance/` | v0.4 最终验收图 4 张（panel/audit/character_流萤/lc_记一位星神的陨落） | `scripts/acceptance_v4.py` 产出 |
| `credentials.json` | 凭据加密存储（配置 master_key 后生成） | 不入 git，勿提交 |

## 五、测试

从父目录 `C:\Users\14476\.astrbot\data\plugins` 运行：`python -m pytest -q astrbot_plugin_demiaoge/`（当前 132 passed / 1 skipped）。

- 离线用例：adapter/mapper（`test_mihomo_adapter`→fixture、`test_mihomo_mapper`）、DS（`test_ds_sign`）、扫码状态机（`test_qr_flow`）、凭据 v2（`test_credentials_v2`）、缓存（`test_cache_service`）、图标（`test_icon_cache`）、UID 解析（`test_uid_resolver`）、PanelService 编排（`test_panel_service`）、HTTP（`test_http_api`）、渲染（`test_render_cards` / `test_render_acceptance`）、**异步纪律静态守护（`test_async_hygiene`）**、Wiki 核对服务（`test_wiki_update_service`）、绑定防串号（`test_bind_guard`）。
- `test_sync_data.py`：依赖工作区 `hsr_wiki_data/` 原始数据，路径不存在时 skipif 跳过（见坑点 6）。
- 真渲染验收：`python astrbot_plugin_demiaoge/scripts/acceptance_v4.py`（真 Edge，4 张图）。

## 六、已知坑点（务必先看）

1. **Edge 截图覆盖问题**：旧版 `--screenshot` 对已存在目标文件覆盖不生效。`render/engine.py` 已用「临时文件 + shot.replace(target) 原子替换」规避，别回退成旧写法。
2. **无头视口偏移**：Edge `--headless=new` 下 PNG 高 = `--window-size` 高，但实际排版视口只有 window_height − 94；新卡片估算高度必须加 `render.engine.HEADLESS_VIEWPORT_CHROME`（实测 94 + 6px 余量），否则底部被裁。
3. **图标源与预热（W8 重写）**：`IconCache` 默认源列表 jsDelivr 三镜像（cdn/gcore/testingcf）在前、`raw.githubusercontent.com` 兜底（本机 raw 实测不可达）；sticky 记忆成功源；下载失败写 10 分钟内存负缓存防重复打网络；共享 AsyncClient 连接复用（25 张冷下载 32s→3.2s）。成图命令在关键路径限时 8s await 图标解析，超时/失败占位出图不阻塞。
4. **salt/端点可能轮换**：DS salt 与扫码端点是核实开源实现得到的当前值，米哈游可能随版本轮换；权威记录与实测方法见 `docs/api_notes.md`，失效时更新 `adapters/ds.py` / `adapters/mihoyo_auth.py`。
5. **UID 绑定的 cookie 字段是占位值**：`CredentialStore.bind` 强制 cookie 非空，UID 绑定把 uid 本身作为 cookie 占位存入（bind_type="uid"）；业务层不得把该字段当 Cookie 用（详见 main.py 注释）。
6. **test_sync_data skipif**：该测试依赖工作区 `workspaces\_FriendMessage_1447653277\hsr_wiki_data\`（维护窗口产物），路径不存在时自动 skip 并注明原因——这是设计行为，不是回归。
7. **image_result 只收路径字符串**：AstrBot `event.image_result(url_or_path)` 传 bytes 会 TypeError（内部 `startswith("http")`）。所有图片发送一律 `event.image_result(str(png_path))`，PanelService 四个成图方法返回 Path。`test_async_hygiene.py` 静态守护。
8. **异步纪律**：事件循环上禁止阻塞——网络全 httpx.AsyncClient；Edge 截图收敛在 `render/engine.py` 且调用方 to_thread；payload 缓存磁盘 I/O、二维码生成/落盘走 to_thread；等待一律 `await asyncio.sleep`。例外：`services/wiki_crawler.py` 是维护窗口手动 CLI，不在事件循环内，允许同步库。渲染/同步服务的运行日志用标准 `logging`（logger 名 `demiaoge.render` / `demiaoge.wiki_sync` / `demiaoge.credentials`），别回退成 print。
9. **绑定隔离与防串号（W7）**：凭据按发送者 ID 一级隔离；`find_uid` 防同人重复绑同一 UID；`switch` 指针存顶层 `_current` 键（不与别名命名空间混用）；需要凭据的命令（体力）只取 `get_bundle(owner_id=发送者)`，参数永不指定他人账号。
10. **成图缓存键是内容哈希**：卡片缓存键 = `类型_标识_{sha256(html)[:12]}`（`render_to_path`），数据一变键即变、自动重渲染（修掉了旧 `panel_{uid}` / `character_{name}` 键的跨用户串图与 TTL 过期后命中旧图问题）；card_cache 文件由 main 每日 GC 按超期（7 天）回收，`/hsr 更新缓存` 仍可立即全清。
11. **卡片高度自适应（adaptive.py）**：引擎截图前页面末尾有 3px 洋红哨兵块，截图后裁到哨兵顶——不要"优化掉"哨兵；自适配包装层先查缓存（成品已无哨兵，不能当"估算过矮"重试）。升级部署后旧 card_cache 带黑边/哨兵线的图需 `/hsr 更新缓存` 清一次。
12. **BWiki WAF（HTTP 567）**：突发并发会触发限频，之后约 20 分钟内全拒。抓取纪律：workers≤3、每请求 0.8-1.8s 抖动、指数退避；触发后冷却再试。`fetch_wiki.py` 有 SSRF 白名单（仅 wiki.biligame.com + 私网 IP 阻断 + 禁重定向），别拆。
13. **光锥/角色数据以 W6 重爬为准**：角色技能/星魂、光锥「光锥故事」均已入库；审计的 `dropped_invalid` 是被清洗的空白/占位条目（如 19 条 PAGENAME），属设计行为不是数据丢失。
14. **在线更新**：每日 auto_update_time 自动核对 + `/hsr 更新数据` 手动触发（二者同代码路径）；`wiki_update_service.py` 已实装（原 TODO 完结），维护窗口也可手动 `python scripts/fetch_wiki.py`。
15. **汇报纪律**：汇报前必须确认实际落地（曾因空口说白话被点名批评）。
16. **工作区 main.py ≠ 德谬歌**：工作区 `main.py` 是「汐光锚点」称呼守护插件，与德谬歌无关，别混。
17. **Edge 子进程 CWD**：截图路径必须绝对化（engine/adaptive 已 `.resolve()`），相对路径会报 `Failed to write file ... (0x3)`。
18. **新旧插件并存**：`astrbot_plugin_seashell` 是旧骨架，开发一律在 `astrbot_plugin_demiaoge`，避免改错目录。

## 七、接手工作流建议

1. 读本 CODE_MAP.md → 2. 读 `DEVELOPMENT.md`（规格权威）与 `docs/wave_notes.md`（各波次实测记录与偏差说明）→ 3. 上游字段/端点疑问查 `docs/api_notes.md` + `data/fixtures/` → 4. 改动后从父目录跑全量 pytest → 5. 涉及渲染时跑 `scripts/acceptance_v4.py` 目检 4 张验收图 → 6. 每完成一步更新 wave_notes。
