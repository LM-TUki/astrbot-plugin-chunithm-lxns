from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw


PLUGIN_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = PLUGIN_DIR / "renderer.py"

spec = importlib.util.spec_from_file_location("chunithm_renderer", MODULE_PATH)
renderer_module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(renderer_module)


def _fixture() -> tuple[dict, dict[int, dict], dict[str, list[dict]]]:
    player = {
        "name": "TEST PLAYER",
        "level": 89,
        "rating": 16.62,
        "friend_code": 888888888888888,
        "total_play_count": 668,
        "class_emblem": {"base": 0, "medal": 5},
        "reborn_count": 0,
        "over_power": 33601.11,
        "trophy": {"name": "I'm so Happy", "color": "platinum"},
    }
    songs = {
        101: {
            "id": 101,
            "title": "Expert Song",
            "difficulties": [{"difficulty": 2, "level": "14", "level_value": 14.4}],
        },
        102: {
            "id": 102,
            "title": "Master Song",
            "difficulties": [{"difficulty": 3, "level": "14+", "level_value": 14.9}],
        },
        103: {
            "id": 103,
            "title": "Ultima Song",
            "difficulties": [{"difficulty": 4, "level": "15", "level_value": 15.1}],
        },
    }
    scores = {
        "bests": [
            {
                "id": 102,
                "song_name": "Master Song",
                "level": "14+",
                "level_index": 3,
                "score": 1_008_430,
                "rating": 17.093,
                "rank": "sss",
                "clear": "hard",
                "full_combo": None,
                "full_chain": None,
            },
        ],
        "selections": [
            {
                "id": 103,
                "song_name": "Ultima Song",
                "level": "15",
                "level_index": 4,
                "score": 1_010_000,
                "rating": 17.15,
                "rank": "sssp",
                "clear": "hard",
                "full_combo": None,
                "full_chain": None,
            },
        ],
        "new_bests": [
            {
                "id": 101,
                "song_name": "Expert Song",
                "level": "14",
                "level_index": 2,
                "score": 1_007_500,
                "rating": 16.4,
                "rank": "sss",
                "clear": "clear",
                "full_combo": "fullcombo",
                "full_chain": None,
            },
        ],
    }
    return player, songs, scores


def _jackets(directory: Path) -> dict[int, Path]:
    paths = {}
    for song_id, color in ((101, (238, 72, 57)), (102, (151, 30, 222)), (103, (28, 31, 39))):
        path = directory / f"{song_id}.png"
        image = Image.new("RGB", (128, 128), color)
        ImageDraw.Draw(image).text((64, 64), str(song_id), fill="white", anchor="mm")
        image.save(path)
        paths[song_id] = path
    return paths


class RendererTests(unittest.TestCase):
    def test_long_card_title_is_ellipsized_to_available_width(self) -> None:
        renderer = renderer_module.ChunithmBestRenderer(PLUGIN_DIR / "static")
        image = Image.new("RGBA", (300, 80), "white")
        draw = ImageDraw.Draw(image)
        font = renderer.fonts.font(17)
        title = "测试用超长歌曲名称 The Future of CHUNITHM Is Here"
        result = renderer_module._ellipsize(draw, title, font, 120)
        self.assertTrue(result.endswith("..."))
        self.assertLessEqual(draw.textlength(result, font=font), 120)

    def test_catalog_join_preserves_api_order_and_constants(self) -> None:
        _, songs, scores = _fixture()
        with tempfile.TemporaryDirectory() as directory:
            jackets = _jackets(Path(directory))
            bests = renderer_module.enrich_scores_with_catalog(scores["bests"], songs, jackets)
            new_bests = renderer_module.enrich_scores_with_catalog(scores["new_bests"], songs, jackets)
        self.assertEqual([row["id"] for row in bests], [102])
        self.assertEqual([row["id"] for row in new_bests], [101])
        self.assertEqual(bests[0]["level_value"], 14.9)
        self.assertEqual(new_bests[0]["level_value"], 14.4)

    def test_result_badge_uses_api_fields_only(self) -> None:
        _, _, scores = _fixture()
        score = scores["selections"][0]
        self.assertEqual(score["score"], 1_010_000)
        self.assertIsNone(score["full_combo"])
        self.assertIsNone(renderer_module.COMBO_LABELS.get(str(score["full_combo"] or "").lower()))
        renderer = renderer_module.ChunithmBestRenderer(PLUGIN_DIR / "static")
        with patch.object(renderer, "_paste_badge_or_text") as paste_badge:
            renderer._draw_result_badge(Image.new("RGBA", (200, 80)), score, 0, 0)
        self.assertEqual(paste_badge.call_args.args[1], "result-hard.webp")
        self.assertEqual(paste_badge.call_args.args[2], "HARD")

    def test_official_result_and_rank_assets_are_complete(self) -> None:
        ui_dir = PLUGIN_DIR / "static" / "ui"
        for rank in renderer_module.RANK_LABELS:
            self.assertTrue((ui_dir / f"rank-{rank}.webp").exists(), rank)
        for result in (
            "failed",
            "clear",
            "hard",
            "brave",
            "absolute",
            "absolutep",
            "absolutepp",
            "catastrophy",
            "fullcombo",
            "alljustice",
            "alljusticecritical",
            "fullchain",
            "fullchain2",
        ):
            self.assertTrue((ui_dir / f"result-{result}.webp").exists(), result)

    def test_ultima_and_expert_cards_are_visually_distinct(self) -> None:
        renderer = renderer_module.ChunithmBestRenderer(PLUGIN_DIR / "static")
        _, _, scores = _fixture()
        common = {**scores["new_bests"][0], "level_value": 14.4}
        expert = renderer._draw_card({**common, "level_index": 2}, 1)
        ultima = renderer._draw_card({**common, "level_index": 4}, 1)
        expert_color = expert.getpixel((300, 88))
        ultima_color = ultima.getpixel((300, 88))
        self.assertNotEqual(expert_color, ultima_color)
        self.assertLess(sum(ultima_color[:3]), sum(expert_color[:3]))

    def test_privacy_options_default_to_false(self) -> None:
        schema = json.loads((PLUGIN_DIR / "_conf_schema.json").read_text(encoding="utf-8"))
        self.assertFalse(schema["show_friend_code"]["default"])
        self.assertFalse(schema["show_play_count"]["default"])

    def test_default_background_does_not_use_a_promotional_screenshot(self) -> None:
        renderer = renderer_module.ChunithmBestRenderer(PLUGIN_DIR / "static")
        self.assertIsNone(renderer.background_path)
        self.assertFalse((PLUGIN_DIR / "static" / "ui" / "official-2026-ui.jpg").exists())

    def test_fixture_renders(self) -> None:
        player, songs, scores = _fixture()
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            jackets = _jackets(directory_path)
            sections = [
                (
                    title,
                    renderer_module.enrich_scores_with_catalog(scores[key], songs, jackets),
                )
                for title, key in (("BEST 30", "bests"), ("SELECTION 10", "selections"), ("NEW 20", "new_bests"))
            ]
            output = directory_path / "b30-preview.jpg"
            renderer = renderer_module.ChunithmBestRenderer(PLUGIN_DIR / "static")
            result = renderer.render(
                player,
                sections,
                output,
                asset_paths={"character": None, "plate": None, "icon": None, "trophy": None},
                show_friend_code=False,
                show_play_count=False,
            )
            with Image.open(result) as image:
                self.assertEqual(image.width, renderer_module.WIDTH)
                self.assertGreater(image.height, 800)
                self.assertIsNotNone(image.getbbox())


if __name__ == "__main__":
    unittest.main()
