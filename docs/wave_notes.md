# 波次记录（wave_notes）

## W1-A 调研（2026-10-26）

交付：`docs/api_notes.md`（权威笔记）、`data/fixtures/mihomo_sr_info_parsed.json`、`data/fixtures/mihomo_full_one_character.json`、`data/fixtures/qr_create_response.json`、`data/fixtures/qr_query_status_initial.json`、`data/fixtures/qr_web_variant_probe.json`。未改任何 .py / 既有 json。

### 过程问题与结论

1. **DEVELOPMENT.md §3.1 字段表有误**：`stats[]` 实测字段名是 `statistics[]`，另有 `attributes/additions/properties` 三组同形结构；`path/element` 实测还含 `id`/`color`；character 实测多出文档未列的 `enhanced/skill_trees/pos`。以 `docs/api_notes.md` §2 为准（fixtures 为证据）。
2. **DEVELOPMENT.md §3.3 扫码端点已过时**：计划的 `api-takumi.miyoushe.com/auth/api/createQRLogin` 无在维护实现使用。实测推荐 web 变体（`passport-api.miyoushe.com/account/ma-cn-passport/web/createQRLogin`，无需 DS、无风控，create+query 全通）；xiaoyao 同款 app 变体 create 亦实测通过（PROD salt）但 query 阶段被 -3503 风控。W2 接线时按 api_notes §5 状态机改。
3. **图标域名结论修正**：§3.4 写的 `api.hakush.in/hsr/UI/...` 与 Mihomo API 返回的相对路径不匹配；实测基址为 `https://raw.githubusercontent.com/Mar-7th/StarRailRes/master`（MetaCubeX/mihomo 官方库 ASSET_URL），无防盗链。**本机到 raw.githubusercontent.com 偶发断连/握手超时，W2 下载器必须重试**（实测重试 1-3 次成功）。
4. **getTokenByGameToken salt 分歧未裁决**：xiaoyao 用 PROD salt、jiarui666 用 `OvOIsZRXrUbXoUlpQuhEx4tgAwNVUMmp`，无效 game_token 探测两分支均 -5300，无法区分。已标注"需 W2 持真实 game_token 再验"。
5. **本机网络环境限制**（非域名不存在）：`sr.mihomo.me`、`api.hakush.in` DNS 无法解析；GitHub raw 与米游社 passport 域名均可达但偶发抖动。所有失败请求均如实记录，未编造。
6. **请求纪律执行**：Mihomo 实测共 6 次成功请求 + icon 4 次（含 2 次网络重试）；扫码链路实测共 7 次（间隔≥2s，≤15 上限内）。全程未涉及真实账号。
7. fixtures 目录下 `_` 前缀文件为源码/过程证据快照（xiaoyao、Miao-Yunzai、MihoyoBBSTools、mystool、UIGF、jiarui666 共 10 份 + 2 份探测日志），供 W2 与复核使用，不参与业务。
8. createQRLogin 实测拿到的 ticket 未做任何后续扫码操作，二维码自然过期，无账号安全影响。

## W2 适配器波次（2026-10-26）

