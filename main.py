from __future__ import annotations

import asyncio
import json
import random
import re
import time
import traceback
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from .asset_store import LocalAssetStore, PublicAssetSynchronizer
from .renderer import ChunithmBestRenderer, enrich_scores_with_catalog


PLUGIN_NAME = "astrbot_plugin_chunithm_lxns"
PLUGIN_VERSION = "0.3.0"
DATA_DIR = Path.cwd() / "data" / "plugin_data" / PLUGIN_NAME

LEVEL_NAMES = {
    0: "BASIC",
    1: "ADVANCED",
    2: "EXPERT",
    3: "MASTER",
    4: "ULTIMA",
    5: "WORLD'S END",
}

LEVEL_SHORT = {
    0: "BAS",
    1: "ADV",
    2: "EXP",
    3: "MAS",
    4: "ULT",
    5: "WE",
}

DIFFICULTY_ALIASES = {
    "0": 0,
    "bas": 0,
    "basic": 0,
    "绿": 0,
    "绿色": 0,
    "1": 1,
    "adv": 1,
    "advanced": 1,
    "黄": 1,
    "黄色": 1,
    "2": 2,
    "exp": 2,
    "expert": 2,
    "红": 2,
    "红色": 2,
    "3": 3,
    "mas": 3,
    "master": 3,
    "紫": 3,
    "紫色": 3,
    "4": 4,
    "ult": 4,
    "ultima": 4,
    "黑": 4,
    "黑色": 4,
    "5": 5,
    "we": 5,
    "world": 5,
    "worldsend": 5,
    "worldsend's": 5,
    "world'send": 5,
    "world's": 5,
    "worlds": 5,
    "宴": 5,
}

RANK_NAMES = {
    "sssp": "SSS+",
    "sss": "SSS",
    "ssp": "SS+",
    "ss": "SS",
    "sp": "S+",
    "s": "S",
    "aaa": "AAA",
    "aa": "AA",
    "a": "A",
    "bbb": "BBB",
    "bb": "BB",
    "b": "B",
    "c": "C",
    "d": "D",
}

CLEAR_NAMES = {
    "catastrophy": "CATASTROPHY",
    "absolutepp": "ABSOLUTE++",
    "absolutep": "ABSOLUTE+",
    "absolute": "ABSOLUTE",
    "brave": "BRAVE",
    "hard": "HARD",
    "clear": "CLEAR",
    "failed": "FAILED",
}

FULL_COMBO_NAMES = {
    "alljusticecritical": "AJC",
    "alljustice": "AJ",
    "fullcombo": "FC",
}

FULL_CHAIN_NAMES = {
    "fullchain": "铂链",
    "fullchain2": "金链",
}


class UserFacingError(Exception):
    """An error that can be shown directly to chat users."""


class LxnsApiError(UserFacingError):
    def __init__(self, message: str, status: int | None = None):
        self.status = status
        super().__init__(message)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on", "开启", "启用"}:
            return True
        if lowered in {"false", "0", "no", "off", "关闭", "禁用"}:
            return False
    return bool(value)


def _now() -> float:
    return time.time()


def _normalize_text(text: Any) -> str:
    return str(text or "").strip().casefold()


def _format_number(value: Any, digits: int | None = None) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits if digits is not None else 2}f}"
    if isinstance(value, int):
        return f"{value:,}"
    parsed = _safe_float(value)
    if parsed is not None and digits is not None:
        return f"{parsed:.{digits}f}"
    return str(value)


def _format_time(value: Any) -> str:
    if not value:
        return "-"
    text = str(value)
    return text.replace("T", " ").replace("Z", " UTC")


def _is_friend_code_token(token: str) -> bool:
    token = token.strip()
    return bool(re.fullmatch(r"\d{10,20}", token))


def _normalize_friend_code(raw: str) -> str:
    raw = raw.strip()
    if not re.fullmatch(r"\d{6,20}", raw):
        raise UserFacingError("好友码格式不正确，应为纯数字。")
    return raw


def _split_first(rest: str) -> tuple[str, str]:
    rest = rest.strip()
    if not rest:
        return "", ""
    parts = rest.split(maxsplit=1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1].strip()


def _parse_difficulty_token(token: str) -> int | None:
    cleaned = token.strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    return DIFFICULTY_ALIASES.get(cleaned)


