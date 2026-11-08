"""Deterministic blog and social-channel writers."""

from __future__ import annotations

import re
from pathlib import Path

from .material import Material


def _sentences(lines: list[str]) -> str:
    return "\n\n".join(line.strip() for line in lines)


def blog_markdown(material: Material) -> str:
    lines = ["# 핵심정리", ""]
    lines.extend(f"- {point}" for point in material.key_points)
    for heading, paragraphs in zip(material.headings, material.sections, strict=True):
        lines.extend(["", f"## ■ {heading}", "", _sentences(paragraphs)])
    lines.extend(["", "## 출처", ""])
    lines.extend(f"- {link}" for link in material.source_links)
    return "\n".join(lines).strip() + "\n"


def blog_plain_text(material: Material) -> str:
    lines = ["핵심정리", *[f"• {point}" for point in material.key_points]]
    for heading, paragraphs in zip(material.headings, material.sections, strict=True):
        lines.extend(["", f"■ {heading}", "", _sentences(paragraphs)])
    lines.extend(["", "출처", *material.source_links])
    return "\n".join(lines).strip() + "\n"


def title_candidates(material: Material) -> list[str]:
    keyword = material.primary_keyword
    topic = material.topic
    endings = (
        f"{topic}, 왜 지금 확인해야 할까?",
        f"{topic}, 무엇이 달라졌을까?",
        f"{topic}, 놓치기 쉬운 핵심은?",
        f"{topic}, 내게도 해당될까?",
        f"{topic}, 확인 전에 알아둘 점은?",
    )
    return [f"{keyword} | {ending}" for ending in endings]


def _hashtags(tags: list[str], limit: int | None = None) -> str:
    clean = ["#" + re.sub(r"\s+", "", tag.lstrip("#")) for tag in tags]
    return " ".join(clean[:limit])


def threads_text(material: Material) -> tuple[str, str]:
    replacements = (
        ("해야 합니다.", "해야 해."),
        ("할 수 있습니다.", "할 수 있어."),
        ("있습니다.", "있어."),
        ("없습니다.", "없어."),
        ("됩니다.", "돼."),
        ("합니다.", "해."),
        ("입니다.", "이야."),
        ("달라집니다.", "달라져."),
    )

    def friendly(text: str) -> str:
        for formal, casual in replacements:
            if text.endswith(formal):
                return text[:-len(formal)] + casual
        return text

    body = [friendly(material.hook), "", *[friendly(point) for point in material.key_points[:5]]]
    return "\n".join(body) + "\n", "자세한 내용과 출처는 블로그 링크에서 확인해 봐.\n"


def _fit_x(text: str) -> str:
    if len(text) <= 280:
        return text
    return text[:277].rstrip() + "…"


def x_posts(material: Material) -> list[str]:
    tag = _hashtags(material.tags, 2)
    first = _fit_x(f"{material.hook}\n\n{material.key_points[0]}\n{tag}")
    continuation = [
        _fit_x(f"{heading}\n{section[0]}")
        for heading, section in zip(material.headings[:3], material.sections[:3], strict=True)
    ]
    return [first, *continuation]


def instagram_caption(material: Material) -> str:
    points = "\n\n".join(f"• {point}" for point in material.key_points)
    tags = list(dict.fromkeys([*material.tags, material.topic, *material.keywords]))
    generic = ["경제정보", "생활정보", "정보정리", "오늘의이슈", "재테크공부",
               "쉬운설명", "핵심정리", "블로그", "콘텐츠추천", "한눈에보기"]
    tags = list(dict.fromkeys([*tags, *generic]))[:15]
    return f"{material.hook}\n\n{points}\n\n{_hashtags(tags)}\n"


def clip_script(material: Material) -> str:
    lines = [material.hook, *material.key_points[:4], "출처는 본문에서 확인하세요."]
    return "\n".join(lines) + "\n"


def clip_prompt(material: Material) -> str:
    return (
        "Vertical 9:16 editorial video, modern Korean lifestyle and finance mood, "
        "navy and mint color palette, calm camera movement, clean realistic scene, "
        "no text, no letters, no logos, no watermark."
    )


def image_prompts(material: Material, card_count: int = 2) -> list[str]:
    base = (
        "Clean editorial illustration about personal finance and everyday decisions, "
        "modern Korean setting, navy and mint palette, balanced empty space for overlay, "
        "no text, no letters, no numbers, no logos, no watermark"
    )
    prompts = [f"Thumbnail: {base}, dramatic focal lighting."]
    prompts.extend(
        f"Summary card {index}: {base}, simple visual metaphor, soft lighting."
        for index in range(1, card_count + 1)
    )
    prompts.extend(
        f"Instagram slide {index}: {base}, vertical composition."
        for index in range(1, max(4, min(6, len(material.headings))) + 1)
    )
    return prompts


def write_text_outputs(material: Material, output_dir: Path, channels: set[str]) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []

    common = {
        "본문.md": blog_markdown(material),
        "본문.txt": blog_plain_text(material),
        "제목후보.txt": "\n".join(title_candidates(material)) + "\n",
        "태그.txt": _hashtags(material.tags) + "\n",
        "prompts.txt": "\n\n".join(
            image_prompts(material, min(2, max(1, len(material.numbers))))
        ) + "\n",
    }
    for name, content in common.items():
        path = output_dir / name
        path.write_text(content, encoding="utf-8")
        files.append(path)

    if "threads" in channels:
        folder = output_dir / "threads"
        folder.mkdir(exist_ok=True)
        body, reply = threads_text(material)
        for name, content in {"본문.txt": body, "답글.txt": reply}.items():
            path = folder / name
            path.write_text(content, encoding="utf-8")
            files.append(path)

    if "x" in channels:
        folder = output_dir / "x"
        folder.mkdir(exist_ok=True)
        posts = x_posts(material)
        path = folder / "게시물.txt"
        path.write_text(
            "\n\n--- 이어쓰기 ---\n\n".join(posts) + "\n",
            encoding="utf-8",
        )
        files.append(path)

    if "instagram" in channels:
        folder = output_dir / "instagram"
        folder.mkdir(exist_ok=True)
        path = folder / "캡션.txt"
        path.write_text(instagram_caption(material), encoding="utf-8")
        files.append(path)

    if "clip" in channels:
        folder = output_dir / "clip"
        folder.mkdir(exist_ok=True)
        values = {
            "대본.txt": clip_script(material),
            "자막.txt": clip_script(material),
            "제목.txt": title_candidates(material)[0] + "\n",
            "태그.txt": _hashtags(material.tags) + "\n",
            "영상프롬프트.txt": clip_prompt(material) + "\n",
        }
        for name, content in values.items():
            path = folder / name
            path.write_text(content, encoding="utf-8")
            files.append(path)
    return files
