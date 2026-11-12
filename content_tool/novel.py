"""Novel manuscript, storyboard, scene-image, prompt, and MP4 video pipeline."""

from __future__ import annotations

import json
import math
import random
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from .images import ImageComposeError, _font, _wrap

ASPECT_SIZES: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}

MOOD_PALETTES: dict[str, tuple[tuple[int, int, int], tuple[int, int, int], str]] = {
    "corridor": ((14, 18, 26), (38, 32, 28), "#E8C39E"),
    "night": ((8, 13, 28), (24, 34, 58), "#9CC4E4"),
    "rain": ((11, 20, 31), (32, 52, 68), "#A8D5E5"),
    "afternoon": ((28, 22, 20), (74, 52, 40), "#F2D0A9"),
    "tension": ((24, 12, 18), (58, 24, 34), "#F0B7B3"),
    "window": ((15, 22, 32), (46, 58, 72), "#D6E4F0"),
}

MOOD_VISUALS: dict[str, tuple[str, str]] = {
    "rain": (
        "heavy summer rain outside apartment shelter, wet ivory linen shirt clinging subtly, "
        "water droplets on glass and umbrella, moody blue-grey reflections, dramatic chiaroscuro lighting",
        "Slow cinematic push-in, raindrops falling in slow motion, subtle unsteady breathing, "
        "eyes shifting downward in flustered silence, shallow depth of field.",
    ),
    "corridor": (
        "quiet luxury Korean apartment hallway at night, two adjacent front doors 1401 and 1402, "
        "warm recessed ceiling light casting long shadows, hushed tension",
        "Slow dolly forward along the quiet hallway, warm light flickering softly on the door lock, "
        "subtle handheld tension.",
    ),
    "afternoon": (
        "sunlit yet quiet apartment living room at 3 PM, warm afternoon light sliced through venetian blinds, "
        "two teacups on a low table, dust motes floating in warm air",
        "Gentle lateral camera pan across afternoon window blinds, curtain swaying slightly, "
        "lingering close-up on hesitant fingers near a teacup.",
    ),
    "tension": (
        "intimate close two-shot indoors with restrained distance, warm rim lighting against deep shadow, "
        "unspoken psychological tension, hyper-detailed eyes and posture",
        "Very slow zoom-in on subtle gaze exchange, shallow breathing, strands of hair moving softly, "
        "cinematic suspense.",
    ),
    "night": (
        "late-night apartment balcony overlooking dim city bokeh lights, thin wall separating two balconies, "
        "cool moonlight mixed with warm interior lamp glow",
        "Slow pull-back from dimly lit balcony window into night air, distant city lights shimmering softly.",
    ),
    "window": (
        "minimalist apartment interior by a tall rain-streaked window, muted slate and warm wood tones, "
        "quiet solitude",
        "Subtle camera drift past window frame, soft reflections shifting across glass.",
    ),
}

CAMERA_CYCLE = ("zoom_in", "pan_up", "zoom_out", "pan_down")


class NovelError(ValueError):
    """Validation or rendering error in the novel-to-video pipeline."""


@dataclass(frozen=True)
class CharacterProfile:
    name: str
    role: str
    description: str
    visual_prompt: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class SeriesBible:
    title: str
    subtitle: str = ""
    genre: str = "성인 심리 드라마"
    style_prompt: str = (
        "Cinematic Korean K-drama film still, moody atmospheric lighting, "
        "35mm anamorphic lens, shallow depth of field, realistic skin texture, "
        "subtle film grain, photorealistic, no text, no letters, no watermark, no logo"
    )
    characters: dict[str, CharacterProfile] = field(default_factory=dict)


@dataclass(frozen=True)
class Scene:
    index: int
    title: str
    narration: str
    caption: str
    mood: str
    characters: list[str]
    image_prompt: str
    motion_prompt: str
    camera: str = "zoom_in"
    duration: float = 4.5


@dataclass(frozen=True)
class Episode:
    number: int
    title: str
    summary: str
    paragraphs: list[str]
    scenes: list[Scene]
    tags: list[str] = field(default_factory=list)