@register(PLUGIN_NAME, "Codex", "接入落雪 API 的中二节奏查询插件", PLUGIN_VERSION, "")
class ChunithmLxnsPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context, config)
        self.config = config or {}
        self.api_base = str(
            self.config.get("api_base", "https://maimai.lxns.net/api/v0"),
        ).rstrip("/")
        self.asset_base = str(
            self.config.get("asset_base", "https://assets2.lxns.net/chunithm"),
        ).rstrip("/")
        self.token = str(self.config.get("lxns_token", "") or "").strip()
        self.default_version = _safe_int(self.config.get("default_version"), 23000)
        self.cache_seconds = max(
            _safe_int(self.config.get("cache_seconds"), 24 * 60 * 60),
            60,
        )
        self.timeout_seconds = max(_safe_int(self.config.get("timeout_seconds"), 15), 3)
        self.default_recent_count = max(
            min(_safe_int(self.config.get("default_recent_count"), 10), 50),
            1,
        )
        self.b30_show_count = max(
            min(_safe_int(self.config.get("b30_show_count"), 30), 30),
            1,
        )
        self.selection_show_count = max(
            min(_safe_int(self.config.get("selection_show_count"), 10), 10),
            0,
        )
        self.auto_resolve_qq = _safe_bool(self.config.get("auto_resolve_qq"), True)
        self.render_b30_image = _safe_bool(self.config.get("render_b30_image"), True)
        self.show_friend_code = _safe_bool(self.config.get("show_friend_code"), False)
        self.show_play_count = _safe_bool(self.config.get("show_play_count"), False)
        self.footer_bot_name = str(self.config.get("footer_bot_name", "EmuBot") or "EmuBot").strip()
        self.asset_sync_concurrency = max(
            min(_safe_int(self.config.get("asset_sync_concurrency"), 1), 4),
            1,
        )
        self.asset_sync_delay = max(_safe_float(self.config.get("asset_sync_delay")) or 0.5, 0.05)

        self.bindings_file = DATA_DIR / "bindings.json"
        self.catalog_file = DATA_DIR / "catalog_cache.json"
        self.asset_cache_dir = DATA_DIR / "assets"
        self.generated_dir = DATA_DIR / "generated"
        self.static_dir = Path(__file__).resolve().parent / "static"
        self.bindings: dict[str, str] = {}
        self.catalog: dict[str, Any] | None = None
        self.catalog_lock = asyncio.Lock()
        self.render_semaphore = asyncio.Semaphore(2)
        self.session: aiohttp.ClientSession | None = None
        self.asset_update_task: asyncio.Task[None] | None = None
        self.asset_update_state: dict[str, Any] = {"status": "idle"}
        self.asset_store = LocalAssetStore(self.asset_cache_dir)
        self.renderer = ChunithmBestRenderer(self.static_dir)

        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.asset_cache_dir.mkdir(parents=True, exist_ok=True)
        self.generated_dir.mkdir(parents=True, exist_ok=True)
        self._load_bindings()
        self._load_catalog_from_disk()
        self._cleanup_generated_images()

    async def initialize(self):
        logger.info("中二节奏落雪查询插件已加载")

    async def terminate(self):
        if self.asset_update_task and not self.asset_update_task.done():
            self.asset_update_task.cancel()
            await asyncio.gather(self.asset_update_task, return_exceptions=True)
        self.asset_update_task = None
        if self.session and not self.session.closed:
            await self.session.close()
        self.session = None

    @filter.regex(r"^/?chu(?:\s|$)")
    async def handle_chu(self, event: AstrMessageEvent):
        try:
            result = await self._dispatch(event, event.get_message_str())
        except UserFacingError as exc:
            result = f"中二节奏查询失败：{exc}"
        except Exception as exc:
            logger.error(f"中二节奏插件内部错误：{exc}")
            logger.error(traceback.format_exc())
            result = "中二节奏查询失败：插件内部错误，详情请查看 AstrBot 日志。"

        if isinstance(result, Path):
            yield event.image_result(str(result)).stop_event()
        elif result:
            yield event.plain_result(result).stop_event()

    async def _dispatch(self, event: AstrMessageEvent, message: str) -> str | Path:
        rest = self._strip_prefix(message)
        cmd, args = _split_first(rest)
        cmd_key = cmd.strip().lower()

        if not cmd_key or cmd_key in {"help", "帮助", "h", "菜单"}:
            return self._help_text()
        if cmd_key in {"bind", "绑定"}:
            return await self._cmd_bind(event, args)
        if cmd_key in {"unbind", "解绑"}:
            return self._cmd_unbind(event)
        if cmd_key in {"whoami", "me", "我的", "info", "player", "玩家"}:
            return await self._cmd_player(event, args)
        if cmd_key in {"b30", "best30", "bests", "best"} and not args:
            return await self._cmd_b30(event, args)
        if cmd_key in {"b30", "best30", "bests"}:
            return await self._cmd_b30(event, args)
        if cmd_key in {"recent", "recents", "r10", "r", "最近"}:
            return await self._cmd_recent(event, args)
        if cmd_key in {"score", "scores", "成绩", "单曲"}:
            return await self._cmd_score(event, args)
        if cmd_key in {"best", "单曲最佳"}:
            return await self._cmd_score(event, args)
        if cmd_key in {"song", "search", "查歌", "歌曲", "曲目"}:
            return await self._cmd_song(args)
        if cmd_key in {"alias", "别名"}:
            return await self._cmd_alias(args)
        if cmd_key in {"random", "rand", "随机", "随歌"}:
            return await self._cmd_random(args)
        if cmd_key in {"jacket", "cover", "曲绘"}:
            return await self._cmd_jacket(args)
        if cmd_key in {"update", "更新", "刷新"}:
            return await self._cmd_update_cache()
        if cmd_key in {"assets", "asset", "素材", "资源"}:
            return await self._cmd_assets(event, args)

        # Convenience: `/chu <曲名>` behaves like `/chu song <曲名>`.
        return await self._cmd_song(rest)

    def _strip_prefix(self, message: str) -> str:
        match = re.match(r"^/?chu(?:\s+|$)(.*)$", message.strip(), flags=re.I | re.S)
        return match.group(1).strip() if match else message.strip()

    def _help_text(self) -> str:
        return (
            "中二节奏查询 /chu 帮助\n"
            "\n"
            "账号：\n"
            "/chu bind <好友码> 绑定好友码\n"
            "/chu unbind 解绑\n"
            "/chu me 查看当前绑定玩家\n"
            "\n"
            "成绩：\n"
            "/chu b30 [好友码] 查询 Rating 构成\n"
            "/chu recent [数量] [好友码] 查询 Recent\n"
            "/chu score <曲名或ID> [难度] [好友码] 查询单曲成绩\n"
            "\n"
            "曲库：\n"
            "/chu song <曲名/别名/ID> 查歌\n"
            "/chu alias <曲名/ID> 查别名\n"
            "/chu random [等级] [难度] 随机谱面\n"
            "/chu jacket <曲名/ID> 获取本地曲绘\n"
            "/chu update 刷新本地曲库缓存\n"
            "/chu assets status 查看本地素材库\n"
            "/chu assets update [all/jackets/characters] 后台更新公共素材（管理员）\n"
            "\n"
            "说明：B30 只读取本地素材；玩家成绩接口需要配置落雪开发者 API 密钥。"
        )

    async def _cmd_bind(self, event: AstrMessageEvent, args: str) -> str:
        if not args.strip():
            return (
                "请发送 /chu bind <好友码> 绑定。\n"
                "OAuth 授权绑定需要额外的回调服务，本插件当前只支持手动好友码绑定。"
            )
        code = _normalize_friend_code(args.split()[0])
        player_name = ""
        if self.token:
            try:
                player = await self._api_player(code)
                player_name = str(player.get("name") or "")
            except UserFacingError as exc:
                raise UserFacingError(f"绑定前验证好友码失败：{exc}") from exc

        self.bindings[self._binding_key(event)] = code
        self._save_bindings()

        suffix = f"（{player_name}）" if player_name else ""
        if self.show_friend_code:
            return f"已绑定中二节奏好友码：{code}{suffix}"
        return f"已绑定中二节奏账号{suffix}。"

    def _cmd_unbind(self, event: AstrMessageEvent) -> str:
        key = self._binding_key(event)
        if key not in self.bindings:
            return "当前账号没有绑定中二节奏好友码。"
        old_code = self.bindings.pop(key)
        self._save_bindings()
        if self.show_friend_code:
            return f"已解绑中二节奏好友码：{old_code}"
        return "已解绑中二节奏账号。"

    async def _cmd_player(self, event: AstrMessageEvent, args: str) -> str:
        code = None
        qq = None
        first, rest = _split_first(args)
        if first.lower() == "qq" and rest:
            qq = rest.split()[0]
        elif first:
            code = _normalize_friend_code(first)

        if qq:
            player = await self._api_player_by_qq(qq)
        else:
            code = await self._resolve_friend_code(event, code)
            player = await self._api_player(code)

        return self._format_player(player)

    async def _cmd_b30(self, event: AstrMessageEvent, args: str) -> str | Path:
        explicit_code, rest = self._pop_friend_code(args)
        if rest:
            raise UserFacingError("B30 只接受好友码参数。用法：/chu b30 [好友码]")
        code = await self._resolve_friend_code(event, explicit_code)

        player_task = asyncio.create_task(self._api_player(code))
        bests_task = asyncio.create_task(self._api_rating_bests(code))
        catalog_task = asyncio.create_task(self._get_catalog()) if self.render_b30_image else None
        try:
            bests = await bests_task
        except Exception:
            pending_tasks = [player_task]
            if catalog_task is not None:
                pending_tasks.append(catalog_task)
            for task in pending_tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pending_tasks, return_exceptions=True)
            raise
        try:
            player = await player_task
        except UserFacingError:
            player = {"friend_code": code}
        except Exception:
            if catalog_task is not None and not catalog_task.done():
                catalog_task.cancel()
                await asyncio.gather(catalog_task, return_exceptions=True)
            raise

        if self.render_b30_image:
            try:
                assert catalog_task is not None
                catalog = await catalog_task
                return await self._render_b30(player, bests, catalog)
            except Exception as exc:
                logger.error(f"B30 图片生成失败，已回退文本：{exc}")
                logger.error(traceback.format_exc())

        return self._format_b30_text(player, bests, code)

    def _format_b30_text(self, player: dict[str, Any], bests: dict[str, Any], code: str) -> str:

        title = self._player_title(player, code, include_friend_code=self.show_friend_code)
        lines = [f"{title} Rating 构成"]
        if player:
            summary = self._player_summary_line(player)
            if summary:
                lines.append(summary)

        lines.extend(
            self._format_score_section(
                "Best 30",
                bests.get("bests", []),
                self.b30_show_count,
            ),
        )
        if self.selection_show_count:
            lines.extend(
                self._format_score_section(
                    "Selection 10",
                    bests.get("selections", []),
                    self.selection_show_count,
                ),
            )
        lines.extend(
            self._format_score_section(
                "New Best 20",
                bests.get("new_bests", []),
                min(self.b30_show_count, 20),
            ),
        )
        if len(lines) <= 2:
            lines.append("落雪没有返回 Rating 构成数据。")
        return "\n".join(lines)

    async def _cmd_recent(self, event: AstrMessageEvent, args: str) -> str:
        count, rest = self._pop_count(args, self.default_recent_count)
        explicit_code, rest = self._pop_friend_code(rest)
        if rest:
            raise UserFacingError("Recent 只接受数量和好友码。用法：/chu recent [数量] [好友码]")
        count = max(1, min(count, 50))
        code = await self._resolve_friend_code(event, explicit_code)

        recents = await self._api_recents(code)
        player_name = ""
        try:
            player = await self._api_player(code)
            player_name = self._player_title(player, code, include_friend_code=self.show_friend_code)
        except UserFacingError:
            player_name = f"好友码 {code}" if self.show_friend_code else "未知玩家"

        lines = [f"{player_name} Recent {count}"]
        for idx, score in enumerate(recents[:count], start=1):
            lines.append(self._format_score_line(score, idx=idx, include_time=True))
        if len(lines) == 1:
            lines.append("暂无 Recent 数据。")
        return "\n".join(lines)

    async def _cmd_score(self, event: AstrMessageEvent, args: str) -> str:
        query, level_index, explicit_code = self._parse_score_args(args)
        if not query:
            return "用法：/chu score <曲名或ID> [难度] [好友码]"

        code = await self._resolve_friend_code(event, explicit_code)
        song = await self._resolve_one_song(query)
        params = self._song_query_params(song, query)

        if level_index is not None:
            score = await self._api_best_score(code, {**params, "level_index": level_index})
            lines = [
                f"{self._song_display_name(song, query)} 单曲最佳",
                self._format_score_line(score),
            ]
            return "\n".join(lines)

        scores = await self._api_song_scores(code, params)
        if isinstance(scores, dict):
            scores = [scores]
        lines = [f"{self._song_display_name(song, query)} 全难度成绩"]
        for idx, score in enumerate(scores or [], start=1):
            lines.append(self._format_score_line(score, idx=idx))
        if len(lines) == 1:
            lines.append("没有查到这首歌的缓存成绩。")
        return "\n".join(lines)

    async def _cmd_song(self, args: str) -> str:
        query = args.strip()
        if not query:
            return "用法：/chu song <曲名/别名/ID>"
        songs = await self._search_songs(query, limit=8)
        if not songs:
            return f"没有找到曲目：{query}"
        if len(songs) == 1:
            aliases = await self._aliases_for_song(songs[0].get("id"))
            return self._format_song_detail(songs[0], aliases)

        lines = [f"找到 {len(songs)} 个可能的曲目："]
        for song in songs:
            lines.append(self._format_song_brief(song))
        lines.append("请使用 /chu song <ID> 查看详情。")
        return "\n".join(lines)

    async def _cmd_alias(self, args: str) -> str:
        query = args.strip()
        if not query:
            return "用法：/chu alias <曲名/ID>"
        song = await self._resolve_one_song(query)
        aliases = await self._aliases_for_song(song.get("id"))
        lines = [f"{song.get('id')} - {song.get('title')} 的别名"]
        if aliases:
            lines.extend(f"- {alias}" for alias in aliases[:40])
            if len(aliases) > 40:
                lines.append(f"... 还有 {len(aliases) - 40} 个")
        else:
            lines.append("暂无别名。")
        return "\n".join(lines)

    async def _cmd_random(self, args: str) -> str:
        level_filter = None
        difficulty_filter = None
        for token in args.split():
            parsed_diff = _parse_difficulty_token(token)
            if parsed_diff is not None:
                difficulty_filter = parsed_diff
            else:
                level_filter = token

        catalog = await self._get_catalog()
        candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for song in catalog.get("songs", []):
            for diff in song.get("difficulties") or []:
                if difficulty_filter is not None and diff.get("difficulty") != difficulty_filter:
                    continue
                if level_filter and not self._difficulty_matches_level(diff, level_filter):
                    continue
                candidates.append((song, diff))

        if not candidates:
            return "没有找到符合条件的随机谱面。示例：/chu random 14+ mas"

        song, diff = random.choice(candidates)
        lines = ["随机中二节奏谱面"]
        lines.append(self._format_song_brief(song))
        lines.append(self._format_difficulty_detail(diff))
        return "\n".join(lines)

    async def _cmd_jacket(self, args: str) -> str | Path:
        query = args.strip()
        if not query:
            return "用法：/chu jacket <曲名/ID>"
        song = await self._resolve_one_song(query)
        song_id = song.get("id")
        local_path = self.asset_store.find("jacket", song_id)
        if local_path:
            return local_path
        return (
            f"{song.get('id')} - {song.get('title')}\n"
            "本地素材库中没有该曲绘。请联系管理员执行 /chu assets update jackets。"
        )

    async def _cmd_update_cache(self) -> str:
        catalog = await self._get_catalog(force=True)
        return (
            "已刷新中二节奏曲库缓存："
            f"{len(catalog.get('songs', []))} 首曲目，"
            f"{len(catalog.get('aliases', []))} 条别名记录。"
        )

    async def _cmd_assets(self, event: AstrMessageEvent, args: str) -> str:
        action, target = _split_first(args)
        action = action.lower() or "status"
        if action in {"status", "状态", "info"}:
            return self._format_asset_status()
        if action not in {"update", "sync", "更新", "同步"}:
            return "用法：/chu assets status 或 /chu assets update [all/jackets/characters]"
        if not event.is_admin():
            raise UserFacingError("只有 AstrBot 管理员可以更新公共素材库。")
        if self.asset_update_task and not self.asset_update_task.done():
            return "公共素材库正在后台更新。\n" + self._format_asset_status()

        target = target.strip().lower() or "all"
        targets = {
            "all": ("jacket", "character"),
            "全部": ("jacket", "character"),
            "jackets": ("jacket",),
            "jacket": ("jacket",),
            "曲绘": ("jacket",),
            "characters": ("character",),
            "character": ("character",),
            "角色": ("character",),
        }
        kinds = targets.get(target)
        if kinds is None:
            return "素材类型只支持 all、jackets 或 characters。"

        self.asset_update_state = {
            "status": "queued",
            "kinds": list(kinds),
            "total": 0,
            "completed": 0,
            "downloaded": 0,
            "skipped": 0,
            "failed": 0,
        }
        self.asset_update_task = asyncio.create_task(self._run_asset_update(kinds))
        return (
            "已在后台启动公共素材更新。B30 查询仍只读取当前本地素材，不会触发网络下载。\n"
            "使用 /chu assets status 查看进度。"
        )

    async def _run_asset_update(self, kinds: tuple[str, ...]) -> None:
        synchronizer = PublicAssetSynchronizer(
            self.asset_store,
            api_base=self.api_base,
            asset_base=self.asset_base,
            version=self.default_version,
            timeout_seconds=max(self.timeout_seconds, 30),
            concurrency=self.asset_sync_concurrency,
            delay_seconds=self.asset_sync_delay,
        )

        def update_state(state: dict[str, Any]) -> None:
            self.asset_update_state = state

        try:
            await synchronizer.sync(kinds, update_state)
        except asyncio.CancelledError:
            self.asset_update_state = {**self.asset_update_state, "status": "cancelled"}
            raise
        except Exception as exc:
            logger.error(f"公共素材库更新失败：{exc}")
            logger.error(traceback.format_exc())
            self.asset_update_state = {
                **self.asset_update_state,
                "status": "failed",
                "error": str(exc),
            }

    def _format_asset_status(self) -> str:
        state = self.asset_update_state
        if state.get("status") == "idle":
            manifest = self.asset_store.load_manifest()
            if manifest:
                state = manifest
        counts = self.asset_store.counts()
        labels = {
            "idle": "空闲",
            "queued": "等待开始",
            "discovering": "读取公共素材清单",
            "downloading": "下载中",
            "complete": "已完成",
            "failed": "失败",
            "cancelled": "已取消",
        }
        status = labels.get(str(state.get("status")), str(state.get("status") or "空闲"))
        lines = [
            "中二节奏本地素材库",
            f"状态：{status}",
            f"曲绘：{counts['jacket']} / 角色：{counts['character']}",
        ]
        total = _safe_int(state.get("total"), 0)
        completed = _safe_int(state.get("completed"), 0)
        if total:
            lines.append(
                f"进度：{completed}/{total}，新增 {state.get('downloaded', 0)}，"
                f"已有 {state.get('skipped', 0)}，失败 {state.get('failed', 0)}"
            )
        if state.get("completed_at"):
            lines.append(f"最近完成：{_format_time(state.get('completed_at'))}")
        if state.get("error"):
            lines.append(f"错误：{state.get('error')}")
        lines.append("日常 B30 仅读取这些本地文件，不会请求素材站。")
        return "\n".join(lines)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=self.timeout_seconds, connect=8)
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                headers={"User-Agent": f"{PLUGIN_NAME}/{PLUGIN_VERSION} AstrBot"},
            )
        return self.session

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> Any:
        if auth and not self.token:
            raise UserFacingError(
                "未配置落雪开发者 API 密钥。请在插件配置 lxns_token 中填写 Token。",
            )

        headers = {}
        if auth:
            headers["Authorization"] = self.token

        session = await self._get_session()
        url = f"{self.api_base}/{path.lstrip('/')}"

        try:
            async with session.request(method, url, params=params, headers=headers) as resp:
                text = await resp.text()
                try:
                    payload = json.loads(text) if text else {}
                except json.JSONDecodeError as exc:
                    raise LxnsApiError(f"落雪 API 返回了非 JSON 响应（HTTP {resp.status}）", resp.status) from exc

                if isinstance(payload, dict) and "success" in payload:
                    if not payload.get("success") or resp.status >= 400:
                        message = payload.get("message") or f"HTTP {resp.status}"
                        raise LxnsApiError(str(message), resp.status)
                    return payload.get("data")

                if resp.status >= 400:
                    raise LxnsApiError(f"HTTP {resp.status}", resp.status)
                return payload
        except aiohttp.ClientError as exc:
            raise UserFacingError(f"无法连接落雪 API：{exc}") from exc
        except asyncio.TimeoutError as exc:
            raise UserFacingError("连接落雪 API 超时，请稍后再试。") from exc

    async def _api_player(self, friend_code: str) -> dict[str, Any]:
        return await self._request("GET", f"chunithm/player/{friend_code}")

    async def _api_player_by_qq(self, qq: str) -> dict[str, Any]:
        qq = qq.strip()
        if not re.fullmatch(r"\d{5,20}", qq):
            raise UserFacingError("QQ 号格式不正确。")
        return await self._request("GET", f"chunithm/player/qq/{qq}")

    async def _api_rating_bests(self, friend_code: str) -> dict[str, Any]:
        data = await self._request("GET", f"chunithm/player/{friend_code}/bests")
        return data or {}

    async def _api_song_scores(self, friend_code: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        data = await self._request("GET", f"chunithm/player/{friend_code}/bests", params=params)
        return data or []

    async def _api_best_score(self, friend_code: str, params: dict[str, Any]) -> dict[str, Any]:
        return await self._request("GET", f"chunithm/player/{friend_code}/best", params=params)

    async def _api_recents(self, friend_code: str) -> list[dict[str, Any]]:
        data = await self._request("GET", f"chunithm/player/{friend_code}/recents")
        return data or []

    async def _render_b30(
        self,
        player: dict[str, Any],
        bests: dict[str, Any],
        catalog: dict[str, Any],
    ) -> Path:
        section_specs = [
            ("BEST 30", list(bests.get("bests") or [])[: self.b30_show_count]),
            ("SELECTION 10", list(bests.get("selections") or [])[: self.selection_show_count]),
            ("NEW 20", list(bests.get("new_bests") or [])[:20]),
        ]
        if not any(rows for _, rows in section_specs):
            raise UserFacingError("落雪没有返回 Rating 构成数据。")

        songs_by_id = {
            _safe_int(song.get("id"), -1): song
            for song in catalog.get("songs") or []
            if song.get("id") is not None
        }
        song_ids = {
            _safe_int(score.get("id"), -1)
            for _, rows in section_specs
            for score in rows
            if score.get("id") is not None
        }
        jacket_paths = self._local_jackets(song_ids)
        player_assets = self._local_player_assets(player)
        missing_jackets = len(song_ids) - len(jacket_paths)
        if missing_jackets:
            logger.warning(
                f"B30 本地素材库缺少 {missing_jackets}/{len(song_ids)} 张曲绘；"
                "请由管理员执行 /chu assets update jackets。"
            )
        character = player.get("character") or {}
        if character.get("id") is not None and player_assets.get("character") is None:
            logger.warning(
                f"B30 本地素材库缺少角色 {character.get('id')}；"
                "请由管理员执行 /chu assets update characters。"
            )

        sections = [
            (
                title,
                enrich_scores_with_catalog(rows, songs_by_id, jacket_paths),
            )
            for title, rows in section_specs
            if rows
        ]
        self._validate_rating_sections(sections)

        output_path = self.generated_dir / f"b30-{int(time.time())}-{uuid4().hex[:8]}.jpg"
        async with self.render_semaphore:
            await asyncio.to_thread(
                self.renderer.render,
                player,
                sections,
                output_path,
                asset_paths=player_assets,
                show_friend_code=self.show_friend_code,
                show_play_count=self.show_play_count,
                footer_bot_name=self.footer_bot_name,
            )
        self._cleanup_generated_images()
        return output_path

    @staticmethod
    def _validate_rating_sections(sections: list[tuple[str, list[dict[str, Any]]]]) -> None:
        seen: dict[tuple[int, int], str] = {}
        for title, rows in sections:
            for score in rows:
                key = (
                    _safe_int(score.get("id"), -1),
                    _safe_int(score.get("level_index"), -1),
                )
                if key[0] < 0 or key[1] < 0:
                    raise ValueError(f"{title} 包含无效成绩记录：{score}")
                if key in seen:
                    raise ValueError(f"Rating 分组重复谱面：{key}（{seen[key]} / {title}）")
                seen[key] = title

    def _local_jackets(self, song_ids: set[int]) -> dict[int, Path]:
        return self.asset_store.find_many("jacket", sorted(song_id for song_id in song_ids if song_id >= 0))

    def _local_player_assets(self, player: dict[str, Any]) -> dict[str, Path | None]:
        requests: dict[str, tuple[str, Any] | None] = {
            "character": self._collection_request(player.get("character"), "character"),
            "plate": self._collection_request(player.get("name_plate"), "plate"),
            "icon": self._collection_request(player.get("map_icon"), "icon"),
            "trophy": self._collection_request(player.get("trophy"), "trophy")
            if str((player.get("trophy") or {}).get("color") or "").lower() == "image"
            else None,
        }
        return {
            name: self.asset_store.find(*request) if request else None
            for name, request in requests.items()
        }

    @staticmethod
    def _collection_request(collection: Any, kind: str) -> tuple[str, Any] | None:
        if not isinstance(collection, dict) or collection.get("id") is None:
            return None
        return kind, collection.get("id")

    def _cleanup_generated_images(self, max_age_seconds: int = 24 * 60 * 60) -> None:
        if not self.generated_dir.exists():
            return
        cutoff = _now() - max_age_seconds
        for path in self.generated_dir.glob("b30-*.jpg"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass

    async def _get_catalog(self, force: bool = False) -> dict[str, Any]:
        async with self.catalog_lock:
            if not force and self.catalog and not self._catalog_expired(self.catalog):
                return self.catalog

            disk_catalog = self._load_catalog_from_disk()
            if not force and disk_catalog and not self._catalog_expired(disk_catalog):
                self.catalog = disk_catalog
                return disk_catalog

            try:
                songs_data, alias_data = await asyncio.gather(
                    self._request(
                        "GET",
                        "chunithm/song/list",
                        params={"version": self.default_version, "notes": "true"},
                        auth=False,
                    ),
                    self._request("GET", "chunithm/alias/list", auth=False),
                )
                catalog = {
                    "fetched_at": _now(),
                    "songs": (songs_data or {}).get("songs", []),
                    "genres": (songs_data or {}).get("genres", []),
                    "versions": (songs_data or {}).get("versions", []),
                    "aliases": (alias_data or {}).get("aliases", []),
                }
                self.catalog = catalog
                self._save_json(self.catalog_file, catalog)
                return catalog
            except UserFacingError:
                if self.catalog:
                    return self.catalog
                if disk_catalog:
                    self.catalog = disk_catalog
                    return disk_catalog
                raise

    def _catalog_expired(self, catalog: dict[str, Any]) -> bool:
        fetched_at = _safe_float(catalog.get("fetched_at")) or 0
        return _now() - fetched_at > self.cache_seconds

    async def _search_songs(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        catalog = await self._get_catalog()
        songs = catalog.get("songs", [])
        query = query.strip()

        song_id = self._parse_song_id(query)
        if song_id is not None:
            exact = [song for song in songs if song.get("id") == song_id]
            return exact[:limit]

        normalized = _normalize_text(query)
        alias_matches: dict[int, tuple[int, str]] = {}
        for alias_record in catalog.get("aliases", []):
            sid = alias_record.get("song_id")
            aliases = alias_record.get("aliases") or []
            for alias in aliases:
                normalized_alias = _normalize_text(alias)
                if normalized_alias == normalized:
                    alias_matches[sid] = (0, str(alias))
                    break
                if normalized in normalized_alias and sid not in alias_matches:
                    alias_matches[sid] = (2, str(alias))

        ranked: list[tuple[int, dict[str, Any]]] = []
        for song in songs:
            title = _normalize_text(song.get("title"))
            artist = _normalize_text(song.get("artist"))
            sid = song.get("id")
            score = None
            if title == normalized:
                score = 0
            elif sid in alias_matches:
                score = alias_matches[sid][0]
            elif normalized in title:
                score = 1
            elif normalized in artist:
                score = 3
            if score is not None:
                ranked.append((score, song))

        ranked.sort(key=lambda item: (item[0], len(str(item[1].get("title") or "")), item[1].get("id") or 0))
        return [song for _, song in ranked[:limit]]

    async def _resolve_one_song(self, query: str) -> dict[str, Any]:
        songs = await self._search_songs(query, limit=6)
        if not songs:
            raise UserFacingError(f"没有找到曲目：{query}")
        if len(songs) > 1:
            lines = [f"曲名不唯一，请使用曲目 ID：{query}"]
            for song in songs:
                lines.append(self._format_song_brief(song))
            raise UserFacingError("\n".join(lines))
        return songs[0]

    async def _aliases_for_song(self, song_id: Any) -> list[str]:
        catalog = await self._get_catalog()
        for alias_record in catalog.get("aliases", []):
            if alias_record.get("song_id") == song_id:
                return [str(alias) for alias in alias_record.get("aliases") or []]
        return []

    def _parse_song_id(self, query: str) -> int | None:
        query = query.strip()
        match = re.fullmatch(r"(?:id|#)?\s*(\d{1,8})", query, flags=re.I)
        if not match:
            return None
        return int(match.group(1))

    def _song_query_params(self, song: dict[str, Any] | None, fallback_query: str) -> dict[str, Any]:
        if song and song.get("id") is not None:
            return {"song_id": song.get("id")}
        return {"song_name": fallback_query}

    def _song_display_name(self, song: dict[str, Any] | None, fallback_query: str) -> str:
        if song:
            return f"{song.get('id')} - {song.get('title')}"
        return fallback_query

    def _parse_score_args(self, args: str) -> tuple[str, int | None, str | None]:
        explicit_code, args = self._pop_friend_code(args)
        tokens = args.split()
        level_index = None
        if tokens:
            maybe_diff = _parse_difficulty_token(tokens[-1])
            if maybe_diff is not None:
                level_index = maybe_diff
                tokens = tokens[:-1]
        return " ".join(tokens).strip(), level_index, explicit_code

    def _pop_friend_code(self, args: str) -> tuple[str | None, str]:
        tokens = args.split()
        for idx in range(len(tokens) - 1, -1, -1):
            if _is_friend_code_token(tokens[idx]):
                code = tokens[idx]
                rest = " ".join(tokens[:idx] + tokens[idx + 1 :])
                return code, rest.strip()
        return None, args.strip()

    def _pop_count(self, args: str, default: int) -> tuple[int, str]:
        tokens = args.split()
        for idx, token in enumerate(tokens):
            if token.isdigit() and len(token) <= 2:
                count = int(token)
                rest = " ".join(tokens[:idx] + tokens[idx + 1 :])
                return count, rest.strip()
        return default, args.strip()

    async def _resolve_friend_code(self, event: AstrMessageEvent, explicit_code: str | None = None) -> str:
        if explicit_code:
            return _normalize_friend_code(explicit_code)

        key = self._binding_key(event)
        if key in self.bindings:
            return self.bindings[key]

        sender_id = str(event.get_sender_id() or "")
        if self.auto_resolve_qq and sender_id.isdigit() and self.token:
            try:
                player = await self._api_player_by_qq(sender_id)
                code = str(player.get("friend_code") or "")
                if code:
                    return code
            except UserFacingError:
                pass

        raise UserFacingError("未绑定好友码。请先发送 /chu bind <好友码>，或在命令末尾直接写好友码。")

    def _binding_key(self, event: AstrMessageEvent) -> str:
        platform = event.get_platform_id() or event.get_platform_name() or "default"
        return f"{platform}:{event.get_sender_id()}"

    def _load_bindings(self):
        self.bindings = self._load_json(self.bindings_file, {})
        if not isinstance(self.bindings, dict):
            self.bindings = {}

    def _save_bindings(self):
        self._save_json(self.bindings_file, self.bindings)

    def _load_catalog_from_disk(self) -> dict[str, Any] | None:
        catalog = self._load_json(self.catalog_file, None)
        if isinstance(catalog, dict):
            self.catalog = catalog
            return catalog
        return None

    def _load_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception as exc:
            logger.warning(f"读取 {path} 失败：{exc}")
            return default

    def _save_json(self, path: Path, data: Any):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
        tmp_path.replace(path)

    def _format_player(self, player: dict[str, Any]) -> str:
        lines = [
            self._player_title(
                player,
                str(player.get("friend_code") or "-"),
                include_friend_code=self.show_friend_code,
            ),
        ]
        summary = self._player_summary_line(player)
        if summary:
            lines.append(summary)

        trophy = player.get("trophy") or {}
        character = player.get("character") or {}
        plate = player.get("name_plate") or {}
        icon = player.get("map_icon") or {}
        extras = []
        if trophy.get("name"):
            extras.append(f"称号：{trophy.get('name')}")
        if character.get("name"):
            level = character.get("level")
            level_suffix = f" Lv.{level}" if level is not None else ""
            extras.append(f"角色：{character.get('name')}{level_suffix}")
        if plate.get("name"):
            extras.append(f"名牌：{plate.get('name')}")
        if icon.get("name"):
            extras.append(f"头像：{icon.get('name')}")
        lines.extend(extras)
        if player.get("upload_time"):
            lines.append(f"同步时间：{_format_time(player.get('upload_time'))}")
        return "\n".join(lines)

    def _player_title(
        self,
        player: dict[str, Any] | None,
        fallback_code: str,
        *,
        include_friend_code: bool = True,
    ) -> str:
        player = player or {}
        name = player.get("name") or "未知玩家"
        if not include_friend_code:
            return str(name)
        code = player.get("friend_code") or fallback_code
        return f"{name}（{code}）"

    def _player_summary_line(self, player: dict[str, Any]) -> str:
        parts = []
        if player.get("rating") is not None:
            parts.append(f"Rating {_format_number(player.get('rating'), 2)}")
        if player.get("level") is not None:
            parts.append(f"Lv.{player.get('level')}")
        if player.get("over_power") is not None:
            parts.append(f"OVER POWER {_format_number(player.get('over_power'), 2)}")
        if self.show_play_count and player.get("total_play_count") is not None:
            parts.append(f"游玩 {_format_number(player.get('total_play_count'))}")
        return " / ".join(parts)

    def _format_score_section(self, title: str, scores: list[dict[str, Any]], limit: int) -> list[str]:
        if not scores:
            return []
        ratings = [_safe_float(score.get("rating")) for score in scores]
        ratings = [rating for rating in ratings if rating is not None]
        average = sum(ratings) / len(ratings) if ratings else None
        header = f"\n{title}（{len(scores)} 首"
        if average is not None:
            header += f"，平均 {average:.2f}"
        header += "）"
        lines = [header]
        for idx, score in enumerate(scores[:limit], start=1):
            lines.append(self._format_score_line(score, idx=idx))
        if len(scores) > limit:
            lines.append(f"... 还有 {len(scores) - limit} 条未展示")
        return lines

    def _format_score_line(
        self,
        score: dict[str, Any],
        *,
        idx: int | None = None,
        include_time: bool = False,
    ) -> str:
        prefix = f"#{idx:02d} " if idx is not None else ""
        title = score.get("song_name") or f"ID {score.get('id', '-')}"
        diff = LEVEL_SHORT.get(score.get("level_index"), str(score.get("level_index", "-")))
        level = score.get("level") or "-"
        score_value = _format_number(score.get("score"))
        rating = _format_number(score.get("rating"), 2)
        rank = RANK_NAMES.get(str(score.get("rank") or "").lower(), str(score.get("rank") or "-").upper())
        badges = self._score_badges(score)
        line = f"{prefix}{rating} / {score_value} / {rank} [{diff} {level}] {title}"
        if badges:
            line += f" {' '.join(badges)}"
        if include_time:
            line += f" / {_format_time(score.get('play_time') or score.get('last_played_time'))}"
        return line

    def _score_badges(self, score: dict[str, Any]) -> list[str]:
        badges = []
        clear = CLEAR_NAMES.get(str(score.get("clear") or "").lower())
        if clear and clear not in {"CLEAR", "FAILED"}:
            badges.append(clear)
        fc = FULL_COMBO_NAMES.get(str(score.get("full_combo") or "").lower())
        if fc:
            badges.append(fc)
        chain = FULL_CHAIN_NAMES.get(str(score.get("full_chain") or "").lower())
        if chain:
            badges.append(chain)
        if score.get("over_power") is not None:
            badges.append(f"OP {_format_number(score.get('over_power'), 2)}")
        return badges

    def _format_song_brief(self, song: dict[str, Any]) -> str:
        levels = self._format_song_levels(song)
        artist = song.get("artist") or "-"
        return f"{song.get('id')} - {song.get('title')} / {artist} / BPM {song.get('bpm', '-')} / {levels}"

    def _format_song_detail(self, song: dict[str, Any], aliases: list[str]) -> str:
        lines = [
            f"{song.get('id')} - {song.get('title')}",
            f"艺术家：{song.get('artist') or '-'}",
            f"分类：{song.get('genre') or '-'} / BPM：{song.get('bpm') or '-'}",
            f"版本：{song.get('version') or '-'} / 地图：{song.get('map') or '-'}",
        ]
        if song.get("locked"):
            lines.append("状态：需要解锁")
        if song.get("disabled"):
            lines.append("状态：已禁用，不进入 Rating 构成")
        lines.append("谱面：")
        for diff in song.get("difficulties") or []:
            lines.append(f"- {self._format_difficulty_detail(diff)}")
        if aliases:
            shown = "、".join(aliases[:12])
            lines.append(f"别名：{shown}")
            if len(aliases) > 12:
                lines.append(f"还有 {len(aliases) - 12} 个别名，可用 /chu alias {song.get('id')} 查看。")
        jacket = self.asset_store.find("jacket", song.get("id"))
        lines.append(f"曲绘：{'已保存到本地素材库' if jacket else '本地素材库中暂无'}")
        return "\n".join(lines)

    def _format_song_levels(self, song: dict[str, Any]) -> str:
        parts = []
        for diff in song.get("difficulties") or []:
            name = LEVEL_SHORT.get(diff.get("difficulty"), str(diff.get("difficulty", "-")))
            level = diff.get("level") or "-"
            value = diff.get("level_value")
            if value is not None:
                parts.append(f"{name} {level}({value})")
            else:
                parts.append(f"{name} {level}")
        return " / ".join(parts) if parts else "-"

    def _format_difficulty_detail(self, diff: dict[str, Any]) -> str:
        name = LEVEL_NAMES.get(diff.get("difficulty"), str(diff.get("difficulty", "-")))
        level = diff.get("level") or "-"
        value = diff.get("level_value")
        designer = diff.get("note_designer") or "-"
        notes = diff.get("notes") or {}
        total = notes.get("total")
        value_part = f" / 定数 {value}" if value is not None else ""
        notes_part = f" / 物量 {total}" if total is not None else ""
        extra = ""
        if diff.get("difficulty") == 5:
            kanji = diff.get("kanji") or ""
            star = diff.get("star")
            extra = f" / {kanji}{star or ''}"
        return f"{name} {level}{value_part} / 谱师 {designer}{notes_part}{extra}"

    def _difficulty_matches_level(self, diff: dict[str, Any], level_filter: str) -> bool:
        level_filter = level_filter.strip().lower()
        level = str(diff.get("level") or "").lower()
        value = diff.get("level_value")
        if level_filter == level:
            return True
        if level_filter.endswith("+"):
            return level_filter == level
        if level_filter and level.startswith(level_filter):
            return True
        if value is not None and str(value).startswith(level_filter):
            return True
        return False
