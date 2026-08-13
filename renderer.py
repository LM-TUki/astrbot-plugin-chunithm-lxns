from __future__ import annotations

import math
from collections import deque
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps


WIDTH = 1700
MARGIN = 34
COLUMNS = 5
GAP_X = 18
GAP_Y = 18
CARD_WIDTH = (WIDTH - MARGIN * 2 - GAP_X * (COLUMNS - 1)) // COLUMNS
CARD_HEIGHT = 130

DIFFICULTY_NAMES = {
    0: "BASIC",
    1: "ADVANCED",
    2: "EXPERT",
    3: "MASTER",
    4: "ULTIMA",
    5: "WORLD'S END",
}

# ULTIMA intentionally uses a dark neutral body and warning-red edge. EXPERT
# keeps the official red family, so the two remain distinguishable at a glance.
DIFFICULTY_STYLES = {
    0: {"main": (72, 181, 62), "dark": (43, 119, 49), "label": "BASIC"},
    1: {"main": (235, 173, 28), "dark": (171, 112, 16), "label": "ADVANCED"},
    2: {"main": (239, 71, 55), "dark": (188, 41, 37), "label": "EXPERT"},
    3: {"main": (151, 30, 222), "dark": (91, 31, 153), "label": "MASTER"},
    4: {"main": (32, 35, 43), "dark": (12, 14, 19), "edge": (244, 42, 67), "label": "ULTIMA"},
    5: {"main": (54, 58, 67), "dark": (20, 23, 29), "edge": (84, 214, 229), "label": "WORLD'S END"},
}

SECTION_STYLES = {
    "BEST 30": (34, 205, 229),
    "SELECTION 10": (255, 205, 55),
    "NEW 20": (244, 104, 203),
}

