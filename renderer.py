from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

WIDTH = 2000
MARGIN = 48
COLUMNS = 5
GAP_X = 18
GAP_Y = 20
CARD_WIDTH = (WIDTH - MARGIN * 2 - GAP_X * (COLUMNS - 1)) // COLUMNS
CARD_HEIGHT = 164
JACKET_SIZE = 148
BADGE_WIDTH = 82
BADGE_HEIGHT = 22
HELP_WIDTH = 1200
HELP_HEIGHT = 1500
GAME_LABEL = "CHUNITHM 2027"
GAME_EDITION = "中二节奏 2027"
LOGO_FILE = "branding-2027.png"
# Use the Chinese logo region of the unmodified official announcement artwork.
LOGO_CROP = (1760, 2470, 2450, 2855)
VIOLET = (105, 58, 216)
LIME = (208, 245, 103)

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
    "BEST 30": (208, 245, 103),
    "SELECTION 10": (164, 229, 240),
    "NEW 20": (194, 166, 255),
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

HELP_ACCOUNT_COMMANDS = (
    ("/chu bind <好友码>", "绑定自己的玩家账号"),
    ("/chu unbind", "解除当前账号绑定"),
    ("/chu me [好友码]", "查看玩家资料"),
    ("/chu b30 [好友码]", "生成 Rating 构成图片"),
    ("/chu recent [数量] [好友码]", "查询 Recent 记录"),
    ("/chu score <曲名或ID> [难度] [好友码]", "查询单曲成绩"),
    ("/chu stats [好友码]", "查看分组统计与达成情况"),
    ("/chu targets [好友码]", "查看最接近的下一评级目标"),
)

HELP_SONG_COMMANDS = (
    ("/chu song <曲名/别名/ID>", "查询歌曲与谱面详情"),
    ("/chu alias <曲名/ID>", "查询歌曲别名"),
    ("/chu random [等级] [难度]", "随机选择符合条件的谱面"),
    ("/chu jacket <曲名/ID>", "发送本地曲绘"),
)

HELP_ADMIN_COMMANDS = (
    ("/chu update", "刷新本地曲库缓存"),
    ("/chu assets status", "查看本地素材库状态"),
    ("/chu assets update <类型>", "管理员主动更新公共素材"),
)

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
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255
    )
    return mask


def _cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(
        image.convert("RGBA"),
        size,
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )


def _contain(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    image = image.convert("RGBA")
    image.thumbnail(size, Image.Resampling.LANCZOS)
    target = Image.new("RGBA", size, (0, 0, 0, 0))
    target.alpha_composite(
        image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2)
    )
    return target


def _open_rgba(path: Path) -> Image.Image:
    with Image.open(path) as source:
        return source.convert("RGBA").copy()


