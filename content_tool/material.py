"""Material loading and strict validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

REQUIRED_FIELDS = (
    "주제", "방향", "검색어", "훅", "핵심", "숫자", "소제목",
    "소제목별_내용", "출처링크", "태그",
)


class MaterialError(ValueError):
    """A concise validation error for a material JSON file."""


@dataclass(frozen=True)
class Material:
    topic: str
    angle: str
    keywords: list[str]
    hook: str
    key_points: list[str]
    numbers: list[dict[str, str]]
    headings: list[str]
    sections: list[list[str]]
    source_links: list[str]
    tags: list[str]

    @property
    def primary_keyword(self) -> str:
        return self.keywords[0]


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MaterialError(f"'{name}'은 비어 있지 않은 문자열이어야 합니다.")
    return value.strip()


def _text_list(value: Any, name: str, minimum: int = 1) -> list[str]:
    if not isinstance(value, list) or len(value) < minimum:
        raise MaterialError(f"'{name}'은 {minimum}개 이상의 문자열 목록이어야 합니다.")
    return [_text(item, name) for item in value]


def load_material(path: Path) -> Material:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MaterialError(f"재료 파일이 없습니다: {path}") from exc
    except json.JSONDecodeError as exc:
        raise MaterialError(f"JSON 형식 오류({exc.lineno}행): {path.name}") from exc
    if not isinstance(data, dict):
        raise MaterialError("재료 파일의 최상위 값은 객체여야 합니다.")
    missing = [field for field in REQUIRED_FIELDS if field not in data]
    if missing:
        raise MaterialError(f"필수 항목이 없습니다: {', '.join(missing)}")

    headings = _text_list(data["소제목"], "소제목", 4)
    if len(headings) > 6:
        raise MaterialError("'소제목'은 4~6개여야 합니다.")
    raw_sections = data["소제목별_내용"]
    if not isinstance(raw_sections, list) or len(raw_sections) != len(headings):
        raise MaterialError("'소제목별_내용' 수는 '소제목' 수와 같아야 합니다.")
    sections = [
        _text_list(section, f"소제목별_내용[{index}]", 1)
        for index, section in enumerate(raw_sections, 1)
    ]

    key_points = _text_list(data["핵심"], "핵심", 3)
    if len(key_points) > 5:
        raise MaterialError("'핵심'은 3~5개여야 합니다.")
    numbers = data["숫자"]
    if not isinstance(numbers, list):
        raise MaterialError("'숫자'는 목록이어야 합니다.")
    clean_numbers: list[dict[str, str]] = []
    for index, number in enumerate(numbers, 1):
        if not isinstance(number, dict):
            raise MaterialError(f"'숫자[{index}]'는 객체여야 합니다.")
        clean_numbers.append(
            {
                "항목": _text(number.get("항목"), f"숫자[{index}].항목"),
                "값": _text(number.get("값"), f"숫자[{index}].값"),
                "출처": _text(number.get("출처"), f"숫자[{index}].출처"),
            }
        )
    source_links = _text_list(data["출처링크"], "출처링크")
    if any(urlparse(link).scheme not in {"http", "https"} for link in source_links):
        raise MaterialError("'출처링크'는 http 또는 https 주소여야 합니다.")
    return Material(
        topic=_text(data["주제"], "주제"),
        angle=_text(data["방향"], "방향"),
        keywords=_text_list(data["검색어"], "검색어"),
        hook=_text(data["훅"], "훅"),
        key_points=key_points,
        numbers=clean_numbers,
        headings=headings,
        sections=sections,
        source_links=source_links,
        tags=_text_list(data["태그"], "태그"),
    )