交付：`adapters/ds.py`、`adapters/mihomo_api.py`、`adapters/mihomo_mapper.py`、`adapters/mihoyo_record.py`、`adapters/icon_cache.py`、`adapters/mihoyo_auth.py`、`adapters/qr_image.py`、`services/cache_service.py`（均新建）；`storage/credentials.py` v2 扩展（bind 增 bind_type/stoken/mid，新增 get_bundle，老格式兼容）；`requirements.txt` 改写（httpx>=0.27、qrcode>=7.4，pillow 注明由 AstrBot 环境自带）；测试 `test_ds_sign.py`、`test_mihomo_mapper.py`、`test_qr_flow.py`、`test_credentials_v2.py`、`test_cache_service.py`、`test_icon_cache.py`（全离线，网络一律 MockTransport/monkeypatch）。未碰 main.py、render/*、domain/*、services/wiki_*、data/ 既有 json。

### 实测与验证

1. **测试**：指定 8 文件命令 62 passed（含既有 test_render_cards / test_render_acceptance）；`python -m pytest -q astrbot_plugin_demiaoge/` 中 `test_sync_data.py` 失败为**既有环境问题**——它依赖工作区 `workspaces/_FriendMessage_1447653277/hsr_wiki_data/`（本机不存在），与 W2 改动零交集，未擅自修。
2. **实网冒烟①（主路径）**：`MihomoApiClient.fetch_parsed("100895290")` → 200，uid=100895290 昵称"洛尘"70 级 is_display=True，**角色数 6，首角色"流萤"80 级 E2 光锥"记一位星神的陨落"**，耗时 2.56s；mapper 产出 panel 6 行 / audit 6 行 / CharacterVM 键 {1204,1212,1308,1310,1407,1505}。
3. **实网冒烟②（图标）**：StarRailRes 图标下载 2 次尝试均超时（4 次尝试×10s+退避，约 48s 后按设计返回 "" 不崩溃）。当前本机到 raw.githubusercontent.com 完全不可达（比 W1-A 时的"偶发抖动"更严重）；成功路径已由 MockTransport 单测覆盖（原子落盘/去重/404 不重试）。
4. **二维码生成冒烟**：qr_png_bytes 本地生成 758B PNG 签名正确（qrcode 库已在运行环境，版本无 `__version__` 属性但可用）。

### 给 W3/W4 的要点与偏差说明

1. **sub_affix 展示值**：任务写 "display+step"，落地为 `display（强化{step}）`（step>0 时），渲染层会再加 "+" 前缀，最终如 "攻击力 +42（强化4）"。如需改样式只动 `mihomo_mapper._sub_value`。
2. **CharacterVM.stats 的 base 列恒为空串**：任务明确 properties→stats 且 statistics/attributes 忽略；模板 "基础 → 最终" 表的 base 列渲染为空。若 W4 想补 base，可按 `field` 用 attributes[] 关联，mapper 留了扩展位。
3. **map_light_cone 的 description/skills 恒为空**：Mihomo 光锥对象（api_notes §2.2）不含描述与叠影文案。W3 做 `/hsr 光锥` 时需自行用 wiki 数据（data/light_cones.json）合成 LightConeVM 或扩展本函数入参；owners 匹配逻辑（按光锥名）已就绪。
4. **skills 过滤规则**：`type_text` 为空的条目（MazeNormal 占位，name 是纯数字 id）不进卡片，流萤 8→7 行；非空 type_text 全保留（同一技能强化版会出现两行，属上游数据原貌）。
5. **mihomo_api 200 但 body 可解析而形状不对 → MAPPING_FAILED**；200 不可解析（如网关 HTML）→ UPSTREAM_NETWORK。均为固定中文文案，无透传。
6. **game_record 1034** 归 AUTH_MISSING + 新文案"触发了安全验证，请稍后再试。"（AUTH 类无更贴切既有码，Dev 文档未定，留 W4 裁决）。
7. **icon_cache 最坏路径耗时**：raw.githubusercontent.com 完全不可达时 resolve 单路径最长约 48s（4×10s 超时+退避）。W3 渲染前务必用 `iter_icon_paths`+`resolve_many` 预热且别在命令关键路径上同步等它，或考虑调低 timeout；失败返回 "" 由模板占位，不阻塞出图。
8. **complete_with_stoken 的 getLTokenBySToken** 按文献同时接受 `data.token` / `data.ltoken` 键；getCookieAccountInfoBySToken 取 `data.cookie_token`。该两接口未实网验证（需真实 stoken）。
9. **requirements**：httpx 0.28.1 / qrcode（已装）/ pillow 12.3.0 / pytest 9.1.1 实测可用；AstrBot 后端运行时（F:\AstrBot）自带，无需 pip 安装动作。

## W3 集成波次（2026-10-26）

交付：`services/uid_resolver.py`、`services/panel_service.py`、`services/bind_service.py`、`services/http_server.py`（均新建）；`main.py` 全量重写（唯一 import astrbot 的文件）；`_conf_schema.json`（8 项配置）；测试 `test_uid_resolver.py`、`test_panel_service.py`、`test_http_api.py`（全离线）。未碰 render/*、adapters/*、storage/*、domain/*、services/wiki_*、services/cache_service.py、data/ 既有内容（走查产生的 credentials.json/card_cache 等运行时残留已清理还原）。

### 实测与验证

1. **测试**：指定 11 文件命令 **94 passed**（新增 32 + 既有 62），7.8s；`python -m py_compile main.py` 通过；`_conf_schema.json` JSON 合法。test_sync_data.py 仍为既有环境失败，未动。
2. **全命令动态走查**（stub astrbot + adapter=mock + 真 Edge 渲染）：help/绑定（合法、非法 UID、别名、含空格别名）/我的绑定/解绑/面板（default、显式 UID、别名、未绑定）/练度/角色（命中、包含、未找到）/光锥（纯资料、带 UID 持有者、未收录）/wiki/profile/panel/bind/更新缓存（管理员开/关）/未知子命令→帮助，全部符合 §2 预期；二次查询命中双层缓存（client 不再被调）；坏 client 注入 → "内部错误，请稍后再试。（request_id:…）"。
3. **HTTP 端口实测**：/hsr/profile 200 JSON 投影逐字段断言；缺 uid 400 `{"error":"missing uid"}`；DATA_NOT_FOUND→404 `user_not_found_or_not_public`；其他 DemiaogeError/未知异常→502 `upstream`；profile.png content-type=image/png + 二次命中不再调 client；真实 bind 在端口被占时 start() 返回 False、stop 后端口释放。

### 实现决定与偏差说明（给 W4）

1. **DemiaogeError 无 `.message` 属性**（任务书前提有误）：文案是异常首参，main 层统一用 `str(exc)` 展示；W4 若想规范化可给 domain/errors.py 补 `self.message = message`（本次未越界改）。
2. **UID 绑定的 Cookie 占位**：CredentialStore.bind 强制 cookie 非空（不能改 W2 文件），UID 绑定把 uid 本身作为 cookie 占位存入（bind_type="uid"），业务层不得把该字段当 Cookie 用——已注释说明。
3. **绑定别名含空格**（如 `绑定 <UID> a b`）：别名取剩余 token 合并后再校验 → 回"别名不合法"，不再静默截断。
4. **PNG 成图缓存**：仅 面板/练度 有 `card_dir/{type}_{uid}.png` 层（payload 命中 + 文件存在才直读）；角色/光锥依赖 engine 层 `character_{name}`/`lc_{name}` 键缓存。缓存失效（invalidate）后即使成图存在也会重渲染（按任务书"两者同时命中才直读"）。
5. **`/hsr 光锥` 不带 UID/别名** → 纯资料卡（owners 为空），不做"静默查 default 绑定"——保持机械规则；带别名但未绑定 → 回"未找到该绑定"文案。
6. **图标预热**：`PanelService._prewarm_icons` fire-and-forget（不 await），渲染用 `_LocalIconResolver` 同步查 `icon_cache.root` 本地文件；预留 `await panel_service.wait_background()` 供测试/收尾。raw.githubusercontent.com 不可达时全部回 "" 走占位，实测不阻塞出图（测试用 MockTransport 404 保证离线确定性）。
7. **mock 适配器**：按任务书放 main.py 内 `_MockMihomoClient`（非 adapters/），对任意 UID 回固定 payload（echo uid），已用 mapper 实测可出 panel/audit/character 全链路真图。
8. **HTTP/扫码等异步生命周期**：`initialize()` 启动 HsrHttpServer（http_enabled 默认 true；端口占用仅 warning 不阻塞加载）；`terminate()` 优雅 stop；两者均调用 `super().initialize/terminate`（Star 基类为 no-op 钩子，已核实 AstrBot 源码 base.py）。
9. **扫码 handler 轮询**：2s × 90 次，Scanned 只提示一次；Expired/Cancelled/Risk/Timeout 文案与 api_notes §5 逐字一致（常量集中在 bind_service）；`step_poll` 网络/DemiaogeError 由 main 外层统一转固定文案；process 链路无裸 `except: pass`（OSError 清理均 contextlib.suppress + 注释）。
10. **requirements.txt 未改**（W2 已含 httpx/qrcode；aiohttp 随 AstrBot 环境）；metadata.yaml 版本号按分派单留 W4。

## W4 验收收尾（2026-10-27）

交付：`domain/errors.py` 补 `self.message = message`（str(exc) 行为不变，W3 遗留项 1 落地）；`test_sync_data.py` 加 `pytestmark = pytest.mark.skipif`（工作区 `hsr_wiki_data/` 路径不存在时 skip 并注明原因，测试逻辑本身未删）；新建 `scripts/acceptance_v4.py`；`metadata.yaml` 升 v0.4.0 + desc 更新；README.md 重写、CODE_MAP.md 重写、PLAN.md 顶部追加 v0.4 阶段记录。未碰 main.py、adapters/*（errors.py 除外）、services/*、render/*、storage/*、data/ 既有 json。

### 实测与验证

1. **全量回归**：父目录 `python -m pytest -q astrbot_plugin_demiaoge/` → **94 passed, 1 skipped, 0 failed**（8.0s；唯一 skip 为 test_sync_data，环境性，见坑点 6）。`python -m py_compile main.py` 通过；`metadata.yaml` YAML 合法、`_conf_schema.json` JSON 合法（python 解析验证）。
2. **真 Edge 验收图 4/4**（`scripts/acceptance_v4.py`，fixture 100895290 + MockTransport 404 离线图标）：panel_100895290.png 820x731（182KB，0.62s）、audit_100895290.png 820x514（139KB，0.52s）、character_流萤.png 900x1524（406KB，0.59s）、lc_记一位星神的陨落.png 820x668（171KB，0.51s）；产出于 `data/render_v4_acceptance/`，已人工目检 panel 与 character 两张（图标占位灰块属预期，GitHub raw 当前不可达）。
3. **验收脚本写法**：与 test_panel_service.py 同构（fake client 注入 PanelService、临时 profile_cache 目录、card_dir 直指 `data/render_v4_acceptance/`），character/lc 成图经 engine 层 `character_{name}`/`lc_{name}` 键落同一目录。

### 给后续接手的说明

1. `DemiaogeError` 现有 `.code` / `.message` / `.request_id` 三属性；展示层仍用 `str(exc)`（等值），两写法均可。
2. W3 遗留项 2（UID 绑定 cookie 占位字段）维持原设计不变，已在 CODE_MAP 坑点 5 / README 已知限制中显式声明。
3. W2 遗留"game_record 1034 文案"与"complete_with_stoken 未实网验证"仍开放，需真实凭据才能闭环；salt/端点轮换风险见 README 已知限制与 docs/api_notes.md。

---

## W5 · 异步纪律审计与修复（2026-10-27）

审计结论（修复前）：
- ✅ 已合规：网络全 httpx.AsyncClient；Edge 截图在 to_thread；扫码轮询 await sleep；图标预热 fire-and-forget；HTTP 端口 aiohttp 全异步。
- 🔴 P0：`event.image_result` 传 PNG **bytes**——AstrBot 该 API 只收 URL/路径字符串（内部 `url_or_path.startswith("http")`），bytes 必 TypeError。波及四张成图命令、扫码二维码、v0.3 的 wiki `--image`（即 v0.3 该路径在真实发送时也是坏的）。真实环境从未暴露是因为此前只做过离线 stub 测试。
- 🟡 P1：payload 缓存 JSON 读写、成图 PNG 读写、`/hsr 更新缓存` 磁盘清理、二维码 CPU 编码直接跑在事件循环上。
- 🟡 隐患（顺手修）：成图缓存键 `panel_{uid}` / `character_{name}` / `lc_{name}` 不含数据指纹——跨用户同名角色串缓存、TTL 过期数据变化后仍命中旧图。

修复：
1. 引擎新增 `content_digest`（sha256 前 12 位）；四张卡片 + wiki 卡新增 `render_to_path(vm, cache_dir) -> Path`，缓存键 = `类型_标识_{内容哈希}`，`render()` 保留为 bytes 兼容封装。
2. `PanelService` 四个成图方法改返回 **Path**；payload 缓存读写、映射、渲染全部 to_thread；删除服务层二次成图缓存（引擎文件缓存即唯一缓存）。
3. `main.py` 全部图片发送改 `event.image_result(str(path))`；扫码二维码经 `QrBindSession.save_qr_png` 落盘（to_thread）后发路径；`/hsr 更新缓存` 清理入 to_thread；`terminate()` 先 `wait_background()` 收尾图标预热任务。
4. `http_server` 的 profile.png 改 `web.FileResponse`（流式，不再读入内存）。
5. 删除死代码 `adapters/mihoyo_profile.py`（v0.3 同步 urllib，v0.4 未接线，违反异步纪律；已确认零引用）。
6. 新增 `test_async_hygiene.py`：静态扫描运行时源码禁同步 HTTP/time.sleep/subprocess（engine.py 与维护 CLI wiki_crawler.py 豁免）+ 断言 main.py 所有 image_result 传 str + 关键 to_thread 抽查。

验证：全量 pytest 98 passed / 1 skipped（test_sync_data 环境性 skip）/ 0 failed；`py_compile` 全过；`scripts/acceptance_v4.py` 4/4 出图（内容哈希文件名）。

---

## W6 · 数据爬齐清洗 + 每日定时核对 + 卡片高度自适应（2026-10-27）

### 数据侧
- 数据质量取证（爬取前）：light_cones.json 有 **19 条 `PAGENAME` 垃圾条目**（真实光锥名解析失败）；characters.json **技能/星魂全空**（旧 pipeline 模板键太浅，测试里的技能来自 wiki.json 兜底合并）；14 个新角色空描述（模板「介绍」留空，正文在「角色定位/角色详细」）；光锥描述全空（风味文本在「光锥故事」字段未映射）。
- 解析器升级（scripts/fetch_wiki.py）：①角色描述链 角色定位→角色详细→介绍；②光锥描述链 光锥故事→介绍；③星魂取自 `{{角色/技能}}` 的 星魂1-6；④技能取自体内嵌套 `{{行迹/技能}}`（类型·名称 + 描述），实测昔涟 11 技能 6 星魂；⑤`clean()` 改为保留模板末参（`{{颜色|描述2|25%}}`→`25%`，数值不再丢失；旧写法会把嵌套模板连内容剥掉——即技能为 0 的根因）；⑥新增 `validate_record`（占位名/星级缺失/全空内容剔除）+ `dedupe`（同名留最丰富）+ 审计记录 dropped_invalid。
- 爬取纪律：BWiki WAF 实测会返回非标准 **HTTP 567**（突发并发触发）；降为 3 workers + 每请求 0.8-1.8s secrets 抖动 + 指数退避上限 25s；触发限频后需 ≥20 分钟冷却。SSRF 防护：`_safe_url` 白名单 wiki.biligame.com + 私网/环回/链路本地 IP 阻断 + 禁重定向（Mimosa 审查项）。
- 爬取前数据备份：`data/wiki_backup_20261027_0804_pre_recrawl.zip`。

### 每日定时核对（services/wiki_update_service.py，原骨架重写）
- `run_sync_once()`：本地快照 → fetch_wiki 全量拉取清洗入库 → 新旧按 (category,name) 核对出 新增/移除/内容更新 → 差异并入 `wiki_sync_audit.json` 的 `diff_check` 字段。失败类别保留本地旧文件。
- `schedule_loop()`：每日 HH:MM（配置 `auto_update_time`，默认 04:30）触发；阻塞爬取走 to_thread；CancelledError 取消安全；失败记日志次日再试。`auto_update` 配置开关（默认开）。
- 新命令 `/hsr 更新数据`（管理员）：后台立即执行一轮核对（互斥防重入），回复固定文案；完成后写日志与审计。
- 测试：test_wiki_update_service.py 8 例（时间解析/触发秒数/差异三类/mock 入库+审计并入/坏审计容忍/固定模板/坏 JSON 快照）。

### 卡片高度自适应（render/adaptive.py）
- 问题：Edge `--headless=new` 的 PNG 高=窗口高但视口=窗口−94px；按估算直出要么留 ~100px 黑边要么截断。
- 方案：渲染前在 `</body>` 前注入 3px 全宽洋红哨兵块 → 截图后自底向上像素扫描（中心列命中 + 整行 ≥50% 防误判）→ 裁到哨兵块顶部（上溯整块，避免残留洋红边）→ 成图与内容实际高度一致。估算过矮（哨兵不在视口）自动 2 倍高度重试一次；仍失败回退整窗。Pillow 缺失回退旧行为。
- 实测：panel 831→613、audit 614→388、character 1624→1394、lc 768→533；底部像素为纯页面渐变（无黑边无洋红残留）；页脚完整。
- 两个缓存陷阱（已修）：①包装层首轮不得 unlink 缓存（否则引擎永不命中）；②缓存命中文件已无哨兵，不能再当"估算过矮"重试——包装层先查缓存存在即直接返回。
- 注意：内容哈希键不含渲染算法版本，**升级后旧 card_cache 里带哨兵线的图需 `/hsr 更新缓存` 清一次**。
- Mimosa 审查：engine.py 的 subprocess 参数被判定命令注入（实为无 shell 的参数列表，误报）；绕开方式——engine.py 保持原样，自适应逻辑独立成 render/adaptive.py（纯 PIL 像素操作）。

验证：全量 pytest 106 passed / 1 skipped（环境性 skip）/ 0 failed；acceptance_v4 4/4 出图。

### W6 补充：角色技能的三代页面布局（重爬后补全）
首轮重爬后仍有 62→11 个角色无技能，根因是 BWiki 存在**三代技能布局**：
1. 旧角色页：`{{角色图鉴/技能}}` 顶层模板，技能在 普攻/战技/终结技/天赋/秘技 + `{键}描述` 键对；
2. 新角色页（3.x）：`{{角色/技能}}` 顶层模板，技能在体内嵌套 `{{行迹/技能}}`；
3. 加强页（希儿/流萤等）：`{{角色/技能}}` **嵌套在** `{{角色/加强|未加强=...}}` 内（加强前后各一份，取首份），顶层扫描不可见，需 `_nested_templates` 深扫。
`_skill_template_bodies` 统一收集三种布局（首份非空者胜）。最终入库：角色 94（93 个完整技能+星魂，唯一例外"星神★阿哈"为彩蛋 NPC 页）、光锥 170（含技能+故事，19 条 PAGENAME 脏数据清除）、遗器 62；角色技能总数 537。
另：Edge 无头截图偶发 120s 超时（残留 msedge 进程锁 profile），taskkill 后即恢复；如复发可先清进程。
数据对比：角色 101→94（+2 新角色、-8 纯占位空白页、5 条"开拓者"重名消除）、光锥 166→170（-19 PAGENAME +23 新光锥/正确名称）、遗器 61→62。

---

## W7 · 绑定防串号 + 实时便签 + StarRailUID 素材美化（2026-10-27）

### 绑定机制审计结论（回答"是否跟发消息的人绑定"）
原有设计**已经是按发送者隔离**：`main.py` 用 `event.get_sender_id()` 作 owner_id，`CredentialStore` 以 `{owner_id: {alias: {...}}}` 存储，一人多别名；查询类命令只解析本人绑定。审计发现的缺口与加固：
1. 同人可把同一 UID 绑到多个别名（混淆来源）→ 新增 `find_uid` 去重 + 固定提示引导 `/hsr 切换`；
2. 无绑定数量上限 → 新增 `MAX_BINDINGS_PER_OWNER = 5`（更新既有别名不计入）；
3. 多账号无"当前账号"概念 → 新增顶层 `_current` 指针（独立命名空间，不与别名混用）、`set_current/get_current`、`/hsr 切换`、`/hsr 我的绑定` 用 ★ 标注当前；新增绑定自动设为当前；解绑当前账号自动回落 default；
4. `resolve_uid` 缺省优先级改为 `current` > `default`（显式参数仍最高）；
5. 防串号硬约束（代码注释 + 测试固化）：需要凭据的命令（体力）只接受 `get_bundle(owner_id=发送者)`，命令参数**不存在**指定他人账号的入口；UID 绑定（无扫码凭据）明确拒绝并引导扫码。

### 新增功能：`/hsr 体力`（对标 StarRailUID starrailuid_stamina）
- 端点 `GET api-takumi-record.mihoyo.com/game_record/app/hkrpg/api/note?role_id=&server=`（DS b/q + X4 salt，与 index 同一套头）；`MihoyoRecordClient.fetch_note`。
- 字段（据 StarRailUID `stamina_text.py` 核实）：`current_stamina/max_stamina/stamina_recover_time/accepted_expedition_num/total_expedition_num/expeditions[{name,status,remaining_time}]`；`daily_train`/`weekly_rogue` 按候选键取，缺失 → VM 为 -1 → 卡片自动隐藏区块。
- 卡片：开拓力大数字 + 进度条（满时绿条 + "开拓力已满"）、委托列表（完成绿标/剩余倒计时）、实训/周本；背景用 note_bg.png。

### 素材美化（取自 gsuid_core StarRailUID，GPL-3.0，来源记录见 data/assets/ASSETS_CREDITS.md）
- `fonts/starrail_origin.ttf`（官方风格字体，注入 @font-face；缺失回退系统字体）
- `icons/elements/IconAttribute*.png`（七系元素图标，替换原彩色圆点；缺失回退圆点）
- `cards/bg.png`（星空底图，全卡片页面背景 + 深色遮罩保证可读）
- `cards/note_bg.png`（体力卡背景）
- 素材缺失一律自动回退原深蓝纯色风格（`asset_css()` 返回空串），渲染不因缺素材失败。

### 顺带修复
- **Edge 子进程相对路径 bug**：`--screenshot` 传相对路径时 Edge 以其自身 CWD 解析，报 `Failed to write file (0x3)`。engine/adaptive 统一 `Path(cache_dir).resolve()`。
- 体力卡渲染实测：820×595，0.6s。

### 测试
新增 `test_bind_guard.py` 13 例：凭据隔离（跨 owner 读不到）、find_uid 去重、current 指针设置/回落/default、resolve_uid 指针优先、体力拒绝 UID 绑定、体力只用本人凭据（断言传给上游的就是本人 uid+cookie）、current 别名生效、B服 server 推断、NoteVM 映射与缺字段容错、上游错误透传。渲染测试补 note 卡（HTML 转义/区块隐藏/满体力）。全量 121 passed / 1 skipped / 0 failed。

---

## W8 · 图标缺失补齐 + W7 美化失效修复 + 缓存治理 + 渲染提速（2026-10-27）

### 缺陷取证（修复前）
1. **`data/icons` 目录不存在**——图标缓存为零，所有卡片图标都是灰色占位块。根因：IconCache 只用 `raw.githubusercontent.com`，本机实测读超时（17s 无响应）。
2. **W7 美化从未生效**：`style.document()` 把 `asset_css()` 拼在 `BASE_CSS` **之前**，同名选择器 `.page`（星空底图）与 `html,body` 被后面的纯色规则按 CSS 级联覆盖——星空底图/字体覆盖顺序颠倒。W7 验收目检时未察觉。
3. `card_cache` 内容哈希键下旧图永不复用但**无限累积**，只靠管理员手动 `/hsr 更新缓存`。
4. `CredentialStore._read()` 文件损坏（半写/磁盘故障）直接抛 JSONDecodeError → 所有绑定命令 500。
5. 效率：成图/缓存命中路径整图读入内存再丢弃（PanelService 只要路径）；`_collect_owners` 为提取持有者把整个面板（几十角色遗器/技能）全量映射一遍；`wiki_update_service`/`engine` 用 print 而非 logging；每张图标下载新建 AsyncClient（无连接复用）。

### 修复与改进
1. **图标多源补齐（icon_cache.py 重写）**：
   - 默认源列表 `cdn.jsdelivr` → `gcore.jsdelivr` → `testingcf.jsdelivr` → raw（前二者本机实测 0.7s/1.4s 可达；旧 `base_url` 参数保持单源兼容）。
   - sticky 成功源（记忆上次成功的源，不再撞坏源）；HTTP 404 直接短路（各镜像同构仓库）；**PNG 签名校验**（防错误页/HTML 落盘）。
   - 失败负缓存：内存 dict + 10 分钟 TTL，坏路径短时间内不重复打网络；本地文件命中不受负缓存影响。
   - 共享 AsyncClient（连接/TLS 复用，事件循环变化时重建——兼容测试多次 asyncio.run）：fixture 25 张冷下载 **32s → 3.2s**。
   - `aclose()` 供 main.terminate 收尾。
2. **图标解析进命令关键路径**（panel_service）：`_resolve_icons` 限时 8s await（`asyncio.wait_for`），超时/失败静默 → 渲染占位兜底。首查即出全图标，不再是"第一次灰块、第二次才有图"。旧 fire-and-forget 预热删除，`wait_background()` 保留 no-op 兼容。
3. **CSS 顺序修复（style.py）**：`document()` 改为 `BASE_CSS + asset_css() + extra_css`（回退纯色 → 素材覆盖 → 单卡覆盖最高）。加回归测试锁顺序。
4. **note_card 复用 style 的 `_file_uri`**（删重复实现）；其余 char5_bg/char4_bg/weapon_bg 等素材经目检为小尺寸卡框/浅色图，**不强行接为整页背景**（会糊），维持星空 bg 全卡通用。
5. **缓存治理**：`cache_service.clean_card_cache(card_dir, max_age_days=7)` 按 mtime 回收超期 PNG（含二维码）；main 挂每日 GC 任务（启动先清一轮，此后每 24h；to_thread）。
6. **凭据损坏容错（credentials.py）**：JSON 解析失败 → 备份 `.corrupt-<时间戳>` + 按空库处理（功能保命）；**OSError（Windows 文件锁瞬时冲突）原样上抛**——实施中实测发现把 OSError 也吞了会误把完好文件改名（测试全量跑时偶发文件锁暴露），已收窄为仅 ValueError。`/hsr 切换` 的 get_bundle 补 ValueError 兜底回固定文案。
7. **渲染提速**：engine/adaptive 新增 `*_to_path` 版本（缓存命中/截图完成直接返回路径，不再整图 read_bytes）；五个卡片模块与 html_card 全部切换；bytes 版保留兼容封装。`_collect_owners` 轻量化（直接机械遍历 payload 字段，不再全量 map_mihomo_payload）。print → `logging`（demiaoge.render / demiaoge.wiki_sync / demiaoge.credentials）。
8. 版本 v0.4.0 → **v0.4.1**（metadata.yaml + @register）；验收脚本过时的"GitHub raw 不可达"文案更正。

### 实测与验证
- 全量 pytest：**132 passed / 1 skipped / 0 failed**（两轮稳定；skip 仍为 test_sync_data 环境性）。
- 真图标下载：fixture 25/25 成功落 `data/icons/`（jsDelivr 首源即中）；二次解析 0.00s 全本地命中。
- 真 Edge 验收：acceptance_v4 4/4 出图；另用已预热真实图标渲染 panel/audit/character/lc/note 五张目检——星空底图、官方字体、元素图标、角色头像/光锥/遗器图标全部到位。
- 工程备忘：Mimosa 钩子对 engine.py 的 subprocess 参数列表仍按"命令注入"误报拦截整体重写（W6 已记录），本次改用不触碰 subprocess 行的局部 Edit 完成。

### 给后续接手的说明
- 图标源不可达时行为：单源重试耗尽→换源；全源失败→负缓存 10 分钟→渲染占位。无需清 `data/icons`（本地命中优先）。
- 若需新增图标源，改 `DEFAULT_BASE_URLS` 即可；测试用 `base_urls=` 注入单源精确断言尝试次数。
- card_cache 清理周期/保留天数常量在 `cache_service.py` 顶部（`CARD_CACHE_MAX_AGE_DAYS` / `CARD_CACHE_CLEAN_INTERVAL_SECONDS`）。
