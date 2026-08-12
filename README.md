# 中二节奏落雪查询插件

接入落雪咖啡屋 API，在 AstrBot 中实现常用的中二节奏查询功能。

## 配置

在 AstrBot 插件配置中填写：

- `lxns_token`：落雪开发者 API 密钥。玩家信息、B30、Recent、单曲成绩需要它。
- `api_base`：默认 `https://maimai.lxns.net/api/v0`。
- `asset_base`：默认 `https://assets2.lxns.net/chunithm`。

公开曲库、别名、随机谱面不需要 Token。

## 指令

```text
/chu help
/chu bind <好友码>
/chu unbind
/chu me

/chu b30 [好友码]
/chu recent [数量] [好友码]
/chu score <曲名或ID> [难度] [好友码]

/chu song <曲名/别名/ID>
/chu alias <曲名/ID>
/chu random [等级] [难度]
/chu jacket <曲名/ID>
/chu update
```

示例：

```text
/chu bind 888888888888888
/chu b30
/chu recent 20
/chu score 宛城、炎上！！ mas
/chu score 1234 ult 888888888888888
/chu song 玩具狂奏曲
/chu random 14+ mas
```

## 数据文件

插件会在 `data/plugin_data/astrbot_plugin_chunithm_lxns` 下保存：

- `bindings.json`：用户绑定的好友码。
- `catalog_cache.json`：落雪曲库与别名缓存。
