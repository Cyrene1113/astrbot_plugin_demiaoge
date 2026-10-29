# 德谬歌 v0.4 开发档案（星铁查询插件 · 对标云崽 miao-plugin / xiaoyao-cvs）

> 建立：2026-10-26。本档案是唯一权威规格，任何子代理动手前必读本文 + `CODE_MAP.md`。
> 原则：**全程纯机械固定流程，零 LLM 参与**。所有回复文本均为硬编码模板，所有数据映射均为固定字段表。

---

## 1. 项目现状（2026-10-26 基线）

### 1.1 已有可用能力
| 能力 | 位置 | 状态 |
|---|---|---|
| 本地 Wiki 查询（精确→别名→包含） | `services/wiki_service.py` | ✅ 可用（角色101/光锥166/遗器61条） |
| Wiki HTML 卡片 + Edge 无头截图 | `render/html_card.py` | ✅ 可用，含缓存与原子替换 |
| Cookie 手动粘贴绑定（加密存储） | `storage/credentials.py` | ✅ 可用（PBKDF2+XOR+HMAC） |
| 米游社资料适配器 | `adapters/mihoyo_profile.py` | ⚠️ **无 DS 签名，线上必被拒** |
| Pillow 角色列表卡片 | `render/card.py` | ⚠️ 纯色块 ASCII 风，拟废弃 |

### 1.2 本次新增目标
1. **UID 免 Cookie 直查**（对标 miao-plugin）：绑定 UID，走 Mihomo API（`api.mihomo.me`）查面板/练度，要求对方开启"角色展示"。
2. **扫码绑定**（对标 xiaoyao-cvs-plugin）：生成米游社登录二维码 → 轮询确认 → 换取 stoken/cookie_token 加密落盘。
3. **图片输出**：面板总览图、练度统计图、单角色详情图、光锥资料图（HTML→Edge 截图，复用已验证渲染路径）。
4. **公共 HTTP 端口**：插件自带 aiohttp 端点，按 UID 返回练度 JSON / 面板 PNG。
5. **静态资料本地化**：角色/光锥/遗器资料存 `data/*.json`（已有），图标按需下载缓存到 `data/icons/`。

### 1.3 非目标（明确不做）
- 不接任何 LLM Provider；不调用 `context.get_provider`。
- 不做抽卡记录导出（云崽 ` analys ` 类功能）。
- 不做 sqlite（沿用 JSON + 原子写；若未来引入 DB，外部输入一律参数绑定，禁止拼接 SQL）。
- 不自动爬取 BWiki 更新（沿用 `scripts/fetch_wiki.py` 手动维护窗口执行）。

---

## 2. 命令规格（main.py 分发，全部 `filter.command("hsr")`，子命令 if/else 机械路由）

| 命令 | 参数 | 行为 | 回复 |
|---|---|---|---|
| `/hsr help`（或 帮助） | - | 帮助文本 | 固定文本 |
| `/hsr 绑定 <UID>` | 纯数字9-10位 | 存 UID 绑定（别名 default） | 成功/失败文本 |
| `/hsr 绑定 <UID> <别名>` | 同上 | 多账号绑定 | 成功文本 |
| `/hsr 扫码` | - | 米游社扫码登录：发二维码图片，后台轮询 | 先回二维码图，确认后回"绑定成功"；180s 超时回提示 |
| `/hsr 我的绑定` | - | 列出本账号所有绑定（凭据只显示摘要） | 固定格式文本 |
| `/hsr 解绑 [别名]` | 缺省 default | 删除绑定 | 成功/未找到 |
| `/hsr 面板 [UID\|别名]` | 缺省=本人 default 绑定 | 面板总览图（8-10 角色） | 图片 |
| `/hsr 练度 [UID\|别名]` | 同上 | 全角色练度统计图 | 图片 |
| `/hsr 角色 <名称> [UID\|别名]` | 名称走 wiki 别名表解析 | 单角色详情大图 | 图片 |
| `/hsr 光锥 <名称> [UID\|别名]` | 同上 | 单光锥+持有者详情图 | 图片 |
| `/hsr wiki <名称> [--image]` | - | 兼容保留 v0.3 行为 | 文本/图片 |
| `/hsr 更新缓存` | 仅管理（config.admins） | 清空面板缓存与图标缓存 | 文本 |

