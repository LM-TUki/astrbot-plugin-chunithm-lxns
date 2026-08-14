from __future__ import annotations

import importlib.util
import sys
import types
import unicodedata
import unittest
from pathlib import Path


PLUGIN_DIR = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "chunithm_plugin_under_test"


def _install_astrbot_stubs() -> None:
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    components = types.ModuleType("astrbot.api.message_components")
    event = types.ModuleType("astrbot.api.event")
    star = types.ModuleType("astrbot.api.star")

    class DummyLogger:
        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    class DummyFilter:
        @staticmethod
        def regex(pattern):
            return lambda function: function

    class DummyStar:
        def __init__(self, context=None, config=None):
            self.context = context
            self.config = config

    def register(*args, **kwargs):
        return lambda cls: cls

    api.logger = DummyLogger()
    event.AstrMessageEvent = object
    event.filter = DummyFilter()
    star.Context = object
    star.Star = DummyStar
    star.register = register
    sys.modules.update(
        {
            "astrbot": astrbot,
            "astrbot.api": api,
            "astrbot.api.message_components": components,
            "astrbot.api.event": event,
            "astrbot.api.star": star,
        }
    )


def _load_main_module():
    _install_astrbot_stubs()
    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(PLUGIN_DIR)]
    sys.modules[PACKAGE_NAME] = package
    spec = importlib.util.spec_from_file_location(f"{PACKAGE_NAME}.main", PLUGIN_DIR / "main.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


main_module = _load_main_module()


def _display_width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1 for char in text)


class TextFormattingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plugin = main_module.ChunithmLxnsPlugin.__new__(main_module.ChunithmLxnsPlugin)

    def test_score_fields_are_grouped_instead_of_one_long_line(self) -> None:
        score = {
            "song_name": "测试用超长歌曲名称 The Future of CHUNITHM Is Here and Beyond",
            "level_index": 3,
            "level": "15+",
            "score": 1_009_990,
            "rating": 17.12,
            "rank": "sssp",
            "clear": "hard",
            "full_combo": "alljusticecritical",
            "full_chain": "fullchain2",
            "over_power": 86.54,
            "play_time": "2026-08-14T08:23:45.123456Z",
        }
        result = self.plugin._format_score_line(score, idx=1, include_time=True)
        lines = result.splitlines()
        self.assertEqual(len(lines), 3)
        self.assertIn("#01", lines[0])
        self.assertIn("Rating 17.12", lines[1])
        self.assertEqual(lines[2], "  时间：2026-08-14 08:23:45 UTC")
        self.assertTrue(all(_display_width(line) <= 72 for line in lines))

    def test_song_search_result_is_split_into_scannable_lines(self) -> None:
        song = {
            "id": 1234,
            "title": "测试用超长歌曲名称 The Future of CHUNITHM Is Here and Beyond",
            "artist": "Long Artist Unit feat. 排版检查联合艺术家",
            "bpm": 190,
            "difficulties": [
                {"difficulty": 2, "level": "14", "level_value": 14.2},
                {"difficulty": 3, "level": "15+", "level_value": 15.7},
            ],
        }
        lines = self.plugin._format_song_brief(song).splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[1].lstrip().startswith("艺术家："))
        self.assertTrue(lines[2].lstrip().startswith("难度："))
        self.assertTrue(all(_display_width(line) <= 72 for line in lines))


if __name__ == "__main__":
    unittest.main()
