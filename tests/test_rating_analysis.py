from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock

from test_text_formatting import main_module


def score(song_id=1, points=1008999, **fields):
    return {"id": song_id, "level_index": 3, "song_name": f"Song {song_id}", "score": points, "rating": 16.5, **fields}


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.plugin = main_module.ChunithmLxnsPlugin.__new__(main_module.ChunithmLxnsPlugin)

    def test_targets_use_exact_next_threshold_and_sort_by_gap(self):
        result = self.plugin._format_rating_analysis({"bests": [score(1, 1009000), score(2, 1007490), score(3, 1008999), score(4, 1007500)]}, targets=True)
        self.assertNotIn("Song 1", result)
        self.assertLess(result.index("Song 3"), result.index("Song 2"))
        self.assertIn("还差 1 分", result)
        self.assertIn("还差 10 分", result)
        self.assertIn("还差 1,500 分", result)

    def test_all_milestone_boundaries(self):
        for threshold in (975000, 990000, 1000000, 1005000, 1007500, 1009000):
            with self.subTest(threshold=threshold):
                result = self.plugin._format_rating_analysis({"bests": [score(points=threshold - 1)]}, targets=True)
                self.assertIn(f"{threshold:,}（还差 1 分）", result)

    def test_statistics_deduplicate_and_do_not_infer_aj_from_score(self):
        result = self.plugin._format_rating_analysis({"bests": [score(1, 1010000, rank="sssp"), score(2, full_combo="alljusticecritical")], "selections": [score(2, full_combo="alljusticecritical")]})
        self.assertIn("去重后 2 张", result)
        self.assertIn("AJ（含 AJC）1", result)
        self.assertIn("AJC 1", result)
        self.assertIn("New Best 20：暂无记录", result)

    def test_targets_limit_and_invalid_scores(self):
        rows = [score(index, 1008990 + index) for index in range(8)]
        result = self.plugin._format_rating_analysis({"bests": rows + [score(10, -1), score(11, 1010001), score(12, 1008999, level_index=5)]}, targets=True)
        self.assertEqual(result.count("还差"), 5)
        self.assertNotIn("Song 10", result)
        self.assertNotIn("Song 11", result)
        self.assertNotIn("Song 12", result)

    def test_empty_and_all_sss_plus(self):
        self.assertIn("请先同步成绩", self.plugin._format_rating_analysis({}, targets=True))
        self.assertIn("没有下一评级目标", self.plugin._format_rating_analysis({"bests": [score(points=1009000)]}, targets=True))

    def test_version_change_expires_catalog(self):
        self.plugin.default_version = 0
        self.plugin.cache_seconds = 86400
        fresh = {"fetched_at": main_module._now(), "requested_version": 23000}
        self.assertTrue(self.plugin._catalog_expired(fresh))
        fresh["requested_version"] = 0
        self.assertFalse(self.plugin._catalog_expired(fresh))


class CommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.plugin = main_module.ChunithmLxnsPlugin.__new__(main_module.ChunithmLxnsPlugin)
        self.plugin._resolve_friend_code = AsyncMock(return_value="888888888888888")
        self.plugin._api_rating_bests = AsyncMock(return_value={"bests": [score()]})

    async def test_stats_and_targets_dispatch(self):
        event = object()
        for command in ("stats", "targets", "统计", "冲分"):
            result = await self.plugin._dispatch(event, f"/chu {command}")
            self.assertNotIn("888888888888888", result)
            self.plugin._api_rating_bests.assert_awaited_with("888888888888888")
        with self.assertRaises(main_module.UserFacingError):
            await self.plugin._dispatch(event, "/chu targets extra")

    async def test_explicit_friend_code(self):
        event = object()
        await self.plugin._dispatch(event, "/chu stats 888888888888888")
        self.plugin._resolve_friend_code.assert_awaited_with(event, "888888888888888")

    async def test_b30_recalculates_rating_with_empty_new_slots(self):
        self.plugin.render_b30_image = False
        self.plugin.show_friend_code = False
        self.plugin.show_play_count = False
        self.plugin.b30_show_count = 30
        self.plugin.selection_show_count = 10
        self.plugin._api_player = AsyncMock(return_value={"name": "Player", "rating": 16.67})
        self.plugin._api_rating_bests = AsyncMock(
            return_value={
                "bests": [score(index, rating=16.0) for index in range(30)],
                "new_bests": [score(100 + index, rating=16.0) for index in range(9)],
            }
        )

        result = await self.plugin._cmd_b30(object(), "")

        self.assertIn("Rating 12.48", result)
        self.assertNotIn("Rating 16.67", result)

    async def test_b30_warns_when_profile_snapshot_is_older_than_scores(self):
        self.plugin.render_b30_image = False
        self.plugin.show_friend_code = False
        self.plugin.show_play_count = False
        self.plugin.b30_show_count = 30
        self.plugin.selection_show_count = 10
        self.plugin._api_player = AsyncMock(
            return_value={
                "name": "Player",
                "rating": 16.67,
                "upload_time": "2026-08-23T05:13:52Z",
            }
        )
        self.plugin._api_rating_bests = AsyncMock(
            return_value={
                "bests": [score(1, rating=16.0, upload_time="2026-09-11T15:00:00Z")]
            }
        )

        result = await self.plugin._cmd_b30(object(), "")

        self.assertIn("玩家资料快照早于最新成绩", result)
        self.assertIn("/chu sync", result)

    async def test_sync_command_returns_official_lxns_entry(self):
        result = await self.plugin._dispatch(object(), "/chu sync")
        self.assertIn("https://maimai.lxns.net/docs/sync", result)
        self.assertIn("/api/v0/chunithm/wechat/auth", result)

    async def test_auto_catalog_omits_version_and_force_does_not_hide_failure(self):
        self.plugin.default_version = 0
        self.plugin.cache_seconds = 86400
        self.plugin.catalog_lock = asyncio.Lock()
        self.plugin.catalog = None
        self.plugin._load_catalog_from_disk = Mock(return_value=None)
        self.plugin._request = AsyncMock(side_effect=[{"songs": []}, {"aliases": []}])
        with tempfile.TemporaryDirectory() as directory:
            self.plugin.catalog_file = Path(directory) / "catalog.json"
            catalog = await self.plugin._get_catalog()
            self.assertEqual(catalog["requested_version"], 0)
            self.assertNotIn("version", self.plugin._request.await_args_list[0].kwargs["params"])
            self.plugin._request = AsyncMock(side_effect=main_module.UserFacingError("offline"))
            with self.assertRaises(main_module.UserFacingError):
                await self.plugin._get_catalog(force=True)

    async def test_network_failure_never_reuses_other_version(self):
        self.plugin.default_version = 0
        self.plugin.cache_seconds = 86400
        self.plugin.catalog_lock = asyncio.Lock()
        self.plugin.catalog = {"requested_version": 23000, "fetched_at": main_module._now()}
        self.plugin._load_catalog_from_disk = Mock(return_value=self.plugin.catalog)
        self.plugin._request = AsyncMock(side_effect=main_module.UserFacingError("offline"))
        with self.assertRaises(main_module.UserFacingError):
            await self.plugin._get_catalog()

    async def test_b30_refreshes_catalog_when_a_chart_has_no_constant(self):
        self.plugin.b30_show_count = 30
        self.plugin.selection_show_count = 0
        self.plugin._local_jackets = Mock(return_value={})
        self.plugin._local_player_assets = Mock(return_value={})
        self.plugin._validate_rating_sections = Mock()
        self.plugin._cleanup_generated_images = Mock()
        self.plugin._get_catalog = AsyncMock(
            return_value={
                "songs": [
                    {
                        "id": 1,
                        "title": "Fresh Song",
                        "difficulties": [
                            {"difficulty": 3, "level": "14+", "level_value": 14.8}
                        ],
                    }
                ]
            }
        )
        self.plugin.renderer = Mock()
        self.plugin.renderer.render = Mock()
        self.plugin.generated_dir = Path(tempfile.gettempdir())
        self.plugin.render_semaphore = asyncio.Semaphore(1)
        self.plugin.show_friend_code = False
        self.plugin.show_play_count = False
        self.plugin.footer_bot_name = ""

        await self.plugin._render_b30({}, {"bests": [score()]}, {"songs": []})

        self.plugin._get_catalog.assert_awaited_once_with(force=True)
        rendered_sections = self.plugin.renderer.render.call_args.args[1]
        self.assertEqual(rendered_sections[0][1][0]["level_value"], 14.8)


if __name__ == "__main__":
    unittest.main()
