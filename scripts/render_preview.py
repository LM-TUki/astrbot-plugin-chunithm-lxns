"""Render reproducible, clearly labelled demo images without a player token."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "preview_renderer", PLUGIN_DIR / "renderer.py"
)
assert spec and spec.loader
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


def main() -> None:
    """Render all three sections using synthetic scores and optional local jackets."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=PLUGIN_DIR / "generated" / "b30-preview.jpg"
    )
    parser.add_argument(
        "--catalog", type=Path, help="Optional public LXNS song-list JSON"
    )
    parser.add_argument(
        "--assets", type=Path, help="Directory containing <song-id>.png jackets"
    )
    parser.add_argument(
        "--song-ids",
        action="store_true",
        help="Print the selected public jacket IDs and exit",
    )
    args = parser.parse_args()
    if args.catalog:
        songs = json.loads(args.catalog.read_text(encoding="utf-8"))["songs"]
        songs = [
            song
            for song in songs
            if any(
                13.7 <= float(chart.get("level_value") or 0) <= 15.5
                for chart in song.get("difficulties", [])
            )
        ][:30]
    else:
        titles = (
            "光の向こうへ",
            "Crossing the Gate",
            "星海 · 未来への旅",
            "夜明けのシンフォニー",
            "A Very Long Song Title / 超长曲名排版示例",
        )
        songs = [
            {
                "id": index + 1,
                "title": titles[index % len(titles)],
                "difficulties": [
                    {"difficulty": difficulty, "level_value": 14.5 + (index % 6) / 10}
                    for difficulty in (2, 3, 4)
                ],
            }
            for index in range(30)
        ]
    if not songs:
        parser.error("The supplied catalog contains no suitable demo charts")
    if args.song_ids:
        print("\n".join(str(song["id"]) for song in songs))
        return

    rows = []
    for index in range(60):
        song = songs[index % len(songs)]
        charts = [
            chart
            for chart in song["difficulties"]
            if chart.get("difficulty") in (2, 3, 4)
        ]
        charts.sort(key=lambda chart: {3: 0, 4: 1, 2: 2}[chart["difficulty"]])
        chart = charts[(index // len(songs)) % len(charts)]
        constant = float(chart.get("level_value") or 14.5)
        score = (1010000, 1009850, 1009000, 1008742, 1007490, 1006200)[index % 6]
        rating = constant + (
            2.15
            if score >= 1009000
            else 2 + (score - 1007500) / 10000
            if score >= 1007500
            else 1.5 + (score - 1005000) / 5000
        )
        jacket = args.assets / f"{song['id']}.png" if args.assets else None
        rows.append(
            {
                "id": song["id"],
                "song_name": song["title"],
                "level_index": chart["difficulty"],
                "level_value": constant,
                "score": score,
                "rating": rating,
                "rank": "sssp"
                if score >= 1009000
                else "sss"
                if score >= 1007500
                else "ssp",
                "clear": "hard",
                "full_combo": (
                    "alljusticecritical",
                    "alljustice",
                    "fullcombo",
                    None,
                    None,
                    None,
                )[index % 6],
                "jacket_path": str(jacket) if jacket and jacket.exists() else None,
            }
        )
    sections = [
        (title, sorted(rows[start:end], key=lambda row: row["rating"], reverse=True))
        for title, start, end in (
            ("BEST 30", 0, 30),
            ("SELECTION 10", 30, 40),
            ("NEW 20", 40, 60),
        )
    ]
    player = {
        "name": "星海 · DEMO PLAYER",
        "rating": 16.82,
        "level": 128,
        "over_power": 36582.42,
        "class_emblem": {"base": 5, "medal": 5},
        "trophy": {
            "name": "PREVIEW · 示例成绩 / 穿越星门，向下一段旅程出发",
            "color": "platinum",
        },
    }
    renderer.ChunithmBestRenderer(PLUGIN_DIR / "static").render(
        player,
        sections,
        args.output,
        asset_paths={},
        footer_bot_name="EmuBot · 示例成绩 / DEMO",
    )
    help_output = args.output.with_name("help-preview.png")
    renderer.ChunithmHelpRenderer(PLUGIN_DIR / "static").render(help_output)
    print(args.output)
    print(help_output)


if __name__ == "__main__":
    main()