def load_series_bible(novel_dir: Path) -> SeriesBible:
    path = novel_dir / "series_bible.json"
    if not path.exists():
        return SeriesBible(title=novel_dir.name)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise NovelError(f"series_bible.json 형식 오류({exc.lineno}행)") from exc
    if not isinstance(raw, dict):
        raise NovelError("series_bible.json 최상위 값은 객체여야 합니다.")
    chars: dict[str, CharacterProfile] = {}
    for key, item in raw.get("등장인물", {}).items():
        if not isinstance(item, dict):
            continue
        aliases = tuple(str(a).strip() for a in item.get("별칭", []) if str(a).strip())
        chars[key] = CharacterProfile(
            name=str(item.get("이름", key)).strip(),
            role=str(item.get("역할", "")).strip(),
            description=str(item.get("설명", "")).strip(),
            visual_prompt=str(item.get("외형프롬프트", "")).strip(),
            aliases=aliases,
        )
    return SeriesBible(
        title=str(raw.get("제목", novel_dir.name)).strip(),
        subtitle=str(raw.get("부제", "")).strip(),
        genre=str(raw.get("장르", "성인 심리 드라마")).strip(),
        style_prompt=str(raw.get("공통화풍프롬프트", SeriesBible.style_prompt)).strip(),
        characters=chars,
    )


def _infer_mood(text: str) -> str:
    if any(word in text for word in ("소나기", "장마", "우산", "빗물", "젖은", "폭우", "비에")):
        return "rain"
    if any(word in text for word in ("실루엣", "허리", "목선", "체온", "숨결", "시선", "셔츠", "쇄골")):
        return "tension"
    if any(word in text for word in ("오후", "세 시", "햇살", "블라인드", "찻잔", "홍차", "거실")):
        return "afternoon"
    if any(word in text for word in ("복도", "엘리베이터", "도어락", "현관", "1401", "1402", "초인종")):
        return "corridor"
    if any(word in text for word in ("자정", "새벽", "밤", "베란다", "어둠", "불빛")):
        return "night"
    return "window"


def _detect_characters(text: str, bible: SeriesBible) -> list[str]:
    found: list[str] = []
    for key, profile in bible.characters.items():
        tokens = (key, profile.name, *profile.aliases)
        if any(token and token in text for token in tokens):
            found.append(key)
    return found


def _auto_caption(text: str, max_chars: int = 64) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?…])\s+", cleaned) if s.strip()]
    chosen = sentences[0] if sentences else cleaned
    if len(chosen) <= max_chars:
        return chosen
    return chosen[: max_chars - 1].rstrip() + "…"


def _estimate_duration(text: str) -> float:
    char_count = len(re.sub(r"\s+", "", text))
    return round(min(7.0, max(3.5, char_count / 13.5)), 1)


def _auto_scenes_from_paragraphs(
    paragraphs: list[str], bible: SeriesBible, target_scenes: int = 7
) -> list[Scene]:
    if not paragraphs:
        raise NovelError("본문 문단이 비어 있습니다.")
    chunk_size = max(1, math.ceil(len(paragraphs) / target_scenes))
    grouped = [
        paragraphs[idx : idx + chunk_size]
        for idx in range(0, len(paragraphs), chunk_size)
    ]
    scenes: list[Scene] = []
    for index, group in enumerate(grouped, 1):
        joined = "\n\n".join(group)
        mood = _infer_mood(joined)
        chars = _detect_characters(joined, bible)
        visual_setting, motion = MOOD_VISUALS[mood]
        narration = group[0] if len(group[0]) >= 22 or len(group) == 1 else f"{group[0]} {group[1]}"
        caption = _auto_caption(narration)
        scenes.append(
            Scene(
                index=index,
                title=f"장면 {index}",
                narration=narration,
                caption=caption,
                mood=mood,
                characters=chars,
                image_prompt=visual_setting,
                motion_prompt=motion,
                camera=CAMERA_CYCLE[(index - 1) % len(CAMERA_CYCLE)],
                duration=_estimate_duration(caption),
            )
        )
    return scenes