RANK_LABELS = {
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

CLEAR_LABELS = {
    "catastrophy": "CATASTROPHY",
    "absolutepp": "ABSOLUTE++",
    "absolutep": "ABSOLUTE+",
    "absolute": "ABSOLUTE",
    "brave": "BRAVE",
    "hard": "HARD",
    "clear": "CLEAR",
    "failed": "FAILED",
}

COMBO_LABELS = {
    "alljusticecritical": "AJC",
    "alljustice": "ALL JUSTICE",
    "fullcombo": "FULL COMBO",
}

CHAIN_LABELS = {
    "fullchain": "FULL CHAIN",
    "fullchain2": "FULL CHAIN",
}

TROPHY_COLORS = {
    "normal": ((245, 245, 247), (91, 95, 108)),
    "copper": ((223, 153, 94), (91, 45, 18)),
    "silver": ((222, 231, 239), (61, 73, 88)),
    "gold": ((255, 223, 90), (105, 70, 4)),
    "platinum": ((211, 241, 244), (42, 87, 105)),
    "platina": ((211, 241, 244), (42, 87, 105)),
    "rainbow": ((235, 214, 255), (88, 55, 126)),
}

INK = (25, 29, 42)
MUTED = (96, 108, 127)
WHITE = (255, 255, 255)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return mask


def _cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(image.convert("RGBA"), size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def _contain(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    image = image.convert("RGBA")
    image.thumbnail(size, Image.Resampling.LANCZOS)
    target = Image.new("RGBA", size, (0, 0, 0, 0))
    target.alpha_composite(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    return target


def _remove_edge_white(image: Image.Image, tolerance: int = 18) -> Image.Image:
    image = image.convert("RGBA")
    pixels = image.load()
    width, height = image.size
    queue: deque[tuple[int, int]] = deque()
    seen: set[tuple[int, int]] = set()

    def near_white(x: int, y: int) -> bool:
        red, green, blue, _ = pixels[x, y]
        return red >= 255 - tolerance and green >= 255 - tolerance and blue >= 255 - tolerance

    for x in range(width):
        for y in (0, height - 1):
            if near_white(x, y):
                queue.append((x, y))
                seen.add((x, y))
    for y in range(height):
        for x in (0, width - 1):
            if near_white(x, y):
                queue.append((x, y))
                seen.add((x, y))

    while queue:
        x, y = queue.popleft()
        red, green, blue, _ = pixels[x, y]
        pixels[x, y] = (red, green, blue, 0)
        for next_x, next_y in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            point = (next_x, next_y)
            if 0 <= next_x < width and 0 <= next_y < height and point not in seen and near_white(next_x, next_y):
                seen.add(point)
                queue.append(point)
    return image


class FontBook:
    def __init__(self, static_dir: Path):
        self.cjk = self._find_font(
            static_dir / "fonts" / "NotoSansSC.ttf",
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
            Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"),
            Path("C:/Windows/Fonts/NotoSansSC-VF.ttf"),
            Path("C:/Windows/Fonts/msyhbd.ttc"),
        )
        self.latin = self._find_font(
            static_dir / "fonts" / "NotoSansSC.ttf",
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
            Path("C:/Windows/Fonts/arialbd.ttf"),
            self.cjk,
        )

    @staticmethod
    def _find_font(*paths: Path) -> Path:
        for path in paths:
            if path and path.exists():
                return path
        raise FileNotFoundError("No usable font was found for the CHUNITHM renderer")

    @lru_cache(maxsize=96)
    def font(self, size: int, *, latin: bool = False) -> ImageFont.FreeTypeFont:
        font = ImageFont.truetype(str(self.latin if latin else self.cjk), size)
        try:
            font.set_variation_by_name("SemiBold" if latin else "Bold")
        except (AttributeError, OSError, ValueError):
            pass
        return font

    def fit(self, draw: ImageDraw.ImageDraw, text: str, width: int, start: int, minimum: int = 10) -> ImageFont.FreeTypeFont:
        for size in range(start, minimum - 1, -1):
            font = self.font(size)
            if draw.textbbox((0, 0), text, font=font)[2] <= width:
                return font
        return self.font(minimum)


class ChunithmBestRenderer:
    def __init__(self, static_dir: Path, background_path: Path | None = None):
        self.static_dir = static_dir
        self.ui_dir = static_dir / "ui"
        self.fonts = FontBook(static_dir)
        self.background_path = background_path if background_path and background_path.exists() else None
        self._image_cache: dict[str, Image.Image] = {}

    def _ui_image(self, name: str, *, remove_white: bool = False) -> Image.Image | None:
        key = f"{name}:{remove_white}"
        if key not in self._image_cache:
            path = self.ui_dir / name
            if not path.exists():
                return None
            with Image.open(path) as source:
                image = source.convert("RGBA")
            if remove_white:
                image = _remove_edge_white(image)
            self._image_cache[key] = image
        return self._image_cache[key].copy()

    def render(
        self,
        player: dict[str, Any],
        sections: list[tuple[str, list[dict[str, Any]]]],
        output_path: Path,
        *,
        asset_paths: dict[str, Path | None],
        show_friend_code: bool = False,
        show_play_count: bool = False,
        footer_bot_name: str = "EmuBot",
    ) -> Path:
        visible_sections = [(title, rows) for title, rows in sections if rows]
        height = 340 + sum(self._section_height(len(rows)) for _, rows in visible_sections) + 95
        canvas = self._build_background(height)
        self._draw_player_header(
            canvas,
            player,
            asset_paths,
            show_friend_code=show_friend_code,
            show_play_count=show_play_count,
        )

        y = 306
        for title, rows in visible_sections:
            y = self._draw_section(canvas, y, title, rows)

        self._draw_footer(canvas, height, footer_bot_name)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(output_path, "JPEG", quality=94, optimize=True, progressive=True)
        return output_path

    @staticmethod
    def _section_height(row_count: int) -> int:
        lines = math.ceil(row_count / COLUMNS)
        cards_height = lines * CARD_HEIGHT + max(0, lines - 1) * GAP_Y
        return 54 + cards_height + 32

    def _build_background(self, height: int) -> Image.Image:
        top = (218, 255, 248, 255)
        middle = (237, 247, 255, 255)
        bottom = (252, 244, 255, 255)
        colors: list[tuple[int, int, int, int]] = []
        for y in range(height):
            position = y / max(1, height - 1)
            if position < 0.42:
                ratio = position / 0.42
                start, end = top, middle
            else:
                ratio = (position - 0.42) / 0.58
                start, end = middle, bottom
            colors.append(tuple(round(start[index] + (end[index] - start[index]) * ratio) for index in range(4)))

        gradient = Image.new("RGBA", (1, height))
        gradient.putdata(colors)
        canvas = gradient.resize((WIDTH, height))

        if self.background_path:
            background_key = f"background:{self.background_path}"
            if background_key not in self._image_cache:
                with Image.open(self.background_path) as background:
                    self._image_cache[background_key] = background.convert("RGBA")
            source = _cover(self._image_cache[background_key], (WIDTH, 650))
            canvas.alpha_composite(source, (0, 0))
            ImageDraw.Draw(canvas, "RGBA").rectangle((0, 0, WIDTH, 650), fill=(244, 252, 255, 116))

        draw = ImageDraw.Draw(canvas, "RGBA")
        draw.polygon(((0, 0), (790, 0), (505, 290), (0, 290)), fill=(32, 218, 203, 48))
        draw.polygon(((730, 0), (WIDTH, 0), (WIDTH, 290), (1035, 290)), fill=(184, 78, 224, 42))
        draw.polygon(((1220, 0), (WIDTH, 0), (WIDTH, 112), (1395, 208)), fill=(255, 94, 160, 42))
        draw.polygon(((0, 0), (365, 0), (0, 205)), fill=(255, 222, 75, 40))

        for box, color, width in (
            ((-345, -535, 875, 475), (10, 192, 202, 90), 9),
            ((-255, -455, 965, 555), (255, 255, 255, 135), 4),
            ((-165, -375, 1055, 635), (167, 76, 219, 62), 5),
            ((930, -610, 1920, 365), (255, 111, 177, 74), 7),
            ((1015, -520, 2005, 455), (255, 255, 255, 118), 4),
        ):
            draw.arc(box, start=205, end=355, fill=color, width=width)

        for x in range(-500, WIDTH + 500, 110):
            draw.line((x, -30, x + 410, 305), fill=(255, 255, 255, 72), width=2)
        for x in range(0, WIDTH + 1, 85):
            draw.line((x, 0, x, 290), fill=(74, 166, 191, 22), width=1)
        for y in range(0, 291, 58):
            draw.line((0, y, WIDTH, y), fill=(74, 166, 191, 22), width=1)

        draw.rectangle((0, 290, WIDTH, height), fill=(244, 250, 253, 218))
        draw.line((0, 290, WIDTH, 290), fill=(255, 255, 255, 210), width=3)
        for y in range(310, height, 340):
            draw.polygon(((0, y + 210), (610, y), (1020, y), (350, y + 340), (0, y + 340)), fill=(37, 209, 202, 48))
            draw.polygon(((WIDTH, y), (1250, y + 70), (970, y + 340), (WIDTH, y + 245)), fill=(173, 77, 220, 42))
        for offset in range(-500, WIDTH + 500, 330):
            draw.line((offset, 300, offset + height // 2, height), fill=(255, 255, 255, 90), width=2)
        return canvas

    def _draw_player_header(
        self,
        canvas: Image.Image,
        player: dict[str, Any],
        asset_paths: dict[str, Path | None],
        *,
        show_friend_code: bool,
        show_play_count: bool,
    ) -> None:
        draw = ImageDraw.Draw(canvas, "RGBA")
        panel = (MARGIN, 28, 1010, 278)
        plate_path = asset_paths.get("plate")
        if plate_path and plate_path.exists():
            plate = _cover(Image.open(plate_path), (panel[2] - panel[0], panel[3] - panel[1]))
            plate = ImageEnhance.Brightness(plate).enhance(1.08)
            canvas.paste(plate, (panel[0], panel[1]), _rounded_mask((panel[2] - panel[0], panel[3] - panel[1]), 8))
            draw.rounded_rectangle(panel, radius=8, fill=(255, 255, 255, 118), outline=(111, 199, 217, 230), width=3)
        else:
            draw.rounded_rectangle(panel, radius=8, fill=(255, 255, 255, 240), outline=(111, 199, 217, 230), width=3)

        trophy = player.get("trophy") or {}
        trophy_color = str(trophy.get("color") or "normal").lower()
        trophy_image = asset_paths.get("trophy")
        if trophy_color == "image" and trophy_image and trophy_image.exists():
            banner = _contain(Image.open(trophy_image), (706, 48))
            canvas.alpha_composite(banner, (51, 43))
        else:
            fill, text_color = TROPHY_COLORS.get(trophy_color, TROPHY_COLORS["normal"])
            draw.rounded_rectangle((52, 43, 758, 94), radius=8, fill=(*fill, 244), outline=(255, 255, 255, 220), width=2)
            draw.text((405, 68), str(trophy.get("name") or "NO TITLE"), font=self.fonts.fit(draw, str(trophy.get("name") or "NO TITLE"), 650, 22, 13), fill=text_color, anchor="mm")

        level = _as_int(player.get("level"))
        reborn = _as_int(player.get("reborn_count"))
        level_text = f"Lv.{level}" if not reborn else f"Re:{reborn}  Lv.{level}"
        draw.text((58, 123), level_text, font=self.fonts.font(26), fill=INK)
        player_name = str(player.get("name") or "UNKNOWN PLAYER")
        draw.text((172, 115), player_name, font=self.fonts.fit(draw, player_name, 560, 38, 24), fill=INK)

        draw.text((58, 180), "RATING", font=self.fonts.font(15, latin=True), fill=(47, 165, 178))
        draw.text((161, 163), f"{_as_float(player.get('rating')):.2f}", font=self.fonts.font(40, latin=True), fill=(37, 42, 58))

        emblem = player.get("class_emblem") or {}
        medal = _as_int(emblem.get("medal"))
        base = _as_int(emblem.get("base"))
        medal_image = self._ui_image(f"class-medal/{medal}.webp") if medal else None
        base_image = self._ui_image(f"class-base/{base}.webp") if base else None
        if base_image is not None:
            canvas.alpha_composite(_contain(base_image, (230, 45)), (320, 178))
        if medal_image is not None:
            canvas.alpha_composite(_contain(medal_image, (90, 70)), (320, 163))
        else:
            draw.ellipse((326, 170, 380, 224), fill=(85, 55, 145), outline=(255, 215, 55), width=5)
            draw.text((353, 197), self._class_mark(medal), font=self.fonts.font(21, latin=True), fill=WHITE, anchor="mm")
        draw.text((414, 175), "CLASS", font=self.fonts.font(12, latin=True), fill=MUTED)
        draw.text((414, 196), f"MEDAL {medal} / BASE {base}", font=self.fonts.font(17, latin=True), fill=INK)

        draw.text((584, 175), "OVER POWER", font=self.fonts.font(12, latin=True), fill=MUTED)
        draw.text((584, 196), f"{_as_float(player.get('over_power')):.2f}", font=self.fonts.font(21, latin=True), fill=INK)

        extras = []
        if show_friend_code and player.get("friend_code"):
            extras.append(f"FRIEND CODE {player['friend_code']}")
        if show_play_count and player.get("total_play_count") is not None:
            extras.append(f"PLAY COUNT {_as_int(player.get('total_play_count')):,}")
        if extras:
            draw.text((58, 246), "   /   ".join(extras), font=self.fonts.font(14, latin=True), fill=(58, 68, 84), anchor="lm")

        avatar_path = asset_paths.get("icon") or asset_paths.get("character")
        if avatar_path and avatar_path.exists():
            avatar = _cover(Image.open(avatar_path), (150, 150))
            canvas.paste(avatar, (805, 88), _rounded_mask((150, 150), 6))
        else:
            draw.rounded_rectangle((805, 88, 955, 238), radius=6, fill=(226, 233, 240, 255))
            draw.text((880, 163), "CHU", font=self.fonts.font(30, latin=True), fill=(117, 92, 154), anchor="mm")
        draw.rounded_rectangle((800, 83, 960, 243), radius=9, outline=(106, 76, 162, 230), width=4)

        logo_path = self.ui_dir / "logo-2026.png"
        if logo_path.exists():
            logo_source = self._ui_image("logo-2026.png", remove_white=True)
            if logo_source is not None:
                logo = _contain(logo_source, (500, 230))
                canvas.alpha_composite(logo, (WIDTH - MARGIN - 520, 6))
        else:
            draw.text((WIDTH - MARGIN, 78), "中二节奏 2026", font=self.fonts.font(44), fill=(93, 54, 138), anchor="ra")

        draw.rounded_rectangle((1060, 225, WIDTH - MARGIN, 277), radius=9, fill=(255, 255, 255, 228), outline=(177, 133, 222, 180), width=2)
        draw.text((1084, 251), "CHUNITHM 2026  RATING COMPOSITION", font=self.fonts.font(18, latin=True), fill=(61, 69, 91), anchor="lm")
        draw.text((WIDTH - MARGIN - 20, 251), "B30 + N20", font=self.fonts.font(22, latin=True), fill=(116, 72, 164), anchor="rm")

    @staticmethod
    def _class_mark(medal: int) -> str:
        return {0: "-", 1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}.get(medal, str(medal))

    def _draw_section(self, canvas: Image.Image, y: int, title: str, rows: list[dict[str, Any]]) -> int:
        draw = ImageDraw.Draw(canvas, "RGBA")
        color = SECTION_STYLES.get(title, (90, 205, 217))
        average = sum(_as_float(row.get("rating")) for row in rows) / len(rows)
        draw.rounded_rectangle((MARGIN, y, WIDTH - MARGIN, y + 40), radius=7, fill=(255, 255, 255, 230), outline=(*color, 245), width=2)
        draw.polygon(((MARGIN, y), (MARGIN + 325, y), (MARGIN + 282, y + 40), (MARGIN, y + 40)), fill=(*color, 242))
        draw.text((MARGIN + 18, y + 20), title, font=self.fonts.font(21, latin=True), fill=INK, anchor="lm")
        draw.text((WIDTH - MARGIN - 15, y + 20), f"AVG {average:.2f}", font=self.fonts.font(18, latin=True), fill=(64, 73, 93), anchor="rm")

        start_y = y + 54
        for index, score in enumerate(rows, start=1):
            row, column = divmod(index - 1, COLUMNS)
            x = MARGIN + column * (CARD_WIDTH + GAP_X)
            card_y = start_y + row * (CARD_HEIGHT + GAP_Y)
            canvas.alpha_composite(self._draw_card(score, index), (x, card_y))
        return y + self._section_height(len(rows))

    def _draw_card(self, score: dict[str, Any], index: int) -> Image.Image:
        difficulty = _as_int(score.get("level_index"), 3)
        style = DIFFICULTY_STYLES.get(difficulty, DIFFICULTY_STYLES[3])
        main = style["main"]
        dark = style["dark"]
        edge = style.get("edge", main)

        card = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (255, 255, 255, 250))
        draw = ImageDraw.Draw(card, "RGBA")
        draw.rounded_rectangle((0, 0, CARD_WIDTH - 1, CARD_HEIGHT - 1), radius=5, fill=(249, 250, 252, 252), outline=(255, 255, 255, 245), width=2)
        draw.rectangle((0, 0, 8, CARD_HEIGHT), fill=(*edge, 255))
        draw.rectangle((116, 0, CARD_WIDTH, 96), fill=(*main, 252))
        draw.polygon(((CARD_WIDTH - 64, 0), (CARD_WIDTH, 0), (CARD_WIDTH, 64)), fill=(*dark, 235))
        draw.rectangle((116, 95, CARD_WIDTH, CARD_HEIGHT), fill=(253, 253, 254, 255))

        if difficulty == 4:
            for offset in range(0, 42, 16):
                draw.polygon(((116 + offset, 0), (124 + offset, 0), (116 + offset, 17), (116 + max(0, offset - 8), 17)), fill=(244, 42, 67, 255))
            draw.rectangle((116, 92, CARD_WIDTH, 96), fill=(244, 42, 67, 255))
        elif difficulty == 5:
            for offset in range(0, 42, 14):
                draw.line((116 + offset, 0, 116 + offset - 16, 24), fill=(84, 214, 229, 255), width=5)

        jacket_path = score.get("jacket_path")
        if jacket_path and Path(jacket_path).exists():
            jacket = _cover(Image.open(jacket_path), (102, 102))
        else:
            jacket = Image.new("RGBA", (102, 102), (*dark, 255))
            placeholder_draw = ImageDraw.Draw(jacket)
            placeholder_draw.text((51, 51), "NO\nJACKET", font=self.fonts.font(15, latin=True), fill=WHITE, anchor="mm", align="center")
        card.paste(jacket, (14, 14), _rounded_mask((102, 102), 3))
        draw.rectangle((12, 12, 118, 118), outline=(255, 255, 255, 245), width=3)

        info_x = 127
        title = str(score.get("song_name") or f"ID {score.get('id', '-')}")
        draw.text((info_x, 6), title, font=self.fonts.fit(draw, title, CARD_WIDTH - info_x - 44, 17, 10), fill=WHITE)
        draw.text((CARD_WIDTH - 8, 7), f"#{index}", font=self.fonts.font(12, latin=True), fill=WHITE, anchor="ra")
        draw.text((info_x, 34), f"{_as_int(score.get('score')):,}", font=self.fonts.font(25, latin=True), fill=WHITE)
        draw.text((CARD_WIDTH - 8, 55), f"Ra {_as_float(score.get('rating')):.2f}", font=self.fonts.font(11, latin=True), fill=WHITE, anchor="ra")

        difficulty_label = str(style["label"])
        difficulty_key = difficulty_label.lower().replace(" ", "-").replace("'", "")
        difficulty_asset = self.ui_dir / f"difficulty-{difficulty_key}.png"
        if difficulty_asset.exists():
            badge_source = self._ui_image(difficulty_asset.name)
            if badge_source is not None:
                badge = badge_source.resize((62, 9), Image.Resampling.LANCZOS)
                card.alpha_composite(badge, (info_x, 75))
        else:
            draw.rounded_rectangle((info_x, 71, info_x + 62, 87), radius=2, fill=(*dark, 235), outline=(255, 255, 255, 115), width=1)
            draw.text((info_x + 31, 79), difficulty_label, font=self.fonts.fit(draw, difficulty_label, 58, 9, 7), fill=WHITE, anchor="mm")
        draw.text((info_x + 69, 70), f"Lv.{score.get('level') or '-'}", font=self.fonts.font(11, latin=True), fill=WHITE)
        level_value = score.get("level_value")
        constant = f"{_as_float(level_value):.1f}" if level_value is not None else "-"
        draw.text((info_x + 113, 70), f"定数 {constant}", font=self.fonts.font(10), fill=WHITE)

        self._draw_result_badge(card, score, info_x, 99)
        self._draw_rank_badge(card, str(score.get("rank") or "").lower(), CARD_WIDTH - 102, 99)
        return card

    def _draw_result_badge(self, card: Image.Image, score: dict[str, Any], x: int, y: int) -> None:
        combo = str(score.get("full_combo") or "").lower()
        chain = str(score.get("full_chain") or "").lower()
        clear = str(score.get("clear") or "").lower()
        asset_name = {
            "alljusticecritical": "result-alljusticecritical.webp",
            "alljustice": "result-alljustice.webp",
            "fullcombo": "result-fullcombo.webp",
        }.get(combo)
        if not asset_name and chain:
            asset_name = f"result-{chain}.webp"
        if not asset_name and clear:
            asset_name = f"result-{clear}.webp"
        self._paste_badge_or_text(
            card,
            asset_name,
            COMBO_LABELS.get(combo) or CHAIN_LABELS.get(chain) or CLEAR_LABELS.get(clear) or "NO PLAY",
            x,
            y,
            kind="result",
        )

    def _draw_rank_badge(self, card: Image.Image, rank: str, x: int, y: int) -> None:
        rank_asset = self.ui_dir / f"rank-{rank}.webp"
        if rank_asset.exists():
            badge_source = self._ui_image(rank_asset.name)
            if badge_source is not None:
                badge = badge_source.resize((93, 26), Image.Resampling.LANCZOS)
                card.alpha_composite(badge, (x, y))
                return
        self._paste_badge_or_text(card, None, RANK_LABELS.get(rank, rank.upper() or "-"), x, y, kind="rank")

    def _paste_badge_or_text(self, card: Image.Image, asset_name: str | None, label: str, x: int, y: int, *, kind: str) -> None:
        asset = self.ui_dir / asset_name if asset_name else None
        if asset and asset.exists():
            badge_source = self._ui_image(asset.name)
            if badge_source is not None:
                badge = badge_source.resize((93, 26), Image.Resampling.LANCZOS)
                card.alpha_composite(badge, (x, y))
                return
        draw = ImageDraw.Draw(card, "RGBA")
        if kind == "rank":
            fill, outline, text_color = (229, 244, 255, 255), (75, 172, 222, 255), (28, 87, 128)
        else:
            fill, outline, text_color = (255, 222, 59, 255), (220, 152, 15, 255), (79, 56, 4)
        draw.rectangle((x, y, x + 92, y + 25), fill=fill, outline=outline, width=1)
        draw.text((x + 46, y + 13), label, font=self.fonts.fit(draw, label, 88, 11, 7), fill=text_color, anchor="mm")

    def _draw_footer(self, canvas: Image.Image, height: int, footer_bot_name: str) -> None:
        draw = ImageDraw.Draw(canvas, "RGBA")
        footer_y = height - 38
        draw.line((MARGIN, footer_y - 17, WIDTH - MARGIN, footer_y - 17), fill=(73, 105, 135, 95), width=1)
        draw.text((MARGIN, footer_y), datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"), font=self.fonts.font(15, latin=True), fill=(63, 78, 99), anchor="lm")
        draw.text(
            (WIDTH - MARGIN, footer_y),
            f"Powered By maimai.lxns.net / Generated By {footer_bot_name}",
            font=self.fonts.font(15, latin=True),
            fill=(63, 78, 99),
            anchor="rm",
        )


def enrich_scores_with_catalog(
    scores: Iterable[dict[str, Any]],
    songs_by_id: dict[int, dict[str, Any]],
    jacket_paths: dict[int, Path],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for raw_score in scores:
        score = dict(raw_score)
        song_id = _as_int(score.get("id"), -1)
        difficulty_index = _as_int(score.get("level_index"), -1)
        song = songs_by_id.get(song_id) or {}
        difficulty = next(
            (
                item
                for item in song.get("difficulties") or []
                if _as_int(item.get("difficulty"), -2) == difficulty_index
            ),
            {},
        )
        if difficulty.get("level_value") is not None:
            score["level_value"] = difficulty.get("level_value")
        if not score.get("level") and difficulty.get("level"):
            score["level"] = difficulty.get("level")
        if not score.get("song_name") and song.get("title"):
            score["song_name"] = song.get("title")
        if song_id in jacket_paths:
            score["jacket_path"] = str(jacket_paths[song_id])
        enriched.append(score)
    return enriched