解析规则（机械）：
- 命令体 `event.message_str.strip().split()`；子命令集合固定，命中失败一律回帮助。
- 名称→角色 ID：走 `WikiService` 别名解析（`aliases.json` + data 内 aliases 字段），查不到回"未收录"。
- UID 优先级：显式参数 > 绑定别名 > 本人 default 绑定；无绑定回提示。
- `--image` 等开关用 `parts[2:]` 中 `startswith("--")` 剥离。

## 3. 数据源与 API 规格

### 3.1 Mihomo API（免 Cookie 主路径）【W1-A 已实测】
- `GET https://api.mihomo.me/sr_info_parsed/{uid}?lang=cn`，无需 Cookie/DS。
- 成功 200：`{ player: {...}, characters: [...] }`。**权威 schema 以 `docs/api_notes.md` §2 与 `data/fixtures/mihomo_full_one_character.json` 为准**，要点：`player.is_display` 决定 characters 是否有数据；角色属性组字段名为 `statistics/attributes/additions/properties`（非 stats）；affix 通用结构 `{name, value, display, percent, icon}`；icon 均为相对路径。
- 错误：400 `{"detail":"Invalid uid"}` / 404 `{"detail":"User not found"}` → 统一归 `DATA_NOT_FOUND`，固定文案，不按 message 文本猜。
- 频控：同 UID 结果内存+磁盘缓存 TTL（默认 10 分钟，config 可调）。

### 3.2 米游社 game_record（Cookie 路径，扫码绑定后可用）
- 基址 `https://api-takumi-record.mihoyo.com/game_record/app/hkrpg/api/`
- DS 签名（K2 salt，W1-A 从 miao-plugin/xiaoyao-cvs 源码核实后写入 `docs/api_notes.md`，以核实值为准）：
  - `t=int(time.time())`，`r=8位随机`
  - POST：`sign=md5(f"salt={salt}&t={t}&r={r}&b={body}&q={sorted_query}")`
  - GET：`sign=md5(f"salt={salt}&t={t}&r={r}&q={sorted_query}")`
  - 头：`DS: {t},{r},{sign}`
- 仅作为 Mihomo API 失败且用户已扫码绑定的**降级路径**，v0.4 只需实现 index 查询映射。

### 3.3 扫码登录流程（W1-A 实测后修订：采用 passport **web 变体 A**，弃用老端点）
```
1 POST https://passport-api.miyoushe.com/account/ma-cn-passport/web/createQRLogin  body {}
    headers 仅需 x-rpc-app_id: bll8iq97cem8 + x-rpc-device_id: <uuid>   （无需 DS，已实测 retcode=0）
    → data{url, ticket} → 生成二维码 PNG（内容=url）
2 每 2s POST .../web/queryQRLoginStatus  body {"ticket": ...}，最多 90 次/180s
    Created→继续；Scanned→提示一次；Confirmed→ user_info{aid, mid} + Set-Cookie(cookie_token/LToken v2)
    -3501 二维码过期 / -3505 已取消 / -3503 风控 / 超时 → 各回固定文案
3 备用兑换（若需补齐 stoken 场景）：
    GET passport-api.mihoyo.com/account/auth/api/getCookieAccountInfoBySToken → cookie_token
    GET passport-api.mihoyo.com/account/auth/api/getLTokenBySToken → ltoken   （Cookie: mid+stoken）
4 组装 stuid/stoken/mid/ltuid/cookie_token/ltoken → CredentialStore 加密落盘
```
app 变体 B（xiaoyao 同款，PROD salt `JwYDpKvLj6MrMqqYU6jTKF17KNO2PXoS` + b/q DS，createQRLogin 实测通过）仅作备用；query 阶段实测 -3503 风控，device_fp 必须随机 13 位 hex。详见 `docs/api_notes.md` §1.3/§5。