def load_episode(path: Path, bible: SeriesBible) -> Episode:
    if not path.exists():
        raise NovelError(f"회차 파일이 없습니다: {path}")
    if path.suffix.lower() == ".json":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise NovelError(f"JSON 형식 오류({exc.lineno}행): {path.name}") from exc
        if not isinstance(data, dict):
            raise NovelError(f"회차 파일 최상위 값은 객체여야 합니다: {path.name}")
        number = int(data.get("회차", 1))
        title = str(data.get("제목", f"{number}화")).strip()
        summary = str(data.get("요약", "")).strip()
        raw_paragraphs = data.get("본문", [])
        if isinstance(raw_paragraphs, str):
            paragraphs = [p.strip() for p in raw_paragraphs.split("\n\n") if p.strip()]
        elif isinstance(raw_paragraphs, list):
            paragraphs = [str(p).strip() for p in raw_paragraphs if str(p).strip()]
        else:
            paragraphs = []
        if not paragraphs:
            raise NovelError(f"'본문'이 비어 있습니다: {path.name}")
        raw_scenes = data.get("장면", [])
        if isinstance(raw_scenes, list) and raw_scenes:
            scenes = _parse_scenes(raw_scenes, bible)
        else:
            scenes = _auto_scenes_from_paragraphs(paragraphs, bible)
        tags = [str(t).strip() for t in data.get("태그", []) if str(t).strip()]
        return Episode(
            number=number,
            title=title,
            summary=summary,
            paragraphs=paragraphs,
            scenes=scenes,
            tags=tags,
        )

    raw_text = path.read_text(encoding="utf-8").strip()
    if not raw_text:
        raise NovelError(f"원고 파일이 비어 있습니다: {path.name}")
    match = re.search(r"(\d+)", path.stem)
    number = int(match.group(1)) if match else 1
    lines = [line.strip() for line in raw_text.splitlines()]
    title = f"{number}화"
    body_lines = lines
    if lines and lines[0].startswith("#"):
        heading = lines[0].lstrip("#").strip()
        heading = re.sub(r"^\d+\s*화[\s.:·-]*", "", heading).strip()
        if heading:
            title = heading
        body_lines = lines[1:]
    paragraphs = [
        block.strip()
        for block in re.split(r"\n\s*\n", "\n".join(body_lines))
        if block.strip()
    ]
    if not paragraphs:
        paragraphs = [line for line in body_lines if line]
    scenes = _auto_scenes_from_paragraphs(paragraphs, bible)
    return Episode(
        number=number,
        title=title,
        summary=_auto_caption(paragraphs[0], 90),
        paragraphs=paragraphs,
        scenes=scenes,
    )


def _parse_scenes(raw_scenes: list[Any], bible: SeriesBible) -> list[Scene]:
    scenes: list[Scene] = []
    for index, item in enumerate(raw_scenes, 1):
        if not isinstance(item, dict):
            raise NovelError(f"장면[{index}]은 객체여야 합니다.")
        narration = str(item.get("나레이션") or item.get("대사") or "").strip()
        caption = str(item.get("자막") or _auto_caption(narration)).strip()
        if not caption:
            raise NovelError(f"장면[{index}]에 자막 또는 나레이션이 필요합니다.")
        mood = str(item.get("분위기") or _infer_mood(narration + " " + caption)).strip()
        if mood not in MOOD_PALETTES:
            mood = _infer_mood(narration + " " + caption)
        raw_chars = item.get("등장인물")
        if isinstance(raw_chars, list):
            chars = [str(c).strip() for c in raw_chars if str(c).strip()]
        else:
            chars = _detect_characters(narration + " " + caption, bible)
        default_img, default_motion = MOOD_VISUALS[mood]
        image_prompt = str(item.get("이미지프롬프트") or default_img).strip()
        motion_prompt = str(item.get("영상프롬프트") or default_motion).strip()
        camera = str(
            item.get("카메라") or CAMERA_CYCLE[(index - 1) % len(CAMERA_CYCLE)]
        ).strip()
        if camera not in CAMERA_CYCLE:
            camera = CAMERA_CYCLE[(index - 1) % len(CAMERA_CYCLE)]
        duration = float(item.get("길이초") or _estimate_duration(caption))
        scenes.append(
            Scene(
                index=index,
                title=str(item.get("제목") or f"장면 {index}").strip(),
                narration=narration or caption,
                caption=caption,
                mood=mood,
                characters=chars,
                image_prompt=image_prompt,
                motion_prompt=motion_prompt,
                camera=camera,
                duration=max(2.0, min(12.0, duration)),
            )
        )
    return scenes


