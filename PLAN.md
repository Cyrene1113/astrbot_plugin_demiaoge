# 德谬歌：崩坏：星穹铁道查询插件最终方案

> 插件目录：`astrbot_plugin_demiaoge`

## v0.4 阶段记录（2026-10-27）

v0.4 已按五个波次全部交付：W1-A 调研（实测 Mihomo API 与扫码端点，落 `docs/api_notes.md` 与 `data/fixtures/`）→ W1-B 渲染（`render/engine.py` 抽取 + 面板/练度/角色/光锥四模板）→ W2 适配器（Mihomo 客户端、DS 签名、米游社扫码状态机、图标缓存、映射器 v2、凭据存储 v2）→ W3 集成（`main.py` 全命令接线、UID 解析/面板/绑定/HTTP 服务、`_conf_schema.json` 8 项配置）→ W4 验收收尾（全量回归 94 passed + 1 skipped + 0 failed，`metadata.yaml` 升 v0.4.0，README/CODE_MAP 重写，`scripts/acceptance_v4.py` 真 Edge 出 4 张验收图至 `data/render_v4_acceptance/`）。规格与实测过程的权威记录见 `DEVELOPMENT.md` 与 `docs/wave_notes.md`（W1-A/W2/W3/W4 各节），上游端点与字段以 `docs/api_notes.md` 为准。

## Wiki 查询改进进度（本次完成）

- Wiki 查询已按“名称精确 → 别名精确 → 名称包含 → 别名包含”的优先级决策。
- 包含匹配按命中位置、命中长度排序；最高分唯一时直接返回，否则保留候选列表兜底。
- 多关键词采用 AND 匹配。
- 精确命中结果支持基于 tags/description 的简单“相关”提示。
- `WikiEntry` 增加 `version` 字段，用于后续增量更新判断。
- 新增 `data/aliases.json` 与 `domain/alias_models.py`，独立维护黑话、外号和英文别名。

## 数据源适配与更新骨架（本次完成）

- 新增 `adapters/wiki_sources.py`：B 站 biligame 首选源和米游社备用源接口骨架。
- 新增 `services/wiki_update_service.py`：后台异步更新、限速间隔、异常静默回退本地缓存的流程骨架。
- 在线源解析已由 `scripts/fetch_wiki.py` 实现：只读取 BWiki API 的三个 namespace=0 分类目录，逐页 parse，当前远端集合全量重建正式 JSON，并按类别原子替换；失败明细写入 `data/wiki_sync_audit.json`。查询路径仍只读本地快照。

## Wiki 全量数据与图片卡片（本次完成）

- 已将工作区验证通过的三份全量数据转换并同步到 `data/`；原数据已打包保存为 `data/wiki_backup_20260806_new_pipeline.zip`。
- 新增 `services/wiki_crawler.py`：按类别保存 raw 缓存，支持增量/断点续爬、`--parse-only` 重解析、限速、重试、日志和原子输出。
- 新增 `render/html_card.py`：使用标准库生成 HTML，调用 Edge 无头截图；每次截图使用唯一目标文件，避免旧文件覆盖问题，并缓存 PNG。
- `/hsr wiki <名称>` 保留文字查询；`/hsr wiki <名称> --image` 输出 Wiki 图片卡片。Edge 不可用时明确回退为文字结果。
- `WikiService` 继续消费转换后的 `WikiEntry` 数据，角色/光锥/遗器字段已由转换脚本适配。

## 本次修复（2026-08-07）

- `render/html_card.py` 改为按描述、技能、星魂的实际字段内容估算高度，并增加长文本换行与溢出保护，角色卡/光锥卡不再使用固定高度造成大片黑底。
- 卡片渲染增加冷启动与缓存命中耗时日志（`card rendered` / `card cache hit`），用于现场比较优化前后耗时。
- 角色卡继续逐项渲染 `skills`、`eidolons`；昔涟正式数据已核验包含 4 项技能和 3 项星魂。
- 依据插件正式 `data/light_cones.json` 核验，昔涟对应的专属光锥名称为「爱如此刻永恒」；「愿虹光永驻天空」为另一条正式光锥数据，不作替换。
- 已生成并检查两张验收 PNG：昔涟角色卡、爱如此刻永恒光锥卡；未重载插件。

## 验收记录（2026-08-07）

- 根因：角色正式快照中的昔涟 `skills`/`eidolons` 为空，且渲染器只加载分片数据；卡片 viewport 采用粗略固定模板估算，短内容因此留下大片页面底色。
- 修复：合并同名数据时选择技能/星魂字段更完整的正式记录；渲染高度按实际描述、标签、技能和星魂文本估算；保留 Edge 冷启动与缓存命中计时。
- 数据核验：BWiki `api.php?action=parse&page=昔涟&prop=wikitext` 返回昔涟角色图鉴页（命途记忆、冰属性、3.7）；本地正式光锥数据明确记录昔涟专属光锥为「爱如此刻永恒」，其效果为「约定」。未将「愿虹光永驻天空」替换为该名称。
- 图片验收：以本地正式 `wiki.json` 的昔涟记录和 `light_cones.json` 的爱如此刻永恒记录生成；应检查 PNG 元数据、内容文本和边缘/背景比例。
- 未重载插件（按要求）。
- 本轮实测：`python -m pytest -q test_render_acceptance.py` 需从插件父目录运行；验收脚本会输出 cold/cache 耗时、PNG 尺寸和暗像素比例。

## 后续维护

- 在线更新建议在维护窗口执行 `python scripts/fetch_wiki.py`；它不读取旧缓存或工作区数据，完成后直接原子更新三份正式 JSON，并生成审计报告 `data/wiki_sync_audit.json`。查询运行时只读本地快照。

## 原有方案与接口调研

原有架构、米游社账号接口调研和渲染方案仍保留在 Git 历史中；本文件此前的阶段记录已由本次 Wiki 进度摘要替代，后续新增阶段记录应继续追加。
