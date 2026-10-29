# 德谬歌 W1-A · 外部 API 权威笔记

> 产出：W1-A 调研子代理（2026-10-26）。
> 标注约定：**[实测]** = 本机 python httpx 真实请求验证；**[文献]** = 开源实现源码/文档提取，未实测；**[单源]** = 仅一个来源，未交叉验证。
> 所有源码快照存于 `data/fixtures/_src_*.json`（保留供 W2 复查），证据日志 `_qr_probe_log.json`、`_gettoken_probe_log.json`。

---

## 1. 端点总表

### 1.1 Mihomo API（免 Cookie 主路径）【实测】

| 项 | 值 |
|---|---|
| 主端点 | `GET https://api.mihomo.me/sr_info_parsed/{uid}?lang=cn` **[实测]** |
| 可选参数 | `language`/`lang`/`l` 三名等价；`version`/`ver`/`v`；`is_force_update`（OpenAPI 确认） |
| OpenAPI 全族 | `GET /sr_info/{uid}`(原始)、`/sr_info_parsed/{uid}`(解析)、`/sr_activity/{uid}`、`/sr_panel/{uid}`、`/panel/{file_path}`、`/fonts/{file_path}`（`https://api.mihomo.me/openapi.json` **[实测]**） |
| 成功 | 200，`{"player": {...}, "characters": [...]}`（schema 见 §2） |
| 建议请求头 | 标准 UA 即可，无需 Cookie/DS **[实测]** |
| 缓存响应头 | `cache-control: max-age=43200, no-cache`、`x-cache: MISS`（Cloudflare） |

