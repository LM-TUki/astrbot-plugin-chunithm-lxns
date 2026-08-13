from __future__ import annotations

import ast
import importlib.util
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image


PLUGIN_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = PLUGIN_DIR / "asset_store.py"

spec = importlib.util.spec_from_file_location("chunithm_asset_store", MODULE_PATH)
asset_store_module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(asset_store_module)


def _image_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (32, 32), (24, 188, 203)).save(output, "PNG")
    return output.getvalue()


def _jpeg_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (32, 32), (24, 188, 203)).save(output, "JPEG")
    return output.getvalue()


class AssetStoreTests(unittest.TestCase):
    def test_limited_reader_collects_all_chunks_and_rejects_oversize_data(self) -> None:
        class Content:
            def __init__(self, chunks: list[bytes]):
                self.chunks = chunks

            async def iter_chunked(self, _size: int):
                for chunk in self.chunks:
                    yield chunk

        class Response:
            def __init__(self, chunks: list[bytes]):
                self.content = Content(chunks)

        import asyncio

        self.assertEqual(
            asyncio.run(asset_store_module._read_limited(Response([b"abc", b"def"]), 6)),
            b"abcdef",
        )
        with self.assertRaises(ValueError):
            asyncio.run(asset_store_module._read_limited(Response([b"abc", b"def"]), 5))

    def test_local_store_saves_and_finds_images(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = asset_store_module.LocalAssetStore(Path(directory))
            saved = store.save("jacket", 2432, _image_bytes())
            self.assertEqual(store.find("jacket", 2432), saved)
            self.assertEqual(store.counts()["jacket"], 1)

    def test_invalid_assets_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = asset_store_module.LocalAssetStore(Path(directory))
            self.assertIsNone(store.path("jacket", "../../token"))
            with self.assertRaises(ValueError):
                store.save("jacket", 1, b"not an image")
            with self.assertRaises(ValueError):
                store.save("jacket", 1, _jpeg_bytes())

    def test_b30_render_path_contains_no_asset_network_call(self) -> None:
        source = (PLUGIN_DIR / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = {
            node.name: ast.get_source_segment(source, node) or ""
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        render_source = functions["_render_b30"]
        self.assertIn("_local_jackets", render_source)
        self.assertIn("_local_player_assets", render_source)
        self.assertNotIn("session", render_source)
        self.assertNotIn("download", render_source)
        self.assertNotIn("_cache_asset", source)

    def test_public_sync_session_cannot_use_token_or_system_proxy(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("Authorization", source)
        self.assertNotIn("token", source.casefold())
        self.assertIn("trust_env=False", source)
        self.assertIn("cookie_jar=aiohttp.DummyCookieJar()", source)
        self.assertIn("family=socket.AF_INET", source)
        self.assertIn("allow_redirects=False", source)
        self.assertIn("MAX_IMAGE_BYTES", source)
        schema = __import__("json").loads((PLUGIN_DIR / "_conf_schema.json").read_text(encoding="utf-8"))
        self.assertEqual(schema["asset_sync_concurrency"]["default"], 1)
        self.assertGreaterEqual(schema["asset_sync_delay"]["default"], 0.5)

    def test_runtime_assets_are_ignored_by_git(self) -> None:
        ignore_rules = (PLUGIN_DIR / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("/assets/", ignore_rules)
        self.assertIn("/generated/", ignore_rules)

    def test_manifest_reader_accepts_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = asset_store_module.LocalAssetStore(Path(directory))
            store.manifest_path.write_bytes(b"\xef\xbb\xbf{\"status\": \"complete\"}")
            self.assertEqual(store.load_manifest()["status"], "complete")

    def test_discovery_uses_only_public_catalogs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            synchronizer = asset_store_module.PublicAssetSynchronizer(
                asset_store_module.LocalAssetStore(Path(directory)),
                api_base="https://example.invalid/api/v0",
                asset_base="https://assets.example.invalid/chunithm",
                version=23000,
                timeout_seconds=30,
            )
            responses = [
                {
                    "songs": [
                        {"id": 3},
                        {"id": 2432, "difficulties": [{"difficulty": 5, "origin_id": 9001}]},
                    ],
                },
                {"characters": [{"id": 10380}]},
                {"plates": [{"id": 7}]},
                {"icons": [{"id": 8}]},
                {"trophies": [{"id": 9, "color": "gold"}, {"id": 10, "color": "image"}]},
            ]
            with patch.object(synchronizer, "_public_json", AsyncMock(side_effect=responses)) as request:
                import asyncio

                plan = asyncio.run(
                    synchronizer._discover(object(), ("jacket", "character", "plate", "icon", "trophy")),
                )
        self.assertEqual(
            plan,
            [
                ("jacket", 3),
                ("jacket", 2432),
                ("jacket", 9001),
                ("character", 10380),
                ("plate", 7),
                ("icon", 8),
                ("trophy", 10),
            ],
        )
        requested_paths = [call.args[1] for call in request.await_args_list]
        self.assertEqual(
            requested_paths,
            [
                "chunithm/song/list",
                "chunithm/character/list",
                "chunithm/plate/list",
                "chunithm/icon/list",
                "chunithm/trophy/list",
            ],
        )

    def test_command_requires_slash_and_rich_results_quote_the_user(self) -> None:
        source = (PLUGIN_DIR / "main.py").read_text(encoding="utf-8")
        self.assertIn('@filter.regex(r"^/[Cc][Hh][Uu](?:\\s|$)")', source)
        self.assertNotIn('^/?chu', source)
        self.assertIn("Comp.Reply(id=message_id)", source)
        self.assertIn("Comp.Image.fromFileSystem", source)
        for command in ("_cmd_song", "_cmd_score", "_cmd_alias", "_cmd_random"):
            tree = ast.parse(source)
            function = next(node for node in ast.walk(tree) if getattr(node, "name", None) == command)
            command_source = ast.get_source_segment(source, function) or ""
            self.assertIn("BotResponse", command_source, command)
            self.assertIn("_song_jacket", command_source, command)

    def test_player_api_session_has_credential_leak_guards(self) -> None:
        source = (PLUGIN_DIR / "main.py").read_text(encoding="utf-8")
        self.assertIn("allow_custom_endpoints", source)
        self.assertIn("trust_env=False", source)
        self.assertIn("cookie_jar=aiohttp.DummyCookieJar()", source)
        self.assertIn("allow_redirects=not auth", source)
        self.assertIn("MAX_API_RESPONSE_BYTES", source)
        self.assertNotIn('f"无法连接落雪 API：{exc}"', source)
        schema = __import__("json").loads((PLUGIN_DIR / "_conf_schema.json").read_text(encoding="utf-8"))
        self.assertFalse(schema["allow_custom_endpoints"]["default"])
        self.assertFalse(schema["auto_resolve_qq"]["default"])


if __name__ == "__main__":
    unittest.main()
