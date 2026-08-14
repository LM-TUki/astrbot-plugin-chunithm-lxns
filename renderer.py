from __future__ import annotations

import math
from collections import deque
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps


WIDTH = 1700
MARGIN = 42
COLUMNS = 5
GAP_X = 16
GAP_Y = 16
CARD_WIDTH = (WIDTH - MARGIN * 2 - GAP_X * (COLUMNS - 1)) // COLUMNS
CARD_HEIGHT = 132
JACKET_SIZE = 128
BADGE_WIDTH = 82
BADGE_HEIGHT = 22

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
    0: {"main": (67, 177, 84), "dark": (32, 105, 54), "edge": (108, 220, 120)},
    1: {"main": (232, 166, 28), "dark": (148, 92, 5), "edge": (255, 207, 68)},
    2: {"main": (231, 67, 65), "dark": (150, 33, 40), "edge": (255, 105, 99)},
    3: {"main": (135, 44, 218), "dark": (74, 27, 139), "edge": (180, 90, 255)},
    4: {"main": (28, 31, 39), "dark": (8, 10, 15), "edge": (245, 47, 67)},
    5: {"main": (43, 48, 58), "dark": (14, 17, 23), "edge": (63, 213, 227)},
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

INK = (18, 22, 31)
MUTED = (91, 101, 116)
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