### 3.4 静态资料
- `data/characters.json`、`light_cones.json`、`relics.json`：BWiki 快照（只读）。W6 起解析器含：角色技能（内嵌 `{{行迹/技能}}`）、星魂（`{{角色/技能}}` 星魂1-6）、光锥「光锥故事」描述、`{{颜色|a|b}}` 保留末参数值。
- 校验清洗（`validate_record` + `dedupe`）：占位名（PAGENAME/需要内容等）、星级缺失、描述技能星魂全空的条目剔除并记入审计 `dropped_invalid`；同名条目保留内容最丰富一条。
- 图标【W1-A 实测修正】：API 返回的 icon/preview/portrait 为**相对路径**，基址为 `https://raw.githubusercontent.com/Mar-7th/StarRailRes/master`（非 hakush.in，无防盗链）。下载缓存到 `data/icons/`（保留相对路径结构），必须带重试（本机到 GitHub raw 不稳定，1-3 次重试）+ 超时 10s + 失败返回空路径由模板出占位图，不阻塞主流程。

### 3.5 Wiki 数据周期核对（W6）
- 每日 `auto_update_time`（默认 04:30）`WikiUpdateService.schedule_loop` 自动执行；管理员可 `/hsr 更新数据` 立即触发（同一代码路径，互斥防重入）。
- 流程：本地快照 → `fetch_wiki.run`（3 workers + 0.8-1.8s 抖动 + 指数退避；SSRF 白名单 wiki.biligame.com）→ 校验清洗入库 → 新旧按 (category,name) 核对出 新增/移除/内容更新 → 差异并入 `data/wiki_sync_audit.json` 的 `diff_check`。
- 纪律：BWiki WAF 实测会返回非标准 567（突发并发触发，约 20 分钟冷却）；任一类别失败保留本地旧文件；阻塞爬取一律 to_thread。
- 存储为 JSON 文件（无 SQL）；若未来引入数据库，所有外部输入必须参数绑定，禁止拼接 SQL。

## 4. 数据流（收令 → 回图，全固定）

```
命令文本 ──机械解析──> 子命令+参数
  ├─ 定位 UID/绑定（显式参 > 别名 > 本人default）
  ├─ 查缓存(TTL) ─命中→ 直接渲染
  ├─ 未命中 → MihomoAdapter.fetch(uid) →（失败且有cookie→米游社降级）→（仍失败→固定错误文案）
  ├─ mapper 固定字段表 → ViewModel（含图标URL→本地缓存路径）
  └─ HTML 模板填充 → Edge 截图（内容哈希缓存键）→ event.image_result(str(PNG路径))
```

异步纪律（W5 审计后为硬约束）：事件循环上禁止阻塞——网络一律 httpx.AsyncClient；Edge 截图收敛在 `render/engine.py`、调用方 `asyncio.to_thread`；payload 缓存磁盘 I/O、二维码生成/落盘、缓存清理走 to_thread；等待一律 `await asyncio.sleep`。所有图片以**文件路径字符串**发送（AstrBot `image_result` 传 bytes 会 TypeError）。`test_async_hygiene.py` 静态守护。

## 5. 渲染设计（W1-B）

- 抽取 `render/engine.py`：`render_html_to_png(html:str, cache_key:str, cache_dir:Path) -> Path`，Edge 路径探测/临时文件/原子替换逻辑从 `html_card.py` 平移，**不得回退旧覆盖写法**。`html_card.py` 改为薄封装保持 `/hsr wiki --image` 兼容。
- 新模板（纯字符串拼接 + html.escape，风格延续现有 CSS 深蓝风）：
  1. `panel_card.py`：头部玩家信息 + 每行角色（缩略图/等级/E数/命途/元素/光锥缩略）
  2. `audit_card.py`：练度统计（全部角色网格：头像+等级+E，按 等级→E 排序，5星金框4星紫框）
  3. `character_card.py`：单角色（立绘位+属性/命途徽章+技能等级条+光锥条+遗器两件套+副词条）
  4. `lc_card.py`：光锥（资料+叠影效果+持有者列表）
