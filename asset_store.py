from __future__ import annotations

import asyncio
import io
import json
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterable

from PIL import Image

if TYPE_CHECKING:
    import aiohttp


ASSET_KINDS = ("jacket", "character", "plate", "icon", "trophy")
SYNC_KINDS = ASSET_KINDS
COLLECTION_KEYS = {
    "character": "characters",
    "plate": "plates",
    "icon": "icons",
    "trophy": "trophies",
}
MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_IMAGE_DIMENSION = 8192
MAX_IMAGE_PIXELS = 40_000_000
MAX_CATALOG_BYTES = 8 * 1024 * 1024


async def _read_limited(response: Any, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.content.iter_chunked(64 * 1024):
        total += len(chunk)
        if total > limit:
            raise ValueError("Remote response exceeds the configured size limit")
        chunks.append(chunk)
    return b"".join(chunks)


class LocalAssetStore:
    def __init__(self, root: Path):
        self.root = root
        self.manifest_path = root / "manifest.json"
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def normalize_id(asset_id: Any) -> str | None:
        value = str(asset_id).strip()
        return value if re.fullmatch(r"\d{1,12}", value) else None

    def path(self, kind: str, asset_id: Any) -> Path | None:
        safe_id = self.normalize_id(asset_id)
        if kind not in ASSET_KINDS or safe_id is None:
            return None
        return self.root / kind / f"{safe_id}.png"

    def find(self, kind: str, asset_id: Any) -> Path | None:
        path = self.path(kind, asset_id)
        return path if path and self.valid_image(path) else None

    def find_many(self, kind: str, asset_ids: Iterable[Any]) -> dict[int, Path]:
        found: dict[int, Path] = {}
        for asset_id in asset_ids:
            path = self.find(kind, asset_id)
            if path is not None:
                found[int(asset_id)] = path
        return found

    def save(self, kind: str, asset_id: Any, data: bytes) -> Path:
        path = self.path(kind, asset_id)
        if path is None:
            raise ValueError(f"Invalid local asset key: {kind}/{asset_id}")
        if not self.valid_image_bytes(data):
            raise ValueError(f"Invalid image data: {kind}/{asset_id}")

        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".png.tmp")
        try:
            temporary.write_bytes(data)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return path

    def count(self, kind: str) -> int:
        directory = self.root / kind
        if not directory.exists():
            return 0
        count = 0
        for path in directory.glob("*.png"):
            try:
                if path.is_file() and 64 <= path.stat().st_size <= MAX_IMAGE_BYTES:
                    count += 1
            except OSError:
                continue
        return count

    def counts(self) -> dict[str, int]:
        return {kind: self.count(kind) for kind in ASSET_KINDS}

    def load_manifest(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            return {}
        try:
            with self.manifest_path.open("r", encoding="utf-8-sig") as handle:
                payload = json.load(handle)
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def save_manifest(self, payload: dict[str, Any]) -> None:
        temporary = self.manifest_path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        temporary.replace(self.manifest_path)

    @staticmethod
    def valid_image(path: Path) -> bool:
        if not path.exists() or not path.is_file() or not 64 <= path.stat().st_size <= MAX_IMAGE_BYTES:
            return False
        try:
            with Image.open(path) as image:
                if not LocalAssetStore._valid_dimensions(image):
                    return False
                image.verify()
            return True
        except (OSError, ValueError, Image.DecompressionBombError):
            return False

    @staticmethod
    def valid_image_bytes(data: bytes) -> bool:
        if not 64 <= len(data) <= MAX_IMAGE_BYTES:
            return False
        try:
            with Image.open(io.BytesIO(data)) as image:
                if not LocalAssetStore._valid_dimensions(image):
                    return False
                image.verify()
            return True
        except (OSError, ValueError, Image.DecompressionBombError):
            return False

    @staticmethod
    def _valid_dimensions(image: Image.Image) -> bool:
        width, height = image.size
        return (
            image.format == "PNG"
            and 0 < width <= MAX_IMAGE_DIMENSION
            and 0 < height <= MAX_IMAGE_DIMENSION
            and width * height <= MAX_IMAGE_PIXELS
        )


class PublicAssetSynchronizer:
    def __init__(
        self,
        store: LocalAssetStore,
        *,
        api_base: str,
        asset_base: str,
        version: int,
        timeout_seconds: int,
        concurrency: int = 1,
        delay_seconds: float = 0.5,
        user_agent: str = "astrbot_plugin_chunithm_lxns/0.3.0 asset-sync",
    ):
        self.store = store
        self.api_base = api_base.rstrip("/")
        self.asset_base = asset_base.rstrip("/")
        self.version = version
        self.timeout_seconds = timeout_seconds
        self.concurrency = max(1, min(concurrency, 4))
        self.delay_seconds = max(delay_seconds, 0.05)
        self.user_agent = user_agent

    async def sync(
        self,
        kinds: Iterable[str],
        progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        requested_kinds = tuple(dict.fromkeys(kind for kind in kinds if kind in SYNC_KINDS))
        if not requested_kinds:
            raise ValueError("No supported asset kind requested")

        state: dict[str, Any] = {
            "status": "discovering",
            "kinds": list(requested_kinds),
            "total": 0,
            "completed": 0,
            "downloaded": 0,
            "skipped": 0,
            "failed": 0,
        }
        self._notify(progress, state)

        import aiohttp

        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds, connect=min(self.timeout_seconds, 10))
        connector = aiohttp.TCPConnector(
            family=socket.AF_INET,
            limit=self.concurrency,
            ttl_dns_cache=300,
        )
        async with aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            trust_env=False,
            cookie_jar=aiohttp.DummyCookieJar(),
            headers={"User-Agent": self.user_agent},
        ) as session:
            plan = await self._discover(session, requested_kinds)
            state["total"] = len(plan)
            state["status"] = "downloading"
            self._notify(progress, state)

            queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
            for item in plan:
                queue.put_nowait(item)

            async def worker() -> None:
                while True:
                    try:
                        kind, asset_id = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                    requested = False
                    try:
                        if self.store.find(kind, asset_id):
                            state["skipped"] += 1
                        else:
                            requested = True
                            if await self._download_one(session, kind, asset_id):
                                state["downloaded"] += 1
                            else:
                                state["failed"] += 1
                    except Exception:
                        state["failed"] += 1
                    finally:
                        state["completed"] += 1
                        queue.task_done()
                        self._notify(progress, state)
                        if requested:
                            await asyncio.sleep(self.delay_seconds)

            await asyncio.gather(*(worker() for _ in range(self.concurrency)))

        state["status"] = "partial" if state["failed"] else "complete"
        state["completed_at"] = datetime.now(timezone.utc).isoformat()
        state["counts"] = self.store.counts()
        self.store.save_manifest(state)
        self._notify(progress, state)
        return state

    async def _discover(
        self,
        session: aiohttp.ClientSession,
        kinds: tuple[str, ...],
    ) -> list[tuple[str, int]]:
        plan: list[tuple[str, int]] = []
        if "jacket" in kinds:
            payload = await self._public_json(
                session,
                "chunithm/song/list",
                params={"version": self.version, "notes": "false"},
            )
            for song in payload.get("songs", []):
                if self.store.normalize_id(song.get("id")) is not None:
                    plan.append(("jacket", int(song["id"])))
                for difficulty in song.get("difficulties") or []:
                    origin_id = difficulty.get("origin_id")
                    if difficulty.get("difficulty") == 5 and self.store.normalize_id(origin_id) is not None:
                        plan.append(("jacket", int(origin_id)))
        for kind in kinds:
            if kind not in COLLECTION_KEYS:
                continue
            payload = await self._public_json(
                session,
                f"chunithm/{kind}/list",
                params={"version": self.version},
            )
            for collection in payload.get(COLLECTION_KEYS[kind], []):
                if kind == "trophy" and str(collection.get("color") or "").casefold() != "image":
                    continue
                if self.store.normalize_id(collection.get("id")) is not None:
                    plan.append((kind, int(collection["id"])))
        return list(dict.fromkeys(plan))

    async def _public_json(
        self,
        session: aiohttp.ClientSession,
        path: str,
        *,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        url = f"{self.api_base}/{path.lstrip('/')}"
        async with session.get(url, params=params, allow_redirects=False) as response:
            response.raise_for_status()
            content_length = int(response.headers.get("Content-Length") or 0)
            if content_length > MAX_CATALOG_BYTES:
                raise RuntimeError("Public LXNS catalog response is too large")
            body = await _read_limited(response, MAX_CATALOG_BYTES)
            payload = json.loads(body)
        if isinstance(payload, dict) and "success" in payload:
            if not payload.get("success"):
                raise RuntimeError(str(payload.get("message") or "Public LXNS API request failed"))
            payload = payload.get("data")
        if not isinstance(payload, dict):
            raise RuntimeError("Public LXNS API returned an invalid payload")
        return payload

    async def _download_one(
        self,
        session: aiohttp.ClientSession,
        kind: str,
        asset_id: int,
    ) -> bool:
        import aiohttp

        url = f"{self.asset_base}/{kind}/{asset_id}.png"
        for attempt in range(3):
            try:
                async with session.get(url, allow_redirects=False) as response:
                    if response.status == 200:
                        content_length = int(response.headers.get("Content-Length") or 0)
                        if content_length > MAX_IMAGE_BYTES:
                            return False
                        try:
                            data = await _read_limited(response, MAX_IMAGE_BYTES)
                        except ValueError:
                            return False
                        self.store.save(kind, asset_id, data)
                        return True
                    if response.status == 404:
                        return False
                    if response.status == 429 or response.status >= 500:
                        retry_after = response.headers.get("Retry-After")
                        delay = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt
                        await asyncio.sleep(min(delay, 30))
                        continue
                    return False
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                if attempt == 2:
                    return False
                await asyncio.sleep(2 ** attempt)
        return False

    @staticmethod
    def _notify(progress: Callable[[dict[str, Any]], None] | None, state: dict[str, Any]) -> None:
        if progress:
            progress(dict(state))