def _open_rgba(path: Path) -> Image.Image:
    with Image.open(path) as source:
        return source.convert("RGBA").copy()


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    suffix = "..."
    suffix_width = draw.textlength(suffix, font=font)
    low, high = 0, len(text)
    while low < high:
        midpoint = (low + high + 1) // 2
        if draw.textlength(text[:midpoint], font=font) + suffix_width <= max_width:
            low = midpoint
        else:
            high = midpoint - 1
    return text[:low].rstrip() + suffix


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

    @lru_cache(maxsize=192)
    def font(self, size: int, *, latin: bool = False, weight: str = "bold") -> ImageFont.FreeTypeFont:
        font = ImageFont.truetype(str(self.latin if latin else self.cjk), size)
        try:
            variation = {
                "regular": "Regular",
                "medium": "Medium",
                "semibold": "SemiBold",
                "bold": "Bold",
                "black": "Black",
            }.get(weight, "Bold")
            font.set_variation_by_name(variation)
        except (AttributeError, OSError, ValueError):
            pass
        return font

    def fit(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        width: int,
        start: int,
        minimum: int = 10,
        *,
        latin: bool = False,
        weight: str = "bold",
    ) -> ImageFont.FreeTypeFont:
        for size in range(start, minimum - 1, -1):
            font = self.font(size, latin=latin, weight=weight)
            if draw.textbbox((0, 0), text, font=font)[2] <= width:
                return font
        return self.font(minimum, latin=latin, weight=weight)


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
        height = 334 + sum(self._section_height(len(rows)) for _, rows in visible_sections) + 92
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
        return 60 + cards_height + 34

    def _build_background(self, height: int) -> Image.Image:
        canvas = Image.new("RGBA", (WIDTH, height), (242, 245, 248, 255))
        draw = ImageDraw.Draw(canvas, "RGBA")
        draw.rectangle((0, 0, WIDTH, 286), fill=(252, 253, 254, 255))
        draw.rectangle((0, 0, 520, 10), fill=(248, 207, 56, 255))
        draw.rectangle((520, 0, 1130, 10), fill=(27, 194, 205, 255))
        draw.rectangle((1130, 0, WIDTH, 10), fill=(215, 73, 185, 255))

        if self.background_path:
            background_key = f"background:{self.background_path}"
            if background_key not in self._image_cache:
                with Image.open(self.background_path) as background:
                    self._image_cache[background_key] = background.convert("RGBA")
            source = _cover(self._image_cache[background_key], (WIDTH, 286))
            canvas.alpha_composite(source, (0, 0))
            draw.rectangle((0, 0, WIDTH, 286), fill=(250, 252, 254, 184))

        for x in range(0, WIDTH + 1, 92):
            draw.line((x, 286, x, height), fill=(51, 72, 91, 13), width=1)
        for y in range(286, height, 92):
            draw.line((0, y, WIDTH, y), fill=(51, 72, 91, 13), width=1)
        for offset in range(-height, WIDTH + height, 250):
            draw.line((offset, 286, offset + height, height), fill=(255, 255, 255, 82), width=2)

        draw.polygon(((0, 286), (345, 286), (0, 520)), fill=(25, 189, 202, 30))
        draw.polygon(((WIDTH, 286), (1470, 286), (WIDTH, 515)), fill=(207, 64, 179, 26))
        draw.line((22, 310, 22, height - 72), fill=(26, 188, 201, 150), width=4)
        draw.line((WIDTH - 23, 310, WIDTH - 23, height - 72), fill=(213, 71, 184, 110), width=3)

        for row in range(4):
            for column in range(12):
                x = 1070 + column * 22 + row * 7
                y = 26 + row * 22
                draw.ellipse((x, y, x + 5, y + 5), fill=(27, 35, 48, 60))
        draw.line((0, 286, WIDTH, 286), fill=(24, 31, 43, 180), width=2)
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
        panel = (MARGIN, 30, 1050, 258)
        draw.rounded_rectangle((MARGIN + 7, 37, 1057, 265), radius=7, fill=(20, 29, 42, 24))
        plate_path = asset_paths.get("plate")
        if plate_path and plate_path.exists():
            panel_size = (panel[2] - panel[0], panel[3] - panel[1])
            plate = _cover(_open_rgba(plate_path), panel_size)
            plate = ImageEnhance.Brightness(plate).enhance(1.12)
            plate = Image.alpha_composite(plate, Image.new("RGBA", panel_size, (255, 255, 255, 198)))
            canvas.paste(plate, (panel[0], panel[1]), _rounded_mask((panel[2] - panel[0], panel[3] - panel[1]), 8))
        else:
            draw.rounded_rectangle(panel, radius=8, fill=(255, 255, 255, 248))
        draw.rounded_rectangle(panel, radius=8, outline=(31, 43, 57, 210), width=2)
        draw.rectangle((MARGIN, 30, MARGIN + 9, 258), fill=(24, 190, 203, 255))
        draw.rectangle((MARGIN + 9, 30, MARGIN + 15, 258), fill=(239, 203, 56, 255))
        draw.text((72, 49), "PLAYER PROFILE / CHUNITHM 2026", font=self.fonts.font(12, latin=True, weight="semibold"), fill=MUTED)

        trophy = player.get("trophy") or {}
        trophy_color = str(trophy.get("color") or "normal").lower()
        trophy_image = asset_paths.get("trophy")
        if trophy_color == "image" and trophy_image and trophy_image.exists():
            banner = _contain(_open_rgba(trophy_image), (690, 42))
            canvas.alpha_composite(banner, (66, 62))
        else:
            fill, text_color = TROPHY_COLORS.get(trophy_color, TROPHY_COLORS["normal"])
            draw.rounded_rectangle((68, 65, 758, 104), radius=4, fill=(*fill, 238), outline=(42, 54, 68, 62), width=1)
            trophy_name = str(trophy.get("name") or "NO TITLE")
            draw.text((413, 84), trophy_name, font=self.fonts.fit(draw, trophy_name, 640, 19, 12, weight="bold"), fill=text_color, anchor="mm")

        level = _as_int(player.get("level"))
        reborn = _as_int(player.get("reborn_count"))
        level_text = f"Lv.{level}" if not reborn else f"Re:{reborn}  Lv.{level}"
        draw.text((70, 126), level_text, font=self.fonts.font(24, weight="black"), fill=INK)
        player_name = str(player.get("name") or "UNKNOWN PLAYER")
        player_font = self.fonts.fit(draw, player_name, 525, 34, 22, weight="black")
        player_name = _ellipsize(draw, player_name, player_font, 525)
        draw.text((180, 116), player_name, font=player_font, fill=INK)

        draw.text((70, 181), "RATING", font=self.fonts.font(13, latin=True, weight="black"), fill=(18, 157, 174))
        draw.text((70, 194), f"{_as_float(player.get('rating')):.2f}", font=self.fonts.font(38, latin=True, weight="black"), fill=INK)

        emblem = player.get("class_emblem") or {}
        medal = _as_int(emblem.get("medal"))
        base = _as_int(emblem.get("base"))
        medal_image = self._ui_image(f"class-medal/{medal}.webp") if medal else None
        base_image = self._ui_image(f"class-base/{base}.webp") if base else None
        if base_image is not None:
            canvas.alpha_composite(_contain(base_image, (205, 40)), (292, 190))
        if medal_image is not None:
            canvas.alpha_composite(_contain(medal_image, (76, 62)), (292, 175))
        else:
            draw.ellipse((298, 181, 346, 229), fill=(72, 45, 134), outline=(247, 206, 51), width=4)
            draw.text((322, 205), self._class_mark(medal), font=self.fonts.font(19, latin=True, weight="black"), fill=WHITE, anchor="mm")
        draw.text((375, 180), "CLASS EMBLEM", font=self.fonts.font(10, latin=True, weight="semibold"), fill=MUTED)
        class_text_color = WHITE if base_image is not None else INK
        draw.text((375, 204), f"MEDAL {medal} / BASE {base}", font=self.fonts.font(12, latin=True, weight="black"), fill=class_text_color)

        draw.line((558, 178, 558, 230), fill=(39, 53, 69, 50), width=1)
        draw.text((580, 183), "OVER POWER", font=self.fonts.font(11, latin=True, weight="semibold"), fill=MUTED)
        draw.text((580, 202), f"{_as_float(player.get('over_power')):.2f}", font=self.fonts.font(20, latin=True, weight="black"), fill=INK)

        extras = []
        if show_friend_code and player.get("friend_code"):
            extras.append(f"FRIEND CODE {player['friend_code']}")
        if show_play_count and player.get("total_play_count") is not None:
            extras.append(f"PLAY COUNT {_as_int(player.get('total_play_count')):,}")
        if extras:
            draw.text((580, 234), " / ".join(extras), font=self.fonts.font(11, latin=True, weight="semibold"), fill=(58, 68, 84), anchor="lm")

        avatar_path = asset_paths.get("icon") or asset_paths.get("character")
        if avatar_path and avatar_path.exists():
            avatar = _cover(_open_rgba(avatar_path), (164, 164))
            canvas.paste(avatar, (844, 65), _rounded_mask((164, 164), 4))
        else:
            draw.rectangle((844, 65, 1008, 229), fill=(226, 233, 240, 255))
            draw.text((926, 147), "CHU", font=self.fonts.font(30, latin=True, weight="black"), fill=(117, 92, 154), anchor="mm")
        draw.rectangle((839, 60, 1013, 234), outline=(25, 35, 48, 235), width=3)
        draw.line((839, 60, 883, 60), fill=(24, 190, 203), width=6)
        draw.line((969, 234, 1013, 234), fill=(214, 70, 184), width=6)

        logo_path = self.ui_dir / "logo-2026.png"
        if logo_path.exists():
            logo_source = self._ui_image("logo-2026.png", remove_white=True)
            if logo_source is not None:
                logo = _contain(logo_source, (490, 192))
                canvas.alpha_composite(logo, (WIDTH - MARGIN - 500, 16))
        else:
            draw.text((WIDTH - MARGIN, 82), "中二节奏 2026", font=self.fonts.font(44, weight="black"), fill=(93, 54, 138), anchor="ra")

        banner = (1090, 210, WIDTH - MARGIN, 258)
        draw.polygon(((banner[0], banner[1]), (banner[2], banner[1]), (banner[2], banner[3]), (banner[0] + 28, banner[3])), fill=(24, 32, 45, 242))
        draw.rectangle((banner[0] + 28, banner[1], banner[0] + 39, banner[3]), fill=(27, 193, 205, 255))
        draw.text((banner[0] + 58, 234), "RATING COMPOSITION", font=self.fonts.font(17, latin=True, weight="black"), fill=WHITE, anchor="lm")
        draw.text((banner[2] - 18, 234), "B30 / S10 / N20", font=self.fonts.font(15, latin=True, weight="semibold"), fill=(91, 222, 228), anchor="rm")

    @staticmethod
    def _class_mark(medal: int) -> str:
        return {0: "-", 1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}.get(medal, str(medal))

    def _draw_section(self, canvas: Image.Image, y: int, title: str, rows: list[dict[str, Any]]) -> int:
        draw = ImageDraw.Draw(canvas, "RGBA")
        color = SECTION_STYLES.get(title, (90, 205, 217))
        average = sum(_as_float(row.get("rating")) for row in rows) / len(rows)
        section_height = self._section_height(len(rows))
        draw.rectangle((MARGIN - 10, y + 36, WIDTH - MARGIN + 10, y + section_height - 14), fill=(255, 255, 255, 126))
        draw.line((MARGIN, y + 24, WIDTH - MARGIN, y + 24), fill=(28, 37, 49, 140), width=2)
        section_number = {"BEST 30": "01", "SELECTION 10": "02", "NEW 20": "03"}.get(title, "--")
        draw.text((MARGIN, y + 18), section_number, font=self.fonts.font(25, latin=True, weight="black"), fill=INK, anchor="lm")
        tab_left = MARGIN + 58
        tab_right = tab_left + 300
        draw.polygon(((tab_left, y + 2), (tab_right, y + 2), (tab_right - 24, y + 45), (tab_left, y + 45)), fill=(*color, 255))
        title_color = INK if sum(color) > 570 else WHITE
        draw.text((tab_left + 20, y + 23), title, font=self.fonts.font(20, latin=True, weight="black"), fill=title_color, anchor="lm")
        draw.text((tab_right + 5, y + 18), "RATING ARCHIVE", font=self.fonts.font(10, latin=True, weight="semibold"), fill=MUTED, anchor="lm")
        draw.rectangle((WIDTH - MARGIN - 178, y + 3, WIDTH - MARGIN, y + 44), fill=(24, 32, 44, 245))
        draw.text((WIDTH - MARGIN - 18, y + 23), f"AVG  {average:.2f}", font=self.fonts.font(16, latin=True, weight="black"), fill=WHITE, anchor="rm")

        start_y = y + 60
        for index, score in enumerate(rows, start=1):
            row, column = divmod(index - 1, COLUMNS)
            x = MARGIN + column * (CARD_WIDTH + GAP_X)
            card_y = start_y + row * (CARD_HEIGHT + GAP_Y)
            canvas.alpha_composite(self._draw_card(score, index), (x, card_y))
        bracket_y = y + section_height - 23
        draw.line((MARGIN, bracket_y, MARGIN + 74, bracket_y), fill=(29, 40, 54, 105), width=2)
        draw.line((WIDTH - MARGIN - 74, bracket_y, WIDTH - MARGIN, bracket_y), fill=(29, 40, 54, 105), width=2)
        return y + section_height

    def _draw_card(self, score: dict[str, Any], index: int) -> Image.Image:
        difficulty = _as_int(score.get("level_index"), 3)
        style = DIFFICULTY_STYLES.get(difficulty, DIFFICULTY_STYLES[3])
        main = style["main"]
        dark = style["dark"]
        edge = style.get("edge", main)

        card = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(card, "RGBA")
        body = ((2, 2), (CARD_WIDTH - 2, 2), (CARD_WIDTH - 2, CARD_HEIGHT - 16), (CARD_WIDTH - 16, CARD_HEIGHT - 2), (2, CARD_HEIGHT - 2))
        shadow = tuple((x + 2, y + 2) for x, y in body)
        draw.polygon(shadow, fill=(17, 25, 36, 30))
        draw.polygon(body, fill=(253, 254, 255, 255), outline=(105, 116, 130, 90))

        info_x = JACKET_SIZE + 2
        draw.rectangle((info_x, 2, CARD_WIDTH - 2, 35), fill=(*main, 255))
        draw.rectangle((info_x, 35, CARD_WIDTH - 2, 39), fill=(*edge, 255))
        draw.polygon(((CARD_WIDTH - 47, 2), (CARD_WIDTH - 2, 2), (CARD_WIDTH - 2, 35), (CARD_WIDTH - 25, 35)), fill=(*dark, 248))

        if difficulty == 4:
            for offset in range(0, 50, 13):
                draw.polygon(((info_x + offset, 2), (info_x + offset + 7, 2), (info_x + offset - 7, 35), (info_x + offset - 14, 35)), fill=(245, 47, 67, 170))
        elif difficulty == 5:
            for offset in range(0, 56, 15):
                draw.line((info_x + offset, 3, info_x + offset - 14, 35), fill=(63, 213, 227, 210), width=4)

        jacket_path = score.get("jacket_path")
        if jacket_path and Path(jacket_path).exists():
            jacket = _cover(_open_rgba(Path(jacket_path)), (JACKET_SIZE, JACKET_SIZE))
        else:
            jacket = Image.new("RGBA", (JACKET_SIZE, JACKET_SIZE), (*dark, 255))
            placeholder_draw = ImageDraw.Draw(jacket)
            placeholder_draw.text((JACKET_SIZE // 2, JACKET_SIZE // 2), "NO\nJACKET", font=self.fonts.font(15, latin=True, weight="black"), fill=WHITE, anchor="mm", align="center")
        card.alpha_composite(jacket, (2, 2))
        draw.rectangle((2, 2, JACKET_SIZE + 1, JACKET_SIZE + 1), outline=(25, 33, 45, 170), width=2)
        draw.rectangle((JACKET_SIZE - 3, 2, JACKET_SIZE + 2, JACKET_SIZE + 1), fill=(*edge, 255))

        title = str(score.get("song_name") or f"ID {score.get('id', '-')}")
        title_left = info_x + 10
        title_width = CARD_WIDTH - title_left - 42
        title_font = self.fonts.fit(draw, title, title_width, 16, 10, weight="black")
        title = _ellipsize(draw, title, title_font, title_width)
        draw.text((title_left, 8), title, font=title_font, fill=WHITE)
        draw.text((CARD_WIDTH - 8, 9), f"#{index}", font=self.fonts.font(12, latin=True, weight="black"), fill=WHITE, anchor="ra")

        score_text = f"{_as_int(score.get('score')):,}"
        score_font = self.fonts.fit(draw, score_text, CARD_WIDTH - info_x - 16, 29, 23, latin=True, weight="black")
        draw.text((title_left, 42), score_text, font=score_font, fill=INK)

        level_value = score.get("level_value")
        constant = f"{_as_float(level_value):.1f}" if level_value is not None else "-"
        draw.text((title_left, 78), "定数", font=self.fonts.font(10, weight="semibold"), fill=MUTED)
        draw.text((title_left + 31, 76), constant, font=self.fonts.font(13, latin=True, weight="black"), fill=INK)
        draw.line((title_left + 79, 77, title_left + 79, 94), fill=(31, 43, 56, 45), width=1)
        draw.text((title_left + 91, 78), "Ra", font=self.fonts.font(10, latin=True, weight="semibold"), fill=MUTED)
        draw.text((title_left + 111, 76), f"{_as_float(score.get('rating')):.2f}", font=self.fonts.font(13, latin=True, weight="black"), fill=INK)

        badge_y = 104
        self._draw_result_badge(card, score, title_left, badge_y)
        self._draw_rank_badge(card, str(score.get("rank") or "").lower(), title_left + BADGE_WIDTH + 5, badge_y)
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
                badge = badge_source.resize((BADGE_WIDTH, BADGE_HEIGHT), Image.Resampling.LANCZOS)
                card.alpha_composite(badge, (x, y))
                return
        self._paste_badge_or_text(card, None, RANK_LABELS.get(rank, rank.upper() or "-"), x, y, kind="rank")

    def _paste_badge_or_text(self, card: Image.Image, asset_name: str | None, label: str, x: int, y: int, *, kind: str) -> None:
        asset = self.ui_dir / asset_name if asset_name else None
        if asset and asset.exists():
            badge_source = self._ui_image(asset.name)
            if badge_source is not None:
                badge = badge_source.resize((BADGE_WIDTH, BADGE_HEIGHT), Image.Resampling.LANCZOS)
                card.alpha_composite(badge, (x, y))
                return
        draw = ImageDraw.Draw(card, "RGBA")
        if kind == "rank":
            fill, outline, text_color = (229, 244, 255, 255), (75, 172, 222, 255), (28, 87, 128)
        else:
            fill, outline, text_color = (255, 222, 59, 255), (220, 152, 15, 255), (79, 56, 4)
        draw.rectangle((x, y, x + BADGE_WIDTH - 1, y + BADGE_HEIGHT - 1), fill=fill, outline=outline, width=1)
        draw.text(
            (x + BADGE_WIDTH // 2, y + BADGE_HEIGHT // 2),
            label,
            font=self.fonts.fit(draw, label, BADGE_WIDTH - 6, 10, 7, weight="black"),
            fill=text_color,
            anchor="mm",
        )

    def _draw_footer(self, canvas: Image.Image, height: int, footer_bot_name: str) -> None:
        draw = ImageDraw.Draw(canvas, "RGBA")
        footer_y = height - 34
        draw.line((MARGIN, footer_y - 20, WIDTH - MARGIN, footer_y - 20), fill=(28, 39, 53, 125), width=2)
        draw.rectangle((MARGIN, footer_y - 25, MARGIN + 62, footer_y - 17), fill=(27, 193, 205, 255))
        draw.rectangle((MARGIN + 62, footer_y - 25, MARGIN + 99, footer_y - 17), fill=(237, 202, 56, 255))
        draw.text((MARGIN, footer_y), datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"), font=self.fonts.font(13, latin=True, weight="semibold"), fill=(63, 78, 99), anchor="lm")
        draw.text(
            (WIDTH - MARGIN, footer_y),
            f"Powered By maimai.lxns.net / Generated By {footer_bot_name}",
            font=self.fonts.font(13, latin=True, weight="semibold"),
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