- 尺寸：宽度 800-1000px，高度按行数估算（沿用 `_height` 思路，上限 4000）。
- 每个 viewmodel 一个 `build_html(vm)->str` 纯函数 + fixture 测试。

## 6. 存储设计

- `data/credentials.json`（v2 结构，向下兼容 v0.3 读取）：
  `{owner_id: {alias: {uid, cookie_encrypted, stoken_encrypted, mid, bind_type: "uid"|"qr", bound_at}}}`
- `data/profile_cache/{uid}.json`：面板原始 parsed JSON + `fetched_at`（TTL 检查用）。
- `data/icons/`、`data/card_cache/`：PNG 缓存。
- 加密：沿用 CredentialStore（PBKDF2+HMAC），新增字段走同一 `_crypt`。
- **禁止**：任何日志打印完整 cookie/stoken；`bind` 回显仅摘要。

## 7. 公共 HTTP 端口（W3）

- `initialize()` 启动 aiohttp（已随 AstrBot 环境）：
  - `GET /hsr/profile?uid=xxx` → JSON `{player, characters:[{name,level,eidolon,path,element,light_cone}]}`（仅公开数据）
  - `GET /hsr/profile.png?uid=xxx` → 面板 PNG
- 默认绑定 `127.0.0.1:8765`，config 可改 host/port；只读端点，无任何凭据输出；错误统一 JSON `{"error": code}`。
- `terminate()` 必须优雅关闭 runner。

## 8. 安全约束（Mimosa 验收项）
- 若引入 SQL：一律参数绑定。当前设计用 JSON 文件，无 SQL。
- 凭据加密落盘、日志脱敏、HTTP 端点不吐凭据、外端口默认关闭（127.0.0.1）。
- 上游错误文案固定，不透传原始响应体给用户。

## 9. 测试与验收（每波次自验 + W4 全量回归）

从父目录 `C:\Users\14476\.astrbot\data\plugins` 运行：
`python -m pytest -q astrbot_plugin_demiaoge/ -x`
- `test_mihomo_adapter.py`：fixture JSON → mapper → ViewModel 断言（离线）。
- `test_ds_sign.py`：已知输入 → 已知 md5 输出（离线）。
- `test_qr_flow.py`：create/poll 状态机用 mock HTTP 断言（离线）。
- `test_render_cards.py`：四个模板 fixture 渲染 PNG 成功、尺寸>0、缓存命中二次耗时下降。
- `test_http_api.py`：aiohttp 测试客户端打 `/hsr/profile`（mock adapter）。
- 既有 `test_render_acceptance.py`、`test_sync_data.py` 不得回归失败。

## 10. 任务分派单（子代理波次）

| 波次 | 代理 | 范围 | 交付物 | 依赖 |
|---|---|---|---|---|
| W1-A | 调研 | 实测 Mihomo API 存 fixture；从 miao-plugin/xiaoyao-cvs 源码提取 DS salt 与扫码端点并实测 createQRLogin；写 `docs/api_notes.md` | fixture + api_notes.md | 无 |
| W1-B | 渲染 | engine.py 抽取 + 4 模板 + viewmodel + fixture 测试 | render/* + 测试 | 无 |
| W2 | 适配器 | mihomo_api.py / mihoyo_record.py（DS）/ mihoyo_auth.py（扫码状态机）/ mapper v2 / CredentialStore v2 / 缓存服务 | adapters + storage + 测试 | W1-A |
| W3 | 集成 | main.py 全命令接线 + bind/qr 服务 + aiohttp 端口 + `_conf_schema.json` + requirements.txt + 帮助 | main.py 等整体可跑 | W1-B, W2 |
| W4 | 验收 | 全量 pytest + 修回归 + 更新 README/CODE_MAP/PLAN/版本号 0.4.0 | 全绿测试 + 文档 | W3 |

冲突纪律：每代理只改分派单列出的文件；公共文件（main.py）归 W3；发现越界问题记录到 `docs/wave_notes.md` 不擅自改。