def discover_episode_files(novel_dir: Path, numbers: list[int] | None = None) -> list[Path]:
    if not novel_dir.exists():
        raise NovelError(f"소설 폴더가 없습니다: {novel_dir}")
    by_number: dict[int, Path] = {}
    candidates = sorted(
        [*novel_dir.glob("ep*.json"), *novel_dir.glob("ep*.md"), *novel_dir.glob("ep*.txt"),
         *novel_dir.glob("*화*.json"), *novel_dir.glob("*화*.md"), *novel_dir.glob("*화*.txt")]
    )
    for path in candidates:
        if path.name == "series_bible.json":
            continue
        match = re.search(r"(\d+)", path.stem)
        if not match:
            continue
        ep_num = int(match.group(1))
        existing = by_number.get(ep_num)
        if existing is None or (existing.suffix.lower() != ".json" and path.suffix.lower() == ".json"):
            by_number[ep_num] = path
    if not by_number:
        raise NovelError(f"회차 원고 파일(ep01.json, ep01.md 등)이 없습니다: {novel_dir}")
    if numbers:
        missing = [num for num in numbers if num not in by_number]
        if missing:
            raise NovelError(f"찾을 수 없는 회차 번호: {', '.join(map(str, missing))}")
        return [by_number[num] for num in numbers]
    return [by_number[num] for num in sorted(by_number)]


def full_image_prompt(scene: Scene, bible: SeriesBible, aspect: str = "9:16") -> str:
    orientation = (
        "Vertical 9:16 portrait composition"
        if aspect == "9:16"
        else "Widescreen 16:9 cinematic frame"
        if aspect == "16:9"
        else "Square 1:1 composition"
    )
    char_prompts = [
        bible.characters[key].visual_prompt
        for key in scene.characters
        if key in bible.characters and bible.characters[key].visual_prompt
    ]
    parts = [orientation, *char_prompts, scene.image_prompt, bible.style_prompt]
    return ", ".join(part.rstrip(",.") for part in parts if part) + "."


def full_motion_prompt(scene: Scene, aspect: str = "9:16") -> str:
    ratio = "9:16 vertical video" if aspect == "9:16" else "16:9 cinematic video"
    return (
        f"[Image-to-Video | {ratio} | {scene.duration:.1f}s] {scene.motion_prompt} "
        "Keep facial identity and clothing strictly consistent with source image, "
        "natural realistic physics, no morphing, no text, no watermark."
    )


def format_manuscript_markdown(episode: Episode, bible: SeriesBible) -> str:
    header = f"# {bible.title} — {episode.number}화. {episode.title}"
    lines = [header, ""]
    if episode.summary:
        lines.extend([f"> {episode.summary}", ""])
    lines.extend("\n\n".join(episode.paragraphs).splitlines())
    if episode.tags:
        tag_line = " ".join("#" + re.sub(r"\s+", "", t.lstrip("#")) for t in episode.tags)
        lines.extend(["", "---", "", tag_line])
    return "\n".join(lines).strip() + "\n"


def format_manuscript_text(episode: Episode, bible: SeriesBible) -> str:
    lines = [f"{bible.title} - {episode.number}화. {episode.title}", ""]
    lines.append("\n\n".join(episode.paragraphs))
    return "\n".join(lines).strip() + "\n"