官方 Pydantic 模型库（字段权威参考）：[MetaCubeX/mihomo](https://github.com/MetaCubeX/mihomo)（`mihomo/client.py` 定义 `ASSET_URL` 与错误映射）；官方使用文档：[March7th Parsed Data API](https://march7th.xyz/ja/api/parsed.html)。

### 1.2 米游社 game_record（Cookie 降级路径）【文献】

基址 `https://api-takumi-record.mihoyo.com/game_record/app/hkrpg/api/`（B 服 uid 走同一基址，server 参数区分）。
端点与 query（均字母序，来源 [Miao-Yunzai apiTool.js](https://github.com/yoimiya-kokomi/Miao-Yunzai/blob/master/plugins/genshin/model/mys/apiTool.js)）：

| 端点 | query（字母序） | 说明 |
|---|---|---|
| `index` | `role_id={uid}&server={server}` | 首页宝箱/开拓等级 |
| `role/basicInfo` | `role_id={uid}&server={server}` | 基础信息 |
| `challenge` | `role_id={uid}&schedule_type={1}&server={server}` | 混沌回忆 |
| `avatar/info` | `need_wiki=true&role_id={uid}&server={server}` | 角色详情 |
| `avatar/basic` | `role_id={uid}&server={server}` | 角色列表 |
| `note` | `role_id={uid}&server={server}` | 树脂（开拓力） |

- `server` 取值：官服 `prod_gf_cn`，B服 `prod_qd_cn`（[Miao-Yunzai mysApi.js game_region](https://github.com/yoimiya-kokomi/Miao-Yunzai/blob/master/plugins/genshin/model/mys/mysApi.js)）【文献】
- 必需头（Miao-Yunzai cn 客户端组合，生产验证多年）：`DS`（§3 公式+salt）、`x-rpc-app_version: 2.40.1`、`x-rpc-client_type: 5`、`User-Agent: Mozilla/5.0 ... miHoYoBBS/2.40.1`、`Referer: https://webstatic.mihoyo.com/`、`Cookie`（含 stoken/ltuid/ltoken）
- W2 只需实现 `index` 查询映射（DEVELOPMENT.md §3.2）。

### 1.3 扫码登录（米游社绑定）【实测】

存在三个变体；**推荐 W2 用 web 变体**（实测全通、无需过 app 风控），app 变体为 xiaoyao 同款备用。

#### 变体 A：passport web 变体（UIGF 文档 + 本次实测全通）

| 步骤 | 端点 | 说明 |
|---|---|---|
| 1 创建 | `POST https://passport-api.miyoushe.com/account/ma-cn-passport/web/createQRLogin`，body `{}` | **[实测 retcode=0]** 返回 `data{url, ticket}`；仅需头 `x-rpc-app_id: bll8iq97cem8` + `x-rpc-device_id: <uuid>`，**无需 DS** 【实测】；文档同 [UIGF qrcode_hoyolab](https://github.com/UIGF-org/mihoyo-api-collect/blob/main/hoyolab/login/qrcode_hoyolab.md) |
| 2 轮询 | `POST https://passport-api.miyoushe.com/account/ma-cn-passport/web/queryQRLoginStatus`，body `{"ticket":"..."}` | **[实测 retcode=0，初始 status="Created"]**；返回 `data{status, app_id, client_type, created_at, scanned_at, tokens, user_info, realname_info, need_realperson, ext, scan_game_biz}` |
| 3 确认后 | Confirmed 响应的 `data.user_info{aid, mid, ...}` + 响应头 `Set-Cookie`（含 cookie_token/LToken v2） | 【文献 UIGF】 |

#### 变体 B：passport app 变体（xiaoyao 同款）

| 步骤 | 端点 | 说明 |
|---|---|---|
| 1 创建 | `POST https://passport-api.mihoyo.com/account/ma-cn-passport/app/createQRLogin`，body `{}` | **[实测 retcode=0]** 需 DS（PROD salt，§3）与完整 `pass` 头（§3.3）【实测】 |
| 2 轮询 | `POST https://passport-api.mihoyo.com/account/ma-cn-passport/app/queryQRLoginStatus`，body `{"ticket":"..."}` | **[实测被风控]** 本机返回 `retcode=-3503 "请求失败，当前设备或网络环境存在风险"`（换随机 device_id、补全 header 集两次均复现）——DS 本身有效（create 已过验签），疑为固定 device_fp `38d7ee0e96649`（xiaoyao 硬编码值，全网滥用）+ 数据中心 IP 触发风控。**W2 需自研 device_fp 或优先变体 A** |
| 3 兑换 | `POST https://passport-api.mihoyo.com/account/ma-cn-session/app/getTokenByGameToken`，body `{"account_id":<uid:int>,"game_token":"..."}` → `data.token.token`(stoken v2) + `data.user_info{aid,mid}` | 【文献】xiaoyao 用 PROD salt + b/q DS；jiarui666 用 salt `OvOIsZRXrUbXoUlpQuhEx4tgAwNVUMmp` + r=6位字母 + 小写 `ds` 头。**两实现冲突，本次用无效 game_token 探测两种 salt 均返回 `-5300 "请升级应用版本或删除账号后重新登录"`，无法裁决** → 标注 **未实测通过，需 W2 持真实 game_token 再验**。出处：[xiaoyao mihoyoApi.js](https://github.com/ctrlcvs/xiaoyao-cvs-plugin/blob/master/model/mys/mihoyoApi.js) / [jiarui666/mihoyo_qr_login qr_login.py](https://github.com/jiarui666/mihoyo_qr_login/blob/main/qr_login.py) |
| 4 换 cookie | `GET https://api-takumi.mihoyo.com/auth/api/getCookieAccountInfoByGameToken?account_id={uid}&game_token={gt}` → cookie_token | 【文献】xiaoyao 同款（GET query，无 DS）。注意 DEVELOPMENT.md §3.3 原计划写的是 `api-takumi.miyoushe.com` POST，xiaoyao 实际用 `api-takumi.mihoyo.com` GET，两者或均可用，W2 以 xiaoyao 为准 |
| 5 兑换 ltoken（可选） | `GET https://passport-api.mihoyo.com/account/auth/api/getLTokenBySToken?stoken={stoken}`（Cookie: mid=..;stoken=..） | 【文献】[mystool simple_api.py](https://github.com/ayakasuki/nonebot_plugin_mystool/blob/stable/simple_api.py) |

#### 变体 C：hk4e-sdk 游戏内扫码（原神向，不推荐）

`POST https://hk4e-sdk.mihoyo.com/hk4e_cn/combo/panda/qrcode/fetch`（body `{app_id:"7", device}`，无 DS）→ query 同域 `/query`，status 取值 `Init/Scanned/Confirmed`，Confirmed 后 `payload.raw`(JSON 字符串) 内含 `uid`+`token`(game_token)。出处：[jiarui666/mihoyo_qr_login](https://github.com/jiarui666/mihoyo_qr_login/blob/main/qr_login.py)。**仅作参考，德谬歌不用。**

> 注：DEVELOPMENT.md §3.3 原计划的 `POST https://api-takumi.miyoushe.com/auth/api/createQRLogin` 为老版米游社端点，本次调研的 4 个现代实现（xiaoyao/mystool/jiarui666/UIGF）均已迁移到 passport-api 域，未找到仍在用老端点的在维护实现。**W2 直接采用变体 A/B，不要用老端点。**

### 1.4 静态资源（图标）【实测】

- API 返回的 icon/preview/portrait 均为**相对路径**（如 `icon/character/1310.png`、`icon/avatar/IconHead_202006.png`）。
- 资源基址 **[实测确认]**：`https://raw.githubusercontent.com/Mar-7th/StarRailRes/master` + 相对路径
  - 出处：[MetaCubeX/mihomo client.py](https://github.com/MetaCubeX/mihomo/blob/main/mihomo/client.py)（`ASSET_URL` 常量，官方模型库）
  - 实测：`.../icon/path/Destruction.png` → 200 `image/png` 35340B PNG magic ✓；`.../icon/character/1310.png` → 200 `image/png` 151090B PNG magic ✓（带第三方 Referer + 自定义 UA，无防盗链）
- DEVELOPMENT.md §3.4 写的 `api.hakush.in/hsr/UI/...` **不适用于 Mihomo API 返回的相对路径**（该域名本机 DNS 无法解析，亦无必要）。
- ⚠️ 本机到 raw.githubusercontent.com 连接**不稳定**（多次 ConnectTimeout/10054/ssl 握手超时，重试 1-3 次可成功）。W2 图标下载必须带重试+超时+失败占位（开发计划已有此设计，勿省略）。

---

## 2. Mihomo `sr_info_parsed` 实测 schema

fixtures：`data/fixtures/mihomo_sr_info_parsed.json`（player 全量 + 前 3 角色完整）、`data/fixtures/mihomo_full_one_character.json`（首角色完整原始 JSON，零删减）。样例 uid=100895290（官方文档示例，2026-10-26 实测 6 角色）。

### 2.1 player【实测字段全列】

```text
uid: str            昵称下方 UID（字符串，非数字）
nickname: str       昵称
level: int          等级
world_level: int    世界等级（均衡等级）
friend_count: int   好友数
avatar: {id: str, name: str, icon: str}     头像（icon 为相对路径 icon/avatar/IconHead_xxx.png）
signature: str      签名
is_display: bool    是否开启角色展示（ true 时 characters 才有数据）
space_info: {memory_data: {level, chaos_id, chaos_level, chaos_star_count},   // 模拟宇宙/忘却之庭
             universe_level: int, avatar_count, light_cone_count, relic_count,
             achievement_count, book_count, music_count}
```

### 2.2 character item【实测字段全列】

```text
id: str             角色ID（如 "1310"）
name: str           角色名
rarity: int         星级 4/5
rank: int           星魂数 E0-E6（0~6）
level: int          等级
promotion: int      突破阶 0-6
enhanced: bool      是否点亮额外能力（行迹强化）——注意本字段文档未提，实测存在
icon: str           "icon/character/{id}.png"
preview: str        "image/character_preview/{id}.png"
portrait: str       "image/character_portrait/{id}.png"
rank_icons: [str]   星魂图标 ×6（"icon/skill/{id}_rank{n}.png"）
path:    {id: str("Warrior"), name: str("毁灭"), icon: str}
element: {id: str("Fire"), name: str("火"), color: str("#F84F36"), icon: str}
skills: [{id, name, level, max_level, element{...同上}, type("Normal"等),
          type_text("普攻"), effect("SingleAttack"), effect_text("单攻"),
          simple_desc, desc, icon}]                  实测 8 项（含普攻/战技/终结技/天赋）
skill_trees: [{id, level, anchor("Point01"), max_level, icon, parent}]   实测 18 项（行迹）
light_cone: {id, name, rarity, rank(叠影), level, promotion, icon, preview,
             portrait, path{...}, attributes[{field,name,icon,value,display,percent}],
             properties[...]}      可能为 null（角色未装备时，样例 6 角色均有值）
relics: [{id, name, type(1-6部位), set_id, set_name, rarity, level(0-15), icon,
          main_affix{type, field, name, icon, value, display, percent},
          sub_affix[{type, field, name, icon, value, display, percent, count, step}]}]   实测恒 6 件
relic_sets: [{id, name, icon, num(2/4), desc, properties[...]}]
statistics: [{field, name, icon, value, display, percent}]   面板白值×9（含速度/暴击等）
attributes: [{...同形}]   基础属性×6
additions:  [{...同形}]   加成属性×9（含击破/效果命中等）
properties: [{type, field, name, icon, value, display, percent}]   最终面板×12
pos: [int, ...]      立绘站位索引（实测样例 [0,6]/[1]/[2,7]/[3]/[4]/[5]，具体含义未确认，勿依赖）
```

### 2.3 affix/property 通用结构

```text
{type: str(如 "HPDelta"/"AttackDelta"/"BreakDamageAddedRatioBase"),
 field: str(如 "hp"/"atk"/"def"/"break_dmg"/"spd"/"crit_rate"/"crit_dmg"),
 name: str(中文名), icon: str(相对路径),
 value: float(原始值，百分比类为小数), display: str("705"/"10.2%"),
 percent: bool}
sub_affix 额外: count: int(词条数), step: int(强化档)
```

与 DEVELOPMENT.md §3.1 的差异：文档猜测的 `stats[]` 实测字段名为 `statistics[]`（另有 `attributes/additions/properties` 三组）；`path{name,icon}` 实测还含 `id`；`element` 还含 `color`。**mapper（W2）以本节为准。**

---

## 3. DS 签名与 salt（含出处）

### 3.1 通用公式

DS 头格式：`{t},{r},{sign}`，`t = int(time.time())`（秒）。

| 类型 | sign 公式 | 适用 |
|---|---|---|
| 简单式 | `md5("salt={salt}&t={t}&r={r}")` | bbs 签到/stoken 兑换等（mystool `generate_ds` 前分支） |
| b/q 式 | `md5("salt={salt}&t={t}&r={r}&b={body}&q={query}")` | **game_record 全部**、passport app 变体（注意：字符串里 **b 在 q 前**） |

- GET 请求：`b=""`，`q = query串按参数名字母序排列后 k=v&k=v`（Miao-Yunzai apiTool.js 中所有 query 均已按字母序硬编码：`role_id<schedule_type<server`、`need_wiki<role_id<server` 等）。
- POST 请求：`b=JSON.stringify(body)`，`q=""`；body 为空对象时 `b="{}"`（xiaoyao `getUrl`: `if (body) body = JSON.stringify(body)`；mystool 对 SALT_PROD 空数据同样置 `{}`）。
- r 取值：6 位数字 `100000~200000`（Miao-Yunzai `Math.random()*900000+100000`、xiaoyao/mystool `100001~200000`）；仅 jiarui666 的 K2 分支用 6 位小写字母。**W2 统一用 6 位数字即可。**

### 3.2 salt 值清单（出处链接 + 交叉验证状态）

| 用途 | 常量名 | salt 值 | 交叉验证 |
|---|---|---|---|
| **game_record（hkrpg/genshin，CN）** | x4 / LK2 | `xV8v4Qu54lUKrEYFZkJhB8cuOh9Asafs` | ✅ 3 源一致：[Miao-Yunzai mysApi.js](https://github.com/yoimiya-kokomi/Miao-Yunzai/blob/master/plugins/genshin/model/mys/mysApi.js)（getDs 内硬编码）、[MihoyoBBSTools setting.py](https://github.com/Womsxd/MihoyoBBSTools/blob/master/setting.py)（`mihoyobbs_salt_x4`）、[nonebot_plugin_mystool plugin_data.py](https://github.com/ayakasuki/nonebot_plugin_mystool/blob/stable/plugin_data.py)（`SALT_PARAMS`） |
| game_record（海外 OS） | LK2-os | `okr4obncj8bw5a65hbnn5oo6ixjc3l9w` | ⚠️ 单源（Miao-Yunzai）。国服插件用不到 |
| passport app 变体 QR / token 兑换（CN） | PROD / passSalt | `JwYDpKvLj6MrMqqYU6jTKF17KNO2PXoS` | ✅ 3 源一致：[xiaoyao mysTool.js](https://github.com/ctrlcvs/xiaoyao-cvs-plugin/blob/master/model/mys/mysTool.js)（`passSalt`）、[mystool plugin_data.py](https://github.com/ayakasuki/nonebot_plugin_mystool/blob/stable/plugin_data.py)（`SALT_PROD`）、UIGF salt 汇总 [issue #1](https://github.com/UIGF-org/mihoyo-api-collect/issues/1)。**实测通过**（createQRLogin retcode=0） |
| getTokenByGameToken（jiarui666 分支） | K2 | `OvOIsZRXrUbXoUlpQuhEx4tgAwNVUMmp` | ⚠️ 单源（[jiarui666](https://github.com/jiarui666/mihoyo_qr_login/blob/main/qr_login.py)），与 PROD salt 分支冲突，实测无法裁决（见 §1.3 变体 B 步骤 3） |
| bbs 米游币/签到（带 b/q） | x6 / DATA | `t0qEgfub6cvueAPgR5m9aQWWVciEer7v` | ✅ 2 源：[MihoyoBBSTools](https://github.com/Womsxd/MihoyoBBSTools/blob/master/setting.py)（`mihoyobbs_salt_x6`）、[mystool](https://github.com/ayakasuki/nonebot_plugin_mystool/blob/stable/plugin_data.py)（`SALT_DATA`）。德谬歌暂用不到 |
| bbs 签到（简单式，老版本） | — | `S9Hrn38d2b55PamfIR9BNA3Tx9sQTOem`（xiaoyao 注 k2）、`47f15f1b66bee46b816115d8e8e6ebb6`（BBSTools salt）等 | ⚠️ 各项目不同且随版本轮换，德谬歌暂用不到，不采信 |
| iOS/Android 简单式 | SALT_IOS/ANDROID | `ulInCDohgEs557j0VsPDYnQaaz6KJcv5` / `n0KjuIrKgLHh08LWSCYP0WXlVXaYvV64` | ⚠️ 单源（mystool）。德谬歌暂用不到 |

> salt 与 `x-rpc-app_version` 存在配对关系（MihoyoBBSTools 注释"Salt和Version相互对应"）。W2 若遇验签失败，优先调整 app_version 组合：game_record 用 `2.40.1`+`x-rpc-client_type: 5`（Miao-Yunzai 生产组合），passport 用 `2.70.1`+`client_type: 2`（xiaoyao 实测组合）。

### 3.3 passport app 变体完整 `pass` 头（xiaoyao 同款，createQRLogin 实测通过）

```text
x-rpc-app_id: bll8iq97cem8      （米游社 SDK 固定值，3 源一致）
x-rpc-device_id: <uuid4 大写>
x-rpc-device_fp: 38d7ee0e96649  （xiaoyao 硬编码；⚠️ 疑与 query 阶段 -3503 风控相关，W2 建议随机 13 位 hex）
x-rpc-device_name: <随机串>
x-rpc-device_model: <随机串>
x-rpc-app_version: 2.70.1       （xiaoyao mysTool.js APP_VERSION）
x-rpc-client_type: 2            （1=iOS 2=Android 4=Web 5=Hyperion）
x-rpc-game_biz: bbs_cn
x-rpc-sdk_version: 1.3.1.2
x-rpc-sys_version: 11
x-rpc-channel: appstore
x-rpc-aigis: ""                 （风控挑战票据，初始留空）
Content-Type: application/json;
User-Agent: okhttp/4.8.0
DS: {t},{r},{md5(salt=PROD&t=&r=&b={body}&q=)}
```

---

## 4. 错误码与响应形状

### 4.1 Mihomo API【实测】

| 场景 | HTTP | body | 归类建议 |
|---|---|---|---|
| 成功 | 200 | `{"player":{...},"characters":[...]}` | — |
| uid 格式非法（含过短如 `1`） | 400 | `{"detail":"Invalid uid"}` | DATA_NOT_FOUND（固定文案） |
| 格式合法但不存在/未开展示 | 404 | `{"detail":"User not found"}` | DATA_NOT_FOUND 或 NOT_PUBLIC（无内容区分时统一文案） |
| 路径为空 | 404 | `{"detail":"Not Found"}` | 插件内不会发生 |
| 官方模型库错误映射 | — | 400→`InvalidParams`，404→`UserNotFound`（[MetaCubeX/mihomo errors](https://github.com/MetaCubeX/mihomo/blob/main/mihomo/errors.py)） | 与实测一致 |

### 4.2 米游社/ passport【实测 + 文献】

| retcode | message（实测/文献原文） | 含义 | 来源 |
|---|---|---|---|
| 0 | OK | 成功 | 实测 |
| -3001 | 请求头缺少部分参数 | 缺 x-rpc-app_id/device_id 等 | 文献 UIGF |
| -3501 | 二维码已失效，请刷新后重新扫描 | QR 过期（约 3 分钟） | 文献 UIGF |
| -3503 | 请求失败，当前设备或网络环境存在风险 | 设备指纹/IP 风控（app 变体 query 实测复现） | 实测 |
| -3505 | 扫码登录已取消，重新生成二维码 | 用户取消 | 文献 UIGF |
| -5300 | 请升级应用版本或删除账号后重新登录… | 版本/风控层拒绝（getTokenByGameToken 无效探测实测复现） | 实测 |
| -102 | 请求头缺少 DS 或 DS 不合法（常见文献值） | 验签失败 | 文献（未实测） |
| -110 | 请求过于频繁（限频，常见文献值） | 触发限频 | 文献（未实测） |
| 1034 | 风控拦截（常见文献值，验证码 challenge） | 触发安全验证 | 文献（未实测） |
| HTTP 404/412 | — | 路径错误/疑似风控前置 | 文献 |

---

## 5. 扫码状态机（W2 变体 A 实现指引）

```text
1  POST web/createQRLogin  body {}        （头仅需 x-rpc-app_id + x-rpc-device_id）
   ├─ retcode!=0 → 回"二维码生成失败，请稍后再试"
   └─ data{url, ticket} → qrcode 库生成 PNG（内容 = url），
      固定文案：「请用米游社App扫描二维码：App → 我的 → 右上角扫一扫」
2  每 2s POST web/queryQRLoginStatus body {"ticket": ...}，最多 90 次/180s
   ├─ retcode 0 且 status="Created"   → 静默继续
   ├─ retcode 0 且 status="Scanned"   → 回「已扫码，请在手机上确认」（只提示一次）
   ├─ retcode 0 且 status="Confirmed" → user_info{aid, mid} + Set-Cookie（cookie_token/LToken v2）→ 进入第 3 步
   ├─ retcode -3501 → 回「二维码已失效，请重新发送 绑定」
   ├─ retcode -3505 → 回「已取消扫码」
   ├─ retcode -3503 → 回「触发了安全验证，请稍后再试」（W1-A 实测：app 变体在数据中心网络下复现；web 变体未复现）
   └─ 轮询超时 → 回「绑定超时，请重新发送 绑定」
3  用 stoken 兑换补齐凭证（若 Confirmed 未直接给全）：
   GET passport-api.mihoyo.com/account/auth/api/getCookieAccountInfoBySToken?stoken=...  → cookie_token
   GET passport-api.mihoyo.com/account/auth/api/getLTokenBySToken?stoken=...            → ltoken
   （Cookie: mid={mid};stoken={stoken}，DS 用简单式 x4 salt，见 §3.2）
4  组装 stuid/stoken/mid/ltuid/cookie_token → CredentialStore 加密落盘
```

status 字符串实测/文献确认为 `Created` / `Scanned` / `Confirmed`（web 与 app 变体一致）；hk4e-sdk 变体用 `Init/Scanned/Confirmed`，不要混用。

---

## 6. 已实测确认 / 仅文献未验证 清单

### 已实测确认（本机 httpx 真请求）

1. Mihomo `sr_info_parsed` 200 成功形状 + player/character 全字段 schema（uid=100895290）
2. Mihomo 400/404 错误形状（uid=1、abc、空、999999999）
3. Mihomo OpenAPI 端点族（`/openapi.json`）
4. 图标资源基址 `raw.githubusercontent.com/Mar-7th/StarRailRes/master` 可下载、无防盗链（第三方 Referer + 自定义 UA 200 image/png）
5. 本机到 raw.githubusercontent.com 连接不稳定（需重试逻辑）
6. passport **web 变体** createQRLogin（无需 DS）retcode=0 + queryQRLoginStatus 初始 `status="Created"`（含 data 完整字段）
7. passport **app 变体** createQRLogin（PROD salt + b/q DS + pass 头）retcode=0 → **PROD salt `JwYDpKvLj6MrMqqYU6jTKF17KNO2PXoS` 与 b/q 公式实测有效**
8. app 变体 queryQRLoginStatus 在本机被 -3503 风控（复现 2 次）
9. getTokenByGameToken 对无效 game_token 返回 -5300（两种 salt 同结果，无法区分）

### 仅文献未验证

1. game_record hkrpg 各端点实际响应体（需要真实 Cookie，W2 联调时补）
2. getTokenByGameToken 的 salt 分歧裁决（K2 `OvOIsZ...` vs PROD）与 -5300 的确切触发条件
3. Confirmed 后 Set-Cookie 的具体字段与 getCookieAccountInfoByGameToken 实际返回
4. -102/-110/1034/404(米游社侧) 等错误码文献值
5. 老端点 `api-takumi.miyoushe.com/auth/api/createQRLogin`（未找到在维护实现，已弃用，勿用）
6. OS（海外）salt `okr4obncj8bw5a65hbnn5oo6ixjc3l9w`

---

## 7. 给 W2 的落建议（按本次证据强度排序）

1. **扫码用 web 变体**（实测全通、无 DS、无风控）：`passport-api.miyoushe.com/account/ma-cn-passport/web/createQRLogin` + `/web/queryQRLoginStatus`。DEVELOPMENT.md §3.3 的端点行请按 §1.3 变体 A 更新。
2. **game_record DS**：salt `xV8v4Qu54lUKrEYFZkJhB8cuOh9Asafs`（3 源一致）+ b/q 式 + app_version 2.40.1/client_type 5，照抄 Miao-Yunzai 组合。
3. **图标缓存**：基址 StarRailRes（不是 hakush.in），下载器必须带重试（本机实测 1-3 次重试才成功）。
4. **Mihomo 错误归类**：400/404 且 `detail` 字段 → 统一 DATA_NOT_FOUND 文案；勿按 message 文本猜。
5. **风控预案**：保留 xiaoyao app 变体做备用（DS 已验通），device_fp 随机 13 位 hex；-3503/-5300 时回固定"稍后再试"文案。
6. fixtures 中的 `_src_*` / `_qr_probe_log.json` / `_gettoken_probe_log.json` 为调研证据快照，可随 W2 一起归档或删除；`mihomo_sr_info_parsed.json`、`mihomo_full_one_character.json`、`qr_create_response.json`、`qr_query_status_initial.json`、`qr_web_variant_probe.json` 为 W2 适配器/渲染测试的正式输入。
