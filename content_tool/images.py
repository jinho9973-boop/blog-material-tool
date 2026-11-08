"""Pillow image composition with Korean-safe fitting and wrapping."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

from .material import Material

NAVY = "#102A43"
DEEP_NAVY = "#071B2B"
MINT = "#55D6BE"
WHITE = "#FFFFFF"


class ImageComposeError(RuntimeError):
    """Image composition failed."""


def font_path() -> Path:
    path = Path(__file__).resolve().parent.parent / "fonts" / "NanumGothic.ttf"
    if not path.exists():
        raise ImageComposeError("fonts/NanumGothic.ttf 파일이 없습니다.")
    return path


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    bold_path = font_path().with_name("NanumGothicBold.ttf")
    path = bold_path if bold and bold_path.exists() else font_path()
    return ImageFont.truetype(str(path), size=size)


def _background(path: Path, size: tuple[int, int], darken: float = 1.0) -> Image.Image:
    if path.exists():
        with Image.open(path) as source:
            image = ImageOps.fit(source.convert("RGB"), size, method=Image.Resampling.LANCZOS)
        if darken < 1:
            image = ImageEnhance.Brightness(image).enhance(darken)
        return image
    return Image.new("RGB", size, DEEP_NAVY)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        current = ""
        for char in paragraph:
            candidate = current + char
            if draw.textbbox((0, 0), candidate, font=font)[2] <= width or not current:
                current = candidate
            else:
                lines.append(current.rstrip())
                current = char
        lines.append(current.rstrip())
    return lines


def _fitted(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    *,
    maximum: int,
    minimum: int,
    spacing: int = 18,
    bold: bool = True,
) -> tuple[ImageFont.FreeTypeFont, list[str], int]:
    width, height = box[2] - box[0], box[3] - box[1]
    for size in range(maximum, minimum - 1, -2):
        font = _font(size, bold=bold)
        lines = _wrap(draw, text, font, width)
        line_height = draw.textbbox((0, 0), "가Ag", font=font)[3] + spacing
        if len(lines) * line_height <= height:
            return font, lines, line_height
    font = _font(minimum, bold=bold)
    lines = _wrap(draw, text, font, width)
    return font, lines, draw.textbbox((0, 0), "가Ag", font=font)[3] + spacing


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    text: str,
    box: tuple[int, int, int, int],
    maximum: int,
    minimum: int,
    fill: str = WHITE,
) -> None:
    font, lines, line_height = _fitted(
        draw, text, box, maximum=maximum, minimum=minimum
    )
    total = len(lines) * line_height
    y = box[1] + max(0, (box[3] - box[1] - total) // 2)
    for line in lines:
        bounds = draw.textbbox((0, 0), line, font=font)
        x = box[0] + (box[2] - box[0] - (bounds[2] - bounds[0])) // 2
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height


def _save_thumbnail(material: Material, bg: Path, destination: Path) -> None:
    image = _background(bg, (1080, 1080), darken=0.36)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((70, 70, 1010, 1010), radius=38, outline=MINT, width=5)
    _draw_centered(draw, material.hook, (130, 190, 950, 750), 86, 42)
    subline = material.key_points[0]
    _draw_centered(draw, subline, (150, 790, 930, 940), 38, 25, MINT)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, "PNG")


def _save_summary_card(
    material: Material, index: int, bg: Path, destination: Path
) -> None:
    image = _background(bg, (1080, 1080), darken=0.28)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((65, 65, 1015, 1015), radius=46, fill=NAVY)
    number = material.numbers[index - 1] if index <= len(material.numbers) else None
    heading = number["항목"] if number else material.headings[index - 1]
    value = number["값"] if number else material.key_points[index - 1]
    _draw_centered(draw, heading, (130, 150, 950, 330), 50, 30, MINT)
    _draw_centered(draw, value, (115, 340, 965, 710), 102, 42)
    detail = number["출처"] if number else material.sections[index - 1][0]
    _draw_centered(draw, detail, (140, 760, 940, 930), 34, 23, "#CDEFE9")
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, "PNG")


def _save_instagram_card(
    material: Material, index: int, bg: Path, destination: Path
) -> None:
    image = _background(bg, (1080, 1350), darken=0.25)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((60, 70, 1020, 1280), radius=42, fill=NAVY)
    if index == 1:
        heading, body = material.hook, material.key_points[0]
    else:
        section_index = min(index - 2, len(material.headings) - 1)
        heading = material.headings[section_index]
        body = "\n".join(material.sections[section_index][:3])
    _draw_centered(draw, heading, (130, 180, 950, 550), 67, 35, MINT)
    _draw_centered(draw, body, (140, 610, 940, 1120), 45, 28)
    image.save(destination, "PNG")


def compose_images(
    material: Material,
    blog_number: int,
    material_dir: Path,
    output_dir: Path,
    *,
    instagram: bool = True,
) -> list[Path]:
    bg_dir = material_dir / "bg"
    files: list[Path] = []
    thumb = output_dir / "썸네일.png"
    _save_thumbnail(material, bg_dir / f"bg_blog{blog_number}_thumb.png", thumb)
    files.append(thumb)
    summary_count = min(2, max(1, len(material.numbers)))
    for index in range(1, summary_count + 1):
        destination = output_dir / f"요약카드{index}.png"
        _save_summary_card(
            material,
            index,
            bg_dir / f"bg_blog{blog_number}_card{index}.png",
            destination,
        )
        files.append(destination)
    if instagram:
        folder = output_dir / "instagram"
        folder.mkdir(parents=True, exist_ok=True)
        count = max(4, min(6, len(material.headings)))
        for index in range(1, count + 1):
            destination = folder / f"카드뉴스{index}.png"
            _save_instagram_card(
                material,
                index,
                bg_dir / f"bg_blog{blog_number}_insta{index}.png",
                destination,
            )
            files.append(destination)
    return files