def format_storyboard_markdown(
    episode: Episode, bible: SeriesBible, aspect: str = "9:16"
) -> str:
    lines = [
        f"# 스토리보드 — {episode.number}화. {episode.title}",
        "",
        f"- 화면 비율: `{aspect}`",
        f"- 총 장면 수: `{len(episode.scenes)}컷` "
        f"(예상 길이 약 `{sum(s.duration for s in episode.scenes):.1f}초`)",
        "",
        "| 컷 | 길이 | 분위기 | 화면 자막 | 카메라 |",
        "|---:|---:|---|---|---|",
    ]
    for scene in episode.scenes:
        safe_cap = scene.caption.replace("|", "\\|")
        lines.append(
            f"| {scene.index:02d} | {scene.duration:.1f}s | {scene.mood} | {safe_cap} | {scene.camera} |"
        )
    lines.append("")
    for scene in episode.scenes:
        lines.extend(
            [
                f"## Cut {scene.index:02d}. {scene.title} ({scene.duration:.1f}s)",
                "",
                f"- **나레이션/본문 발췌**: {scene.narration}",
                f"- **화면 자막**: {scene.caption}",
                f"- **이미지 생성 프롬프트**: `{full_image_prompt(scene, bible, aspect)}`",
                f"- **영상 전환(I2V) 프롬프트**: `{full_motion_prompt(scene, aspect)}`",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def _srt_timestamp(seconds: float) -> str:
    millis = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def format_srt(episode: Episode) -> str:
    blocks: list[str] = []
    cursor = 0.0
    for scene in episode.scenes:
        start = _srt_timestamp(cursor)
        end = _srt_timestamp(cursor + scene.duration)
        blocks.append(f"{scene.index}\n{start} --> {end}\n{scene.caption}\n")
        cursor += scene.duration
    return "\n".join(blocks).strip() + "\n"


def _procedural_backdrop(size: tuple[int, int], mood: str, seed: int) -> Image.Image:
    width, height = size
    top_rgb, bottom_rgb, _accent = MOOD_PALETTES.get(mood, MOOD_PALETTES["window"])
    rng = random.Random(seed)

    # Render gradient on a compact canvas and upscale smoothly for speed.
    small_w, small_h = max(180, width // 6), max(180, height // 6)
    base = Image.new("RGB", (small_w, small_h))
    px = base.load()
    assert px is not None
    for y in range(small_h):
        t = y / max(1, small_h - 1)
        r = int(top_rgb[0] * (1 - t) + bottom_rgb[0] * t)
        g = int(top_rgb[1] * (1 - t) + bottom_rgb[1] * t)
        b = int(top_rgb[2] * (1 - t) + bottom_rgb[2] * t)
        for x in range(small_w):
            px[x, y] = (r, g, b)
    image = base.resize(size, Image.Resampling.BICUBIC).convert("RGBA")
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    if mood == "rain":
        glow_box = (int(width * 0.18), int(height * 0.12), int(width * 0.82), int(height * 0.62))
        draw.ellipse(glow_box, fill=(130, 185, 215, 36))
        for _ in range(130):
            x0 = rng.randint(-80, width)
            y0 = rng.randint(-100, height)
            length = rng.randint(70, 210)
            alpha = rng.randint(22, 68)
            draw.line((x0, y0, x0 - length // 5, y0 + length), fill=(195, 225, 245, alpha), width=2)
    elif mood == "corridor":
        slit_x = int(width * 0.56)
        draw.rectangle((slit_x, int(height * 0.12), slit_x + 16, int(height * 0.78)), fill=(245, 198, 138, 88))
        draw.polygon(
            [
                (slit_x, int(height * 0.78)),
                (slit_x + 16, int(height * 0.78)),
                (int(width * 0.82), int(height * 0.96)),
                (int(width * 0.28), int(height * 0.96)),
            ],
            fill=(238, 188, 128, 34),
        )
    elif mood == "afternoon":
        for band in range(9):
            y0 = int(height * (0.14 + band * 0.055))
            draw.polygon(
                [
                    (int(width * 0.12), y0),
                    (int(width * 0.88), y0 + 28),
                    (int(width * 0.88), y0 + 54),
                    (int(width * 0.12), y0 + 26),
                ],
                fill=(250, 212, 160, 32),
            )
    elif mood == "tension":
        draw.ellipse(
            (int(width * 0.20), int(height * 0.15), int(width * 0.92), int(height * 0.72)),
            fill=(215, 110, 118, 42),
        )
    else:
        for _ in range(22):
            cx = rng.randint(int(width * 0.08), int(width * 0.92))
            cy = rng.randint(int(height * 0.12), int(height * 0.68))
            rad = rng.randint(24, 95)
            color = rng.choice([(245, 200, 140, 30), (140, 190, 235, 26), (255, 235, 205, 22)])
            draw.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), fill=color)

    blurred = overlay.filter(ImageFilter.GaussianBlur(radius=14))
    combined = Image.alpha_composite(image, blurred)

    # Darken bottom area for crisp subtitle legibility.
    shade = Image.new("RGBA", (1, height), (0, 0, 0, 0))
    for y in range(height):
        if y < height * 0.48:
            alpha = int(55 * (1 - y / (height * 0.48)))
        else:
            progress = (y - height * 0.48) / (height * 0.52)
            alpha = int(30 + 185 * (progress**1.35))
        shade.putpixel((0, y), (5, 8, 14, min(225, alpha)))
    combined = Image.alpha_composite(combined, shade.resize(size, Image.Resampling.BILINEAR))
    return combined.convert("RGB")


def _find_custom_scene_image(novel_dir: Path, ep_number: int, scene_index: int) -> Path | None:
    bg_dir = novel_dir / "bg"
    if not bg_dir.exists():
        return None
    stems = (
        f"ep{ep_number:02d}_scene_{scene_index:02d}",
        f"ep{ep_number}_scene_{scene_index}",
        f"scene_{scene_index:02d}",
    )
    for stem in stems:
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            candidate = bg_dir / f"{stem}{ext}"
            if candidate.is_file():
                return candidate
    return None


def _find_custom_scene_clip(novel_dir: Path, ep_number: int, scene_index: int) -> Path | None:
    clips_dir = novel_dir / "clips"
    if not clips_dir.exists():
        return None
    for stem in (f"ep{ep_number:02d}_scene_{scene_index:02d}", f"ep{ep_number}_scene_{scene_index}"):
        candidate = clips_dir / f"{stem}.mp4"
        if candidate.is_file():
            return candidate
    return None


def render_scene_image(
    scene: Scene,
    episode: Episode,
    bible: SeriesBible,
    novel_dir: Path,
    destination: Path,
    *,
    aspect: str = "9:16",
    subtitle_overlay: bool = True,
) -> Path:
    if aspect not in ASPECT_SIZES:
        raise NovelError(f"지원하지 않는 화면 비율: {aspect}")
    size = ASPECT_SIZES[aspect]
    width, height = size
    custom = _find_custom_scene_image(novel_dir, episode.number, scene.index)
    if custom is not None:
        with Image.open(custom) as source:
            image = ImageOps.fit(source.convert("RGB"), size, method=Image.Resampling.LANCZOS)
        image = ImageEnhance.Brightness(image).enhance(0.84)
        rgba = image.convert("RGBA")
        shade = Image.new("RGBA", (1, height), (0, 0, 0, 0))
        for y in range(height):
            alpha = int(195 * max(0.0, (y - height * 0.55) / (height * 0.45)) ** 1.3)
            shade.putpixel((0, y), (6, 8, 14, min(215, alpha)))
        image = Image.alpha_composite(rgba, shade.resize(size, Image.Resampling.BILINEAR)).convert("RGB")
    else:
        image = _procedural_backdrop(size, scene.mood, episode.number * 100 + scene.index)

    if subtitle_overlay:
        draw = ImageDraw.Draw(image)
        _, _, accent = MOOD_PALETTES.get(scene.mood, MOOD_PALETTES["window"])
        margin_x = int(width * 0.085)
        top_y = int(height * 0.065)

        badge_font = _font(max(22, int(width * 0.026)), bold=True)
        badge_text = f"{bible.title}  |  EP.{episode.number:02d}"
        draw.text((margin_x, top_y), badge_text, font=badge_font, fill=accent)

        caption_font = _font(max(30, int(width * 0.041)), bold=True)
        box_width = width - margin_x * 2
        lines = _wrap(draw, scene.caption, caption_font, box_width)
        line_height = draw.textbbox((0, 0), "가Ag", font=caption_font)[3] + 16
        total_h = len(lines) * line_height
        start_y = int(height * 0.855) - total_h

        # Subtle accent rule above caption
        rule_w = min(96, box_width // 5)
        draw.rectangle(
            (width // 2 - rule_w // 2, start_y - 30, width // 2 + rule_w // 2, start_y - 26),
            fill=accent,
        )
        y = start_y
        for line in lines:
            bounds = draw.textbbox((0, 0), line, font=caption_font)
            x = (width - (bounds[2] - bounds[0])) // 2
            draw.text((x + 2, y + 2), line, font=caption_font, fill="#05070C")
            draw.text((x, y), line, font=caption_font, fill="#F8F9FA")
            y += line_height

    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, "PNG")
    return destination


def _camera_filter(camera: str, width: int, height: int, duration: float, fps: int) -> str:
    frames = max(12, int(round(duration * fps)))
    fade_out_start = max(0.0, duration - 0.4)
    if camera == "zoom_out":
        zp = (
            f"zoompan=z='if(eq(on,1),1.11,max(1.0,zoom-0.11/{frames}))':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}:fps={fps}"
        )
    elif camera == "pan_up":
        zp = (
            f"zoompan=z='1.09':x='iw/2-(iw/zoom/2)':"
            f"y='(ih-ih/zoom)*(1-on/{frames})':d={frames}:s={width}x{height}:fps={fps}"
        )
    elif camera == "pan_down":
        zp = (
            f"zoompan=z='1.09':x='iw/2-(iw/zoom/2)':"
            f"y='(ih-ih/zoom)*(on/{frames})':d={frames}:s={width}x{height}:fps={fps}"
        )
    else:
        zp = (
            f"zoompan=z='min(zoom+0.11/{frames},1.11)':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={width}x{height}:fps={fps}"
        )
    return f"{zp},fade=t=in:st=0:d=0.35,fade=t=out:st={fade_out_start:.2f}:d=0.40,format=yuv420p"


def render_episode_video(
    episode: Episode,
    scene_images: list[Path],
    novel_dir: Path,
    destination: Path,
    *,
    aspect: str = "9:16",
    fps: int = 24,
) -> Path:
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise ImageComposeError("ffmpeg가 설치되어 있지 않아 MP4 영상을 만들 수 없습니다.")
    if len(scene_images) != len(episode.scenes):
        raise NovelError("장면 수와 생성된 장면 이미지 수가 일치하지 않습니다.")

    width, height = ASPECT_SIZES[aspect]
    destination.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="novel_vid_") as tmp:
        tmp_dir = Path(tmp)
        segment_paths: list[Path] = []

        for scene, image_path in zip(episode.scenes, scene_images, strict=True):
            seg_path = tmp_dir / f"seg_{scene.index:02d}.mp4"
            custom_clip = _find_custom_scene_clip(novel_dir, episode.number, scene.index)
            if custom_clip is not None:
                fade_out = max(0.0, scene.duration - 0.4)
                vf = (
                    f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                    f"crop={width}:{height},fps={fps},"
                    f"fade=t=in:st=0:d=0.35,fade=t=out:st={fade_out:.2f}:d=0.40,format=yuv420p"
                )
                cmd = [
                    ffmpeg_bin, "-y", "-i", str(custom_clip),
                    "-t", f"{scene.duration:.2f}",
                    "-vf", vf, "-an",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                    str(seg_path),
                ]
            else:
                vf = _camera_filter(scene.camera, width, height, scene.duration, fps)
                cmd = [
                    ffmpeg_bin, "-y", "-i", str(image_path),
                    "-vf", vf, "-an",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
                    str(seg_path),
                ]
            completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if completed.returncode != 0:
                raise NovelError(f"장면 영상 렌더링 실패(Cut {scene.index}): {completed.stderr[-300:]}")
            segment_paths.append(seg_path)

        concat_list = tmp_dir / "concat.txt"
        concat_list.write_text(
            "\n".join(f"file '{seg.name}'" for seg in segment_paths) + "\n",
            encoding="utf-8",
        )
        bgm_path = next(
            (novel_dir / name for name in ("bgm.mp3", "bgm.wav", "bgm.m4a") if (novel_dir / name).is_file()),
            None,
        )
        total_duration = sum(s.duration for s in episode.scenes)

        if bgm_path is not None:
            audio_fade = max(0.0, total_duration - 1.2)
            cmd = [
                ffmpeg_bin, "-y",
                "-f", "concat", "-safe", "0", "-i", str(concat_list),
                "-stream_loop", "-1", "-i", str(bgm_path),
                "-t", f"{total_duration:.2f}",
                "-filter:a", f"volume=0.35,afade=t=out:st={audio_fade:.2f}:d=1.2",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                str(destination),
            ]
        else:
            cmd = [
                ffmpeg_bin, "-y",
                "-f", "concat", "-safe", "0", "-i", str(concat_list),
                "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-t", f"{total_duration:.2f}",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "96k",
                "-shortest", "-movflags", "+faststart",
                str(destination),
            ]
        completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise NovelError(f"최종 MP4 병합 실패: {completed.stderr[-300:]}")

    return destination


def build_novel_episodes(
    novel_dir: Path,
    output_dir: Path,
    *,
    episode_numbers: list[int] | None = None,
    aspect: str = "9:16",
    render_video: bool = True,
    subtitle_overlay: bool = True,
    fps: int = 24,
) -> tuple[list[Path], list[dict[str, object]]]:
    if aspect not in ASPECT_SIZES:
        raise NovelError(f"지원하지 않는 화면 비율입니다: {aspect} (지원: 9:16, 16:9, 1:1)")
    bible = load_series_bible(novel_dir)
    episode_paths = discover_episode_files(novel_dir, episode_numbers)

    all_files: list[Path] = []
    results: list[dict[str, object]] = []

    for ep_path in episode_paths:
        ep_num_guess = 0
        match = re.search(r"(\d+)", ep_path.stem)
        if match:
            ep_num_guess = int(match.group(1))
        try:
            episode = load_episode(ep_path, bible)
            ep_out = output_dir / f"ep{episode.number:02d}"
            ep_out.mkdir(parents=True, exist_ok=True)
            ep_files: list[Path] = []

            image_prompt_lines = [
                f"[Cut {scene.index:02d} | {scene.title} | {scene.duration:.1f}s]\n"
                f"{full_image_prompt(scene, bible, aspect)}"
                for scene in episode.scenes
            ]
            motion_prompt_lines = [
                f"[Cut {scene.index:02d} | {scene.title}]\n"
                f"{full_motion_prompt(scene, aspect)}"
                for scene in episode.scenes
            ]
            narration_lines = [
                f"[Cut {scene.index:02d} | {scene.duration:.1f}s] {scene.narration}"
                for scene in episode.scenes
            ]

            text_outputs = {
                "원고.md": format_manuscript_markdown(episode, bible),
                "원고.txt": format_manuscript_text(episode, bible),
                "스토리보드.md": format_storyboard_markdown(episode, bible, aspect),
                "이미지_프롬프트.txt": "\n\n".join(image_prompt_lines) + "\n",
                "영상전환_프롬프트.txt": "\n\n".join(motion_prompt_lines) + "\n",
                "나레이션_대본.txt": "\n\n".join(narration_lines) + "\n",
                "자막.srt": format_srt(episode),
            }
            for filename, content in text_outputs.items():
                target = ep_out / filename
                target.write_text(content, encoding="utf-8")
                ep_files.append(target)

            scenes_dir = ep_out / "scenes"
            scene_images: list[Path] = []
            for scene in episode.scenes:
                img_path = scenes_dir / f"scene_{scene.index:02d}.png"
                render_scene_image(
                    scene,
                    episode,
                    bible,
                    novel_dir,
                    img_path,
                    aspect=aspect,
                    subtitle_overlay=subtitle_overlay,
                )
                scene_images.append(img_path)
                ep_files.append(img_path)

            video_path: Path | None = None
            if render_video:
                video_path = ep_out / "영상.mp4"
                render_episode_video(
                    episode,
                    scene_images,
                    novel_dir,
                    video_path,
                    aspect=aspect,
                    fps=fps,
                )
                ep_files.append(video_path)

            all_files.extend(ep_files)
            results.append(
                {
                    "episode": episode.number,
                    "title": episode.title,
                    "success": True,
                    "scene_count": len(episode.scenes),
                    "video": str(video_path) if video_path else None,
                    "files": [str(p) for p in ep_files],
                }
            )
        except Exception as exc:
            results.append(
                {
                    "episode": ep_num_guess,
                    "success": False,
                    "reason": str(exc),
                }
            )
    return all_files, results


def save_plain_episode(
    novel_dir: Path,
    episode_number: int,
    title: str,
    body_text: str,
) -> Path:
    if episode_number < 1:
        raise NovelError("회차 번호는 1 이상이어야 합니다.")
    clean_title = title.strip() or f"{episode_number}화"
    clean_body = body_text.strip()
    if not clean_body:
        raise NovelError("소설 본문을 입력해 주세요.")
    novel_dir.mkdir(parents=True, exist_ok=True)
    target = novel_dir / f"ep{episode_number:02d}.md"
    target.write_text(
        f"# {episode_number}화. {clean_title}\n\n{clean_body}\n",
        encoding="utf-8",
    )
    return target