def _ellipsize(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> str:
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
        return (
            red >= 255 - tolerance
            and green >= 255 - tolerance
            and blue >= 255 - tolerance
        )

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
            if (
                0 <= next_x < width
                and 0 <= next_y < height
                and point not in seen
                and near_white(next_x, next_y)
            ):
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
    def font(
        self, size: int, *, latin: bool = False, weight: str = "bold"
    ) -> ImageFont.FreeTypeFont:
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
        self.background_path = (
            background_path if background_path and background_path.exists() else None
        )
        self._image_cache: dict[str, Image.Image] = {}

    def _ui_image(self, name: str, *, remove_white: bool = False) -> Image.Image | None:
        key = f"{name}:{remove_white}"
        if key not in self._image_cache:
            path = self.ui_dir / name
            if not path.exists():
                return None
            with Image.open(path) as source:
                image = source.convert("RGBA")
            if name == LOGO_FILE:
                image = image.crop(LOGO_CROP)
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
        height = (
            446
            + sum(self._section_height(len(rows)) for _, rows in visible_sections)
            + 92
        )
        canvas = self._build_background(height)
        self._draw_player_header(
            canvas,
            player,
            asset_paths,
            show_friend_code=show_friend_code,
            show_play_count=show_play_count,
        )

        self._draw_summary(canvas, visible_sections)
        y = 430
        for title, rows in visible_sections:
            y = self._draw_section(canvas, y, title, rows)

        self._draw_footer(canvas, height, footer_bot_name)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(
            output_path,
            "JPEG",
            quality=95,
            subsampling=0,
            optimize=True,
            progressive=True,
        )
        return output_path

    @staticmethod
    def _section_height(row_count: int) -> int:
        lines = math.ceil(row_count / COLUMNS)
        cards_height = lines * CARD_HEIGHT + max(0, lines - 1) * GAP_Y
        return 60 + cards_height + 34

    def _build_background(self, height: int) -> Image.Image:
        canvas = Image.new("RGBA", (WIDTH, height), (241, 240, 248, 255))
        draw = ImageDraw.Draw(canvas, "RGBA")
        draw.rectangle((0, 0, WIDTH, 286), fill=(252, 253, 254, 255))
        draw.rectangle((0, 0, 520, 8), fill=LIME)
        draw.rectangle((520, 0, 1130, 8), fill=VIOLET)
        draw.rectangle((1130, 0, WIDTH, 8), fill=(194, 166, 255, 255))

        if self.background_path:
            background_key = f"background:{self.background_path}"
            if background_key not in self._image_cache:
                with Image.open(self.background_path) as background:
                    self._image_cache[background_key] = background.convert("RGBA")
            source = _cover(self._image_cache[background_key], (WIDTH, 286))
            canvas.alpha_composite(source, (0, 0))
            draw.rectangle((0, 0, WIDTH, 286), fill=(250, 252, 254, 184))

        for x in range(0, WIDTH + 1, 92):
            draw.line((x, 286, x, height), fill=(225, 224, 237, 255), width=1)
        for y in range(286, height, 92):
            draw.line((0, y, WIDTH, y), fill=(225, 224, 237, 255), width=1)
        for offset in range(-height, WIDTH + height, 250):
            draw.line(
                (offset, 286, offset + height, height),
                fill=(247, 246, 251, 255),
                width=2,
            )

        draw.polygon(((0, 286), (345, 286), (0, 520)), fill=(227, 215, 251, 255))
        draw.polygon(
            ((WIDTH, 286), (WIDTH - 230, 286), (WIDTH, 515)), fill=(229, 243, 202, 255)
        )
        draw.line((22, 310, 22, height - 72), fill=VIOLET, width=3)
        draw.line(
            (WIDTH - 23, 310, WIDTH - 23, height - 72), fill=(177, 199, 127), width=3
        )

        for row in range(4):
            for column in range(12):
                x = 1080 + column * 22 + row * 7
                y = 26 + row * 22
                draw.ellipse((x, y, x + 5, y + 5), fill=(27, 35, 48, 60))
        draw.line((0, 286, WIDTH, 286), fill=(220, 216, 233, 255), width=1)
        return canvas

    def _draw_summary(
        self, canvas: Image.Image, sections: list[tuple[str, list[dict[str, Any]]]]
    ) -> None:
        """Draw statistics for visible, unique charts without estimating player rating.

        Args:
            canvas: Output canvas.
            sections: Visible API groups, after display limits have been applied.
        """
        draw = ImageDraw.Draw(canvas)
        scores = {
            (row.get("id"), row.get("level_index")): row
            for _, rows in sections
            for row in rows
        }
        rows = list(scores.values())
        ajc = sum(row.get("full_combo") == "alljusticecritical" for row in rows)
        aj = sum(
            row.get("full_combo") in {"alljustice", "alljusticecritical"}
            for row in rows
        )
        sssp = sum(str(row.get("rank") or "").lower() == "sssp" for row in rows)
        metrics = (
            ("DISPLAYED / 展示谱面", str(len(rows))),
            ("SSS+ / 达成", str(sssp)),
            ("AJ / 含 AJC", str(aj)),
            ("AJC / 达成", str(ajc)),
        )
        draw.rounded_rectangle(
            (MARGIN, 310, WIDTH - MARGIN, 404), radius=12, fill=(30, 25, 48)
        )
        cell_width = (WIDTH - MARGIN * 2) // len(metrics)
        for index, (label, value) in enumerate(metrics):
            x = MARGIN + index * cell_width
            if index:
                draw.line((x, 330, x, 384), fill=(67, 59, 84))
            draw.text(
                (x + 26, 326),
                label,
                font=self.fonts.font(13, weight="medium"),
                fill=(199, 192, 218),
            )
            draw.text(
                (x + 26, 346),
                value,
                font=self.fonts.font(33, latin=True, weight="black"),
                fill=LIME if index == 0 else WHITE,
            )

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
        draw.rounded_rectangle(
            (MARGIN + 5, 35, 1055, 263), radius=9, fill=(225, 221, 234, 255)
        )
        plate_path = asset_paths.get("plate")
        if plate_path and plate_path.exists():
            panel_size = (panel[2] - panel[0], panel[3] - panel[1])
            plate = _cover(_open_rgba(plate_path), panel_size)
            plate = ImageEnhance.Brightness(plate).enhance(1.12)
            plate = Image.alpha_composite(
                plate, Image.new("RGBA", panel_size, (255, 255, 255, 198))
            )
            canvas.paste(
                plate,
                (panel[0], panel[1]),
                _rounded_mask((panel[2] - panel[0], panel[3] - panel[1]), 8),
            )
        else:
            draw.rounded_rectangle(panel, radius=8, fill=(255, 255, 255, 248))
        draw.rounded_rectangle(panel, radius=8, outline=(206, 201, 218, 255), width=1)
        draw.rectangle((MARGIN, 30, MARGIN + 9, 258), fill=VIOLET)
        draw.rectangle((MARGIN + 9, 30, MARGIN + 15, 258), fill=LIME)
        draw.text(
            (72, 44),
            f"PLAYER PROFILE / {GAME_LABEL}",
            font=self.fonts.font(12, latin=True, weight="semibold"),
            fill=MUTED,
        )

        trophy = player.get("trophy") or {}
        trophy_color = str(trophy.get("color") or "normal").lower()
        trophy_image = asset_paths.get("trophy")
        if trophy_color == "image" and trophy_image and trophy_image.exists():
            banner = _contain(_open_rgba(trophy_image), (690, 42))
            canvas.alpha_composite(banner, (66, 62))
        else:
            fill, text_color = TROPHY_COLORS.get(trophy_color, TROPHY_COLORS["normal"])
            draw.rounded_rectangle(
                (68, 65, 758, 104),
                radius=4,
                fill=(*fill, 238),
                outline=(42, 54, 68, 62),
                width=1,
            )
            trophy_name = str(trophy.get("name") or "NO TITLE")
            draw.text(
                (413, 84),
                trophy_name,
                font=self.fonts.fit(draw, trophy_name, 640, 19, 12, weight="bold"),
                fill=text_color,
                anchor="mm",
            )

        level = _as_int(player.get("level"))
        reborn = _as_int(player.get("reborn_count"))
        level_text = f"Lv.{level}" if not reborn else f"Re:{reborn}  Lv.{level}"
        draw.text(
            (70, 126), level_text, font=self.fonts.font(24, weight="black"), fill=INK
        )
        player_name = str(player.get("name") or "UNKNOWN PLAYER")
        player_font = self.fonts.fit(draw, player_name, 525, 34, 22, weight="black")
        player_name = _ellipsize(draw, player_name, player_font, 525)
        draw.text((180, 116), player_name, font=player_font, fill=INK)

        draw.text(
            (70, 181),
            "RATING",
            font=self.fonts.font(13, latin=True, weight="black"),
            fill=VIOLET,
        )
        rating = (
            f"{_as_float(player['rating']):.2f}"
            if player.get("rating") is not None
            else "--"
        )
        draw.text(
            (70, 194),
            rating,
            font=self.fonts.font(38, latin=True, weight="black"),
            fill=INK,
        )

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
            draw.ellipse(
                (298, 181, 346, 229),
                fill=(72, 45, 134),
                outline=(247, 206, 51),
                width=4,
            )
            draw.text(
                (322, 205),
                self._class_mark(medal),
                font=self.fonts.font(19, latin=True, weight="black"),
                fill=WHITE,
                anchor="mm",
            )
        draw.text(
            (375, 180),
            "CLASS EMBLEM",
            font=self.fonts.font(10, latin=True, weight="semibold"),
            fill=MUTED,
        )
        draw.text(
            (375, 204),
            f"CLASS {self._class_mark(medal)}",
            font=self.fonts.font(14, latin=True, weight="black"),
            fill=WHITE if base_image is not None else INK,
        )

        draw.line((558, 178, 558, 230), fill=(39, 53, 69, 50), width=1)
        draw.text(
            (580, 183),
            "OVER POWER",
            font=self.fonts.font(11, latin=True, weight="semibold"),
            fill=MUTED,
        )
        draw.text(
            (580, 202),
            f"{_as_float(player.get('over_power')):.2f}",
            font=self.fonts.font(20, latin=True, weight="black"),
            fill=INK,
        )

        extras = []
        if show_friend_code and player.get("friend_code"):
            extras.append(f"FRIEND CODE {player['friend_code']}")
        if show_play_count and player.get("total_play_count") is not None:
            extras.append(f"PLAY COUNT {_as_int(player.get('total_play_count')):,}")
        if extras:
            draw.text(
                (70, 246),
                " / ".join(extras),
                font=self.fonts.font(11, latin=True, weight="semibold"),
                fill=(58, 68, 84),
                anchor="lm",
            )

        avatar_path = asset_paths.get("icon") or asset_paths.get("character")
        if avatar_path and avatar_path.exists():
            avatar = _cover(_open_rgba(avatar_path), (164, 164))
            canvas.paste(avatar, (844, 65), _rounded_mask((164, 164), 4))
        else:
            draw.rectangle((844, 65, 1008, 229), fill=(226, 233, 240, 255))
            draw.text(
                (926, 147),
                "CHU",
                font=self.fonts.font(30, latin=True, weight="black"),
                fill=(117, 92, 154),
                anchor="mm",
            )
        draw.rectangle((839, 60, 1013, 234), outline=(25, 35, 48, 235), width=3)
        draw.line((839, 60, 883, 60), fill=VIOLET, width=6)
        draw.line((969, 234, 1013, 234), fill=LIME, width=6)

        logo_path = self.ui_dir / LOGO_FILE
        if logo_path.exists():
            logo_source = self._ui_image(LOGO_FILE)
            if logo_source is not None:
                logo = _contain(logo_source, (690, 188))
                canvas.alpha_composite(logo, (WIDTH - MARGIN - 750, 12))
        else:
            draw.text(
                (WIDTH - MARGIN - 70, 82),
                GAME_EDITION,
                font=self.fonts.font(54, weight="black"),
                fill=VIOLET,
                anchor="ra",
            )

        banner = (1090, 210, WIDTH - MARGIN, 258)
        draw.polygon(
            (
                (banner[0], banner[1]),
                (banner[2], banner[1]),
                (banner[2], banner[3]),
                (banner[0] + 28, banner[3]),
            ),
            fill=(24, 32, 45, 242),
        )
        draw.rectangle(
            (banner[0] + 28, banner[1], banner[0] + 39, banner[3]), fill=LIME
        )
        draw.text(
            (banner[0] + 58, 234),
            "中二节奏 2027 / RATING COMPOSITION",
            font=self.fonts.font(19, weight="black"),
            fill=WHITE,
            anchor="lm",
        )
        draw.text(
            (banner[2] - 18, 234),
            "B30 / S10 / N20",
            font=self.fonts.font(16, latin=True, weight="semibold"),
            fill=LIME,
            anchor="rm",
        )

    @staticmethod
    def _class_mark(medal: int) -> str:
        return {0: "-", 1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}.get(
            medal, str(medal)
        )

    def _draw_section(
        self, canvas: Image.Image, y: int, title: str, rows: list[dict[str, Any]]
    ) -> int:
        draw = ImageDraw.Draw(canvas, "RGBA")
        section_key = next(
            (key for key in SECTION_STYLES if title.startswith(key)), title
        )
        color = SECTION_STYLES.get(section_key, (90, 205, 217))
        average = sum(_as_float(row.get("rating")) for row in rows) / len(rows)
        section_height = self._section_height(len(rows))
        draw.rectangle(
            (MARGIN - 10, y + 36, WIDTH - MARGIN + 10, y + section_height - 14),
            fill=(255, 255, 255, 126),
        )
        draw.line(
            (MARGIN, y + 49, WIDTH - MARGIN, y + 49), fill=(212, 207, 226, 255), width=1
        )
        section_number = {"BEST 30": "01", "SELECTION 10": "02", "NEW 20": "03"}.get(
            section_key, "--"
        )
        draw.text(
            (MARGIN, y + 18),
            section_number,
            font=self.fonts.font(25, latin=True, weight="black"),
            fill=INK,
            anchor="lm",
        )
        tab_left = MARGIN + 58
        tab_right = tab_left + 300
        draw.polygon(
            (
                (tab_left, y + 2),
                (tab_right, y + 2),
                (tab_right - 24, y + 45),
                (tab_left, y + 45),
            ),
            fill=(*color, 255),
        )
        title_color = INK
        draw.text(
            (tab_left + 20, y + 23),
            title,
            font=self.fonts.font(20, latin=True, weight="black"),
            fill=title_color,
            anchor="lm",
        )
        ratings = [_as_float(row.get("rating")) for row in rows]
        if section_key == "NEW 20":
            detail = f"{len(rows):02d} PLAYED   /   RANGE {min(ratings):.2f} — {max(ratings):.2f}"
        else:
            detail = f"{len(rows):02d} CHARTS   /   RANGE {min(ratings):.2f} — {max(ratings):.2f}"
        draw.text(
            (tab_right + 28, y + 21),
            detail,
            font=self.fonts.font(14, latin=True, weight="semibold"),
            fill=MUTED,
            anchor="lm",
        )
        draw.rectangle(
            (WIDTH - MARGIN - 178, y + 3, WIDTH - MARGIN, y + 44),
            fill=(24, 32, 44, 245),
        )
        draw.text(
            (WIDTH - MARGIN - 18, y + 23),
            f"AVG  {average:.2f}",
            font=self.fonts.font(16, latin=True, weight="black"),
            fill=WHITE,
            anchor="rm",
        )

        start_y = y + 60
        for index, score in enumerate(rows, start=1):
            row, column = divmod(index - 1, COLUMNS)
            x = MARGIN + column * (CARD_WIDTH + GAP_X)
            card_y = start_y + row * (CARD_HEIGHT + GAP_Y)
            canvas.alpha_composite(self._draw_card(score, index), (x, card_y))
        bracket_y = y + section_height - 23
        draw.line(
            (MARGIN, bracket_y, MARGIN + 74, bracket_y), fill=(29, 40, 54, 105), width=2
        )
        draw.line(
            (WIDTH - MARGIN - 74, bracket_y, WIDTH - MARGIN, bracket_y),
            fill=(29, 40, 54, 105),
            width=2,
        )
        return y + section_height

    def _draw_card(self, score: dict[str, Any], index: int) -> Image.Image:
        difficulty = _as_int(score.get("level_index"), 3)
        style = DIFFICULTY_STYLES.get(difficulty, DIFFICULTY_STYLES[3])
        main = style["main"]
        dark = style["dark"]
        edge = style.get("edge", main)

        card = Image.new("RGBA", (CARD_WIDTH, CARD_HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(card, "RGBA")
        body = (
            (2, 2),
            (CARD_WIDTH - 2, 2),
            (CARD_WIDTH - 2, CARD_HEIGHT - 16),
            (CARD_WIDTH - 16, CARD_HEIGHT - 2),
            (2, CARD_HEIGHT - 2),
        )
        shadow = tuple((x + 2, y + 2) for x, y in body)
        draw.polygon(shadow, fill=(219, 215, 230, 255))
        draw.polygon(body, fill=(253, 254, 255, 255), outline=(105, 116, 130, 90))

        info_x = JACKET_SIZE + 2
        draw.rectangle((info_x, 2, CARD_WIDTH - 2, 40), fill=(*main, 255))
        draw.rectangle((info_x, 40, CARD_WIDTH - 2, 43), fill=(*edge, 255))
        draw.polygon(
            (
                (CARD_WIDTH - 47, 2),
                (CARD_WIDTH - 2, 2),
                (CARD_WIDTH - 2, 35),
                (CARD_WIDTH - 25, 35),
            ),
            fill=(*dark, 248),
        )

        if difficulty == 4:
            for offset in range(0, 50, 13):
                draw.polygon(
                    (
                        (info_x + offset, 2),
                        (info_x + offset + 7, 2),
                        (info_x + offset + 2, 8),
                        (info_x + offset - 5, 8),
                    ),
                    fill=(245, 47, 67, 170),
                )
        elif difficulty == 5:
            for offset in range(0, 56, 15):
                draw.line(
                    (info_x + offset, 3, info_x + offset - 4, 8),
                    fill=(63, 213, 227, 210),
                    width=4,
                )

        jacket_path = score.get("jacket_path")
        if jacket_path and Path(jacket_path).exists():
            jacket = _cover(_open_rgba(Path(jacket_path)), (JACKET_SIZE, JACKET_SIZE))
        else:
            jacket = Image.new("RGBA", (JACKET_SIZE, JACKET_SIZE), (*dark, 255))
            placeholder_draw = ImageDraw.Draw(jacket)
            placeholder_draw.text(
                (JACKET_SIZE // 2, JACKET_SIZE // 2),
                "NO\nJACKET",
                font=self.fonts.font(15, latin=True, weight="black"),
                fill=WHITE,
                anchor="mm",
                align="center",
            )
        card.alpha_composite(jacket, (2, 2))
        draw.rectangle(
            (2, 2, JACKET_SIZE + 1, JACKET_SIZE + 1), outline=(25, 33, 45, 170), width=2
        )
        draw.rectangle(
            (JACKET_SIZE - 3, 2, JACKET_SIZE + 2, JACKET_SIZE + 1), fill=(*edge, 255)
        )

        title = str(score.get("song_name") or f"ID {score.get('id', '-')}")
        title_left = info_x + 10
        title_width = CARD_WIDTH - title_left - 42
        title_font = self.fonts.fit(draw, title, title_width, 18, 13, weight="black")
        title = _ellipsize(draw, title, title_font, title_width)
        draw.text(
            (title_left, 21),
            title,
            font=title_font,
            fill=INK if difficulty == 1 else WHITE,
            anchor="lm",
        )
        draw.text(
            (CARD_WIDTH - 8, 9),
            f"#{index}",
            font=self.fonts.font(12, latin=True, weight="black"),
            fill=WHITE,
            anchor="ra",
        )

        score_text = f"{_as_int(score.get('score')):,}"
        score_font = self.fonts.fit(
            draw,
            score_text,
            CARD_WIDTH - info_x - 16,
            33,
            25,
            latin=True,
            weight="black",
        )
        draw.text((title_left, 47), score_text, font=score_font, fill=INK)

        level_value = score.get("level_value")
        constant = f"{_as_float(level_value):.1f}" if level_value is not None else "-"
        draw.text(
            (title_left, 97),
            "定数",
            font=self.fonts.font(12, weight="semibold"),
            fill=MUTED,
        )
        draw.text(
            (title_left + 34, 93),
            constant,
            font=self.fonts.font(17, latin=True, weight="black"),
            fill=INK,
        )
        draw.line(
            (title_left + 88, 96, title_left + 88, 116), fill=(211, 211, 223), width=1
        )
        draw.text(
            (title_left + 100, 97),
            "Ra",
            font=self.fonts.font(12, latin=True, weight="semibold"),
            fill=MUTED,
        )
        draw.text(
            (title_left + 122, 93),
            f"{_as_float(score.get('rating')):.2f}",
            font=self.fonts.font(17, latin=True, weight="black"),
            fill=VIOLET,
        )

        badge_y = 128
        self._draw_result_badge(card, score, title_left, badge_y)
        self._draw_rank_badge(
            card,
            str(score.get("rank") or "").lower(),
            title_left + BADGE_WIDTH + 5,
            badge_y,
        )
        return card

    def _draw_result_badge(
        self, card: Image.Image, score: dict[str, Any], x: int, y: int
    ) -> None:
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
            COMBO_LABELS.get(combo)
            or CHAIN_LABELS.get(chain)
            or CLEAR_LABELS.get(clear)
            or "NO PLAY",
            x,
            y,
            kind="result",
        )

    def _draw_rank_badge(self, card: Image.Image, rank: str, x: int, y: int) -> None:
        rank_asset = self.ui_dir / f"rank-{rank}.webp"
        if rank_asset.exists():
            badge_source = self._ui_image(rank_asset.name)
            if badge_source is not None:
                badge = _contain(badge_source, (BADGE_WIDTH, BADGE_HEIGHT))
                card.alpha_composite(badge, (x, y))
                return
        self._paste_badge_or_text(
            card, None, RANK_LABELS.get(rank, rank.upper() or "-"), x, y, kind="rank"
        )

    def _paste_badge_or_text(
        self,
        card: Image.Image,
        asset_name: str | None,
        label: str,
        x: int,
        y: int,
        *,
        kind: str,
    ) -> None:
        asset = self.ui_dir / asset_name if asset_name else None
        if asset and asset.exists():
            badge_source = self._ui_image(asset.name)
            if badge_source is not None:
                badge = badge_source.resize(
                    (BADGE_WIDTH, BADGE_HEIGHT), Image.Resampling.LANCZOS
                )
                card.alpha_composite(badge, (x, y))
                return
        draw = ImageDraw.Draw(card, "RGBA")
        if kind == "rank":
            fill, outline, text_color = (
                (229, 244, 255, 255),
                (75, 172, 222, 255),
                (28, 87, 128),
            )
        else:
            fill, outline, text_color = (
                (255, 222, 59, 255),
                (220, 152, 15, 255),
                (79, 56, 4),
            )
        draw.rectangle(
            (x, y, x + BADGE_WIDTH - 1, y + BADGE_HEIGHT - 1),
            fill=fill,
            outline=outline,
            width=1,
        )
        draw.text(
            (x + BADGE_WIDTH // 2, y + BADGE_HEIGHT // 2),
            label,
            font=self.fonts.fit(draw, label, BADGE_WIDTH - 6, 10, 7, weight="black"),
            fill=text_color,
            anchor="mm",
        )

    def _draw_footer(
        self, canvas: Image.Image, height: int, footer_bot_name: str
    ) -> None:
        draw = ImageDraw.Draw(canvas, "RGBA")
        footer_y = height - 34
        draw.line(
            (MARGIN, footer_y - 20, WIDTH - MARGIN, footer_y - 20),
            fill=(28, 39, 53, 125),
            width=2,
        )
        draw.rectangle(
            (MARGIN, footer_y - 25, MARGIN + 62, footer_y - 17),
            fill=VIOLET,
        )
        draw.rectangle(
            (MARGIN + 62, footer_y - 25, MARGIN + 99, footer_y - 17),
            fill=LIME,
        )
        draw.text(
            (MARGIN, footer_y),
            datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            font=self.fonts.font(13, latin=True, weight="semibold"),
            fill=(63, 78, 99),
            anchor="lm",
        )
        draw.text(
            (WIDTH - MARGIN, footer_y),
            f"Powered By maimai.lxns.net / Generated By {footer_bot_name}",
            font=self.fonts.font(13, latin=True, weight="semibold"),
            fill=(63, 78, 99),
            anchor="rm",
        )


class ChunithmHelpRenderer:
    def __init__(self, static_dir: Path):
        self.static_dir = static_dir
        self.ui_dir = static_dir / "ui"
        self.fonts = FontBook(static_dir)

    def render(self, output_path: Path, *, footer_bot_name: str = "EmuBot") -> Path:
        canvas = Image.new("RGBA", (HELP_WIDTH, HELP_HEIGHT), (246, 249, 252, 255))
        draw = ImageDraw.Draw(canvas, "RGBA")
        self._draw_background(draw)
        self._draw_header(canvas)

        draw.rounded_rectangle(
            (52, 278, HELP_WIDTH - 52, 356), radius=7, fill=(18, 26, 39, 250)
        )
        draw.text(
            (78, 317),
            "QUICK START",
            font=self.fonts.font(16, latin=True, weight="black"),
            fill=(93, 224, 231),
            anchor="lm",
        )
        draw.line((242, 296, 242, 338), fill=(255, 255, 255, 52), width=2)
        draw.text(
            (272, 317),
            "/chu bind <好友码>",
            font=self.fonts.font(25, weight="black"),
            fill=WHITE,
            anchor="lm",
        )
        draw.text(
            (592, 317),
            ">",
            font=self.fonts.font(25, latin=True, weight="black"),
            fill=(250, 203, 48),
            anchor="mm",
        )
        draw.text(
            (625, 317),
            "/chu b30",
            font=self.fonts.font(25, latin=True, weight="black"),
            fill=WHITE,
            anchor="lm",
        )
        draw.text(
            (HELP_WIDTH - 78, 317),
            "首次使用先绑定",
            font=self.fonts.font(19, weight="semibold"),
            fill=(194, 204, 217),
            anchor="rm",
        )

        self._draw_section(
            canvas,
            52,
            390,
            536,
            "01",
            "账号与成绩",
            VIOLET,
            HELP_ACCOUNT_COMMANDS,
            row_height=74,
        )
        song_bottom = self._draw_section(
            canvas,
            612,
            390,
            536,
            "02",
            "曲库与玩法",
            (164, 135, 227),
            HELP_SONG_COMMANDS,
            row_height=82,
        )
        self._draw_section(
            canvas,
            612,
            song_bottom + 22,
            536,
            "03",
            "本地资源",
            (143, 173, 64),
            HELP_ADMIN_COMMANDS,
            row_height=68,
        )

        self._draw_difficulty_strip(canvas, 52, 1124)
        self._draw_notes(canvas, 52, 1232)
        self._draw_footer(canvas, footer_bot_name)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(output_path, "PNG", optimize=True)
        return output_path

    @staticmethod
    def _draw_background(draw: ImageDraw.ImageDraw) -> None:
        draw.rectangle((0, 0, HELP_WIDTH, 246), fill=(255, 255, 255, 255))
        draw.rectangle((0, 0, 380, 8), fill=LIME)
        draw.rectangle((380, 0, 805, 8), fill=VIOLET)
        draw.rectangle((805, 0, HELP_WIDTH, 8), fill=(194, 166, 255))
        for x in range(0, HELP_WIDTH + 1, 86):
            draw.line((x, 246, x, HELP_HEIGHT), fill=(228, 226, 239, 255), width=1)
        for y in range(246, HELP_HEIGHT, 86):
            draw.line((0, y, HELP_WIDTH, y), fill=(228, 226, 239, 255), width=1)
        draw.polygon(((0, 246), (252, 246), (0, 430)), fill=(231, 223, 250, 255))
        draw.polygon(
            ((HELP_WIDTH, 246), (1025, 246), (HELP_WIDTH, 430)),
            fill=(232, 244, 211, 255),
        )
        draw.line((22, 375, 22, HELP_HEIGHT - 68), fill=VIOLET, width=3)
        draw.line(
            (HELP_WIDTH - 23, 375, HELP_WIDTH - 23, HELP_HEIGHT - 68),
            fill=(177, 199, 127),
            width=3,
        )
        for row in range(4):
            for column in range(10):
                x = 835 + column * 21 + row * 7
                y = 22 + row * 21
                draw.ellipse((x, y, x + 5, y + 5), fill=(228, 223, 241, 255))

    def _draw_header(self, canvas: Image.Image) -> None:
        draw = ImageDraw.Draw(canvas, "RGBA")
        draw.text(
            (52, 45),
            f"{GAME_LABEL} / {GAME_EDITION}",
            font=self.fonts.font(16, latin=True, weight="black"),
            fill=VIOLET,
        )
        draw.text(
            (50, 82), "中二节奏查询", font=self.fonts.font(51, weight="black"), fill=INK
        )
        draw.text(
            (52, 160),
            "/chu 指令菜单",
            font=self.fonts.font(48, weight="black"),
            fill=(58, 39, 129),
        )
        draw.text(
            (53, 220),
            "查询、成绩、本地曲库与素材管理",
            font=self.fonts.font(20, weight="medium"),
            fill=MUTED,
        )

        logo_path = self.ui_dir / LOGO_FILE
        if logo_path.exists():
            logo = _open_rgba(logo_path).crop(LOGO_CROP)
            canvas.alpha_composite(_contain(logo, (345, 160)), (HELP_WIDTH - 393, 28))
        else:
            draw.text(
                (HELP_WIDTH - 52, 112),
                GAME_LABEL,
                font=self.fonts.font(31, latin=True, weight="black"),
                fill=VIOLET,
                anchor="rm",
            )
        draw.polygon(
            ((783, 198), (HELP_WIDTH - 52, 198), (HELP_WIDTH - 52, 238), (813, 238)),
            fill=(18, 27, 40, 245),
        )
        draw.rectangle((813, 198, 824, 238), fill=LIME)
        draw.text(
            (844, 218),
            "COMMAND GUIDE",
            font=self.fonts.font(16, latin=True, weight="black"),
            fill=WHITE,
            anchor="lm",
        )
        draw.text(
            (HELP_WIDTH - 70, 218),
            "HELP / MENU",
            font=self.fonts.font(13, latin=True, weight="semibold"),
            fill=(93, 224, 231),
            anchor="rm",
        )

    def _draw_section(
        self,
        canvas: Image.Image,
        x: int,
        y: int,
        width: int,
        number: str,
        title: str,
        color: tuple[int, int, int],
        rows: tuple[tuple[str, str], ...],
        *,
        row_height: int,
    ) -> int:
        draw = ImageDraw.Draw(canvas, "RGBA")
        height = 62 + len(rows) * row_height + 16
        draw.rounded_rectangle(
            (x + 5, y + 7, x + width + 5, y + height + 7),
            radius=7,
            fill=(220, 216, 230, 255),
        )
        draw.rounded_rectangle(
            (x, y, x + width, y + height),
            radius=7,
            fill=(255, 255, 255, 246),
            outline=(210, 206, 221, 255),
            width=2,
        )
        draw.rectangle((x, y, x + 10, y + height), fill=(*color, 255))
        draw.polygon(
            ((x + 10, y), (x + width, y), (x + width - 18, y + 62), (x + 10, y + 62)),
            fill=(24, 33, 47, 248),
        )
        draw.text(
            (x + 34, y + 31),
            number,
            font=self.fonts.font(17, latin=True, weight="black"),
            fill=color,
            anchor="lm",
        )
        draw.text(
            (x + 90, y + 31),
            title,
            font=self.fonts.font(25, weight="black"),
            fill=WHITE,
            anchor="lm",
        )

        row_y = y + 62
        for index, (command, description) in enumerate(rows):
            if index % 2:
                draw.rectangle(
                    (x + 10, row_y, x + width, row_y + row_height),
                    fill=(240, 244, 248, 170),
                )
            draw.rectangle(
                (x + 27, row_y + 18, x + 34, row_y + row_height - 18),
                fill=(*color, 220),
            )
            command_font = self.fonts.fit(
                draw, command, width - 75, 23, 15, weight="black"
            )
            draw.text(
                (x + 50, row_y + 12), command, font=command_font, fill=INK, anchor="lt"
            )
            draw.text(
                (x + 50, row_y + row_height - 13),
                description,
                font=self.fonts.font(17, weight="medium"),
                fill=MUTED,
                anchor="ls",
            )
            row_y += row_height
        return y + height

    def _draw_difficulty_strip(self, canvas: Image.Image, x: int, y: int) -> None:
        draw = ImageDraw.Draw(canvas, "RGBA")
        draw.rounded_rectangle(
            (x, y, HELP_WIDTH - x, y + 82),
            radius=7,
            fill=(255, 255, 255, 246),
            outline=(35, 50, 68, 42),
            width=2,
        )
        draw.text(
            (x + 24, y + 41),
            "难度写法",
            font=self.fonts.font(20, weight="black"),
            fill=INK,
            anchor="lm",
        )
        aliases = (
            ("BAS", "0 / basic", DIFFICULTY_STYLES[0]["main"]),
            ("ADV", "1 / advanced", DIFFICULTY_STYLES[1]["main"]),
            ("EXP", "2 / expert", DIFFICULTY_STYLES[2]["main"]),
            ("MAS", "3 / master", DIFFICULTY_STYLES[3]["main"]),
            ("ULT", "4 / ultima", DIFFICULTY_STYLES[4]["main"]),
            ("WE", "5 / world", DIFFICULTY_STYLES[5]["edge"]),
        )
        start_x = x + 170
        item_width = 150
        for index, (short, detail, color) in enumerate(aliases):
            item_x = start_x + index * item_width
            draw.rectangle((item_x, y + 17, item_x + 7, y + 65), fill=(*color, 255))
            draw.text(
                (item_x + 18, y + 28),
                short,
                font=self.fonts.font(16, latin=True, weight="black"),
                fill=INK,
                anchor="lm",
            )
            draw.text(
                (item_x + 18, y + 54),
                detail,
                font=self.fonts.font(12, latin=True, weight="semibold"),
                fill=MUTED,
                anchor="lm",
            )

    def _draw_notes(self, canvas: Image.Image, x: int, y: int) -> None:
        draw = ImageDraw.Draw(canvas, "RGBA")
        notes = (
            ("命令格式", "所有指令必须以 /chu 开头", (24, 190, 203)),
            (
                "Token 权限",
                "玩家、成绩、B30、Recent 查询需要开发者 Token",
                (222, 67, 177),
            ),
            (
                "本地与隐私",
                "日常图片查询读取本地素材；好友码与游玩次数默认隐藏",
                (72, 174, 91),
            ),
        )
        width = (HELP_WIDTH - x * 2 - 24 * 2) // 3
        for index, (title, detail, color) in enumerate(notes):
            item_x = x + index * (width + 24)
            draw.rounded_rectangle(
                (item_x, y, item_x + width, y + 166),
                radius=7,
                fill=(255, 255, 255, 246),
                outline=(35, 50, 68, 38),
                width=2,
            )
            draw.rectangle((item_x, y, item_x + width, y + 8), fill=(*color, 255))
            draw.text(
                (item_x + 22, y + 42),
                title,
                font=self.fonts.font(20, weight="black"),
                fill=INK,
            )
            detail_font = self.fonts.fit(
                draw, detail, width - 44, 17, 13, weight="medium"
            )
            lines = self._wrap_text(draw, detail, detail_font, width - 44)
            draw.multiline_text(
                (item_x + 22, y + 84), lines, font=detail_font, fill=MUTED, spacing=8
            )

    @staticmethod
    def _wrap_text(
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.FreeTypeFont,
        max_width: int,
    ) -> str:
        lines: list[str] = []
        current = ""
        for char in text:
            candidate = current + char
            if current and draw.textlength(candidate, font=font) > max_width:
                lines.append(current)
                current = char
            else:
                current = candidate
        if current:
            lines.append(current)
        return "\n".join(lines)

    def _draw_footer(self, canvas: Image.Image, footer_bot_name: str) -> None:
        draw = ImageDraw.Draw(canvas, "RGBA")
        y = HELP_HEIGHT - 38
        draw.line(
            (52, y - 24, HELP_WIDTH - 52, y - 24), fill=(32, 48, 67, 105), width=2
        )
        draw.rectangle((52, y - 29, 112, y - 21), fill=(24, 190, 203, 255))
        draw.rectangle((112, y - 29, 152, y - 21), fill=(249, 199, 42, 255))
        draw.text(
            (52, y),
            "/chu help",
            font=self.fonts.font(15, latin=True, weight="black"),
            fill=(61, 78, 100),
            anchor="lm",
        )
        footer = f"Powered By maimai.lxns.net / Generated By {footer_bot_name}"
        footer_font = self.fonts.fit(
            draw, footer, 650, 15, 11, latin=True, weight="semibold"
        )
        draw.text(
            (HELP_WIDTH - 52, y),
            footer,
            font=footer_font,
            fill=(61, 78, 100),
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
