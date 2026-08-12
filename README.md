# 中二节奏落雪查询

基于落雪咖啡屋 LXNS API 的 AstrBot 中二节奏查询插件，提供玩家信息、Rating 构成、Recent、单曲成绩、曲库、别名、随机谱面和曲绘链接查询。

## 功能

- 绑定中二节奏好友码，后续查询可省略好友码。
- 查询玩家资料：昵称、好友码、Rating、等级、OVER POWER、游玩次数、称号、角色、名牌、头像和同步时间。
- 查询 Rating 构成：Best 30、Selection 10、New Best 20。
- 查询 Recent 记录，支持指定展示数量。
- 查询单曲成绩，支持曲名、别名、歌曲 ID 和难度筛选。
- 查询曲库详情：曲名、曲师、分类、BPM、版本、谱面等级、定数、物量、谱师等。
- 查询歌曲别名。
- 按等级和难度随机谱面。
- 生成落雪曲绘资源链接。
- 本地缓存曲库和别名，支持手动刷新。

## 安装

在 AstrBot 的插件目录执行：

```bash
cd /path/to/AstrBot/data/plugins
git clone https://github.com/LM-TUki/astrbot-plugin-chunithm-lxns.git astrbot_plugin_chunithm_lxns
```

重启 AstrBot，或在 AstrBot 管理面板中重载插件。

依赖写在 `requirements.txt` 中：

```text
aiohttp>=3.11.18
```

如果 AstrBot 没有自动安装依赖，请在 AstrBot 使用的 Python 环境中手动安装：

```bash
pip install -r data/plugins/astrbot_plugin_chunithm_lxns/requirements.txt
```

## 配置

在 AstrBot 插件配置中填写：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `lxns_token` | 空 | 落雪开发者 API 密钥。查询玩家信息、B30、Recent、单曲成绩时需要。 |
| `api_base` | `https://maimai.lxns.net/api/v0` | 落雪 API 基础地址，通常保持默认。 |
| `asset_base` | `https://assets2.lxns.net/chunithm` | 曲绘等资源链接基础地址。 |
| `default_version` | `23000` | 曲库接口使用的默认版本。 |
| `cache_seconds` | `86400` | 曲库和别名本地缓存时间，单位秒。 |
| `timeout_seconds` | `15` | API 请求超时时间，单位秒。 |
| `default_recent_count` | `10` | `/chu recent` 默认展示数量，范围 1-50。 |
| `b30_show_count` | `30` | Best 30 展示数量，范围 1-30。 |
| `selection_show_count` | `10` | Selection 展示数量，设为 0 可隐藏。 |
| `auto_resolve_qq` | `true` | 未手动绑定时，尝试用消息发送者 QQ 号查询落雪绑定。 |

公开曲库、别名、随机谱面不需要 Token。玩家资料、成绩、B30、Recent 需要 Token，并且落雪开发者申请应包含第三方查询成绩相关权限。

## 指令

| 指令 | 功能 |
| --- | --- |
| `/chu help` | 查看帮助菜单。 |
| `/chu bind <好友码>` | 绑定自己的中二节奏好友码。 |
| `/chu unbind` | 解除当前账号绑定。 |
| `/chu me` | 查看当前绑定玩家资料。 |
| `/chu me <好友码>` | 查看指定好友码玩家资料。 |
| `/chu me qq <QQ号>` | 通过落雪 QQ 绑定查询玩家资料。 |
| `/chu b30 [好友码]` | 查询 Rating 构成。未写好友码时使用绑定。 |
| `/chu recent [数量] [好友码]` | 查询 Recent，数量范围 1-50。 |
| `/chu score <曲名或ID> [难度] [好友码]` | 查询单曲成绩。未写难度时展示全难度缓存成绩。 |
| `/chu song <曲名/别名/ID>` | 查询曲库歌曲详情。 |
| `/chu alias <曲名/ID>` | 查询歌曲别名。 |
| `/chu random [等级] [难度]` | 随机一张符合条件的谱面。 |
| `/chu jacket <曲名/ID>` | 获取曲绘链接。 |
| `/chu update` | 强制刷新本地曲库和别名缓存。 |

`/chu <曲名>` 会自动按 `/chu song <曲名>` 处理。

## 难度写法

支持以下难度别名：

| 难度 | 可用写法 |
| --- | --- |
| BASIC | `0`、`bas`、`basic`、`绿` |
| ADVANCED | `1`、`adv`、`advanced`、`黄` |
| EXPERT | `2`、`exp`、`expert`、`红` |
| MASTER | `3`、`mas`、`master`、`紫` |
| ULTIMA | `4`、`ult`、`ultima`、`黑` |
| WORLD'S END | `5`、`we`、`world`、`宴` |

## 使用示例

```text
/chu bind 888888888888888
/chu me
/chu b30
/chu recent 20
/chu score 宛城、炎上！！ mas
/chu score 1234 ult 888888888888888
/chu song 玩具狂奏曲
/chu alias 1234
/chu random 14+ mas
/chu jacket 玩具狂奏曲
/chu update
```

## 查询说明

- 好友码可以在支持的查询命令末尾直接填写，例如 `/chu b30 888888888888888`。
- 不填写好友码时，插件优先使用 `/chu bind` 保存的绑定。
- 开启 `auto_resolve_qq` 且配置了 Token 时，未绑定用户会尝试通过落雪 QQ 绑定查询好友码。
- 曲名查询会匹配歌曲标题、别名和曲师。多个结果时请使用歌曲 ID 精确查询。
- 曲库和别名会缓存到本地，默认 24 小时过期；需要立即更新时使用 `/chu update`。

## 数据文件

插件会在 AstrBot 运行目录的 `data/plugin_data/astrbot_plugin_chunithm_lxns` 下保存：

- `bindings.json`：用户绑定的好友码。
- `catalog_cache.json`：落雪曲库和别名缓存。

## 常见问题

### 提示未配置落雪开发者 API 密钥

在插件配置里填写 `lxns_token`。公开曲库查询不需要 Token，但玩家和成绩相关查询需要。

### 提示未绑定好友码

先发送 `/chu bind <好友码>`，或在查询命令末尾直接写好友码。

### 单曲查询出现多个结果

使用 `/chu song <关键词>` 找到歌曲 ID 后，再用 ID 查询，例如 `/chu score 1234 mas`。

### 查询玩家成绩失败或返回无权限

检查落雪开发者 Token 是否填写正确，以及申请权限是否包含第三方查询成绩相关接口。

## 相关链接

- AstrBot: https://github.com/AstrBotDevs/AstrBot
- 落雪 LxBot: https://github.com/JoinChang/LxBot
