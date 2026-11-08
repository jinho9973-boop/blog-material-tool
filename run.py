#!/usr/bin/env python3
"""Command-line entry point for the content production pipeline."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from content_tool.pipeline import build_blogs
from content_tool.youtube import (
    DEFAULT_CHANNELS,
    DEFAULT_KEYWORDS,
    collect_top_issues,
    write_top_issues,
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(
        description="네이버 블로그와 SNS 글·그림을 만드는 도구"
    )
    modes = command.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--youtube", "--유튜브", dest="youtube", action="store_true",
        help="최근 유튜브 인기 이야기를 모읍니다",
    )
    modes.add_argument(
        "--material", "--재료", dest="material", type=Path,
        help="blog1.json과 blog2.json이 있는 폴더",
    )
    modes.add_argument(
        "--compose", "--그림다시", dest="compose", type=Path,
        help="글은 그대로 두고 그림만 다시 만듭니다",
    )
    command.add_argument(
        "--out", "--저장폴더", dest="out", type=Path, help="완성 파일을 넣을 폴더"
    )
    command.add_argument(
        "--blogs", "--블로그", dest="blogs", default="1,2",
        help="만들 블로그 번호(예: 1,2)",
    )
    command.add_argument(
        "--channels", "--채널", dest="channels",
        default="threads,x,instagram,clip",
        help="만들 SNS 종류(쉼표로 나눔)",
    )
    command.add_argument(
        "--keywords", "--검색어", dest="keywords",
        default=",".join(DEFAULT_KEYWORDS),
        help="유튜브에서 찾을 말(쉼표로 나눔)",
    )
    command.add_argument(
        "--source-channels", "--뉴스채널", dest="source_channels",
        default=",".join(DEFAULT_CHANNELS),
        help="영상을 가져올 뉴스 채널(쉼표로 나눔)",
    )
    command.add_argument(
        "--days", "--기간", dest="days",
        type=int,
        default=1,
        help="며칠 전 영상까지 볼지 정합니다(기본: 1일)",
    )
    return command


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _result(success: bool, files: list[Path], **extra: object) -> dict[str, object]:
    return {
        "성공": success,
        "파일목록": [str(path) for path in files],
        **extra,
    }


def _korean_blog_results(results: list[dict[str, object]]) -> list[dict[str, object]]:
    translated: list[dict[str, object]] = []
    for item in results:
        value = {"블로그": item["blog"], "성공": item["success"]}
        if item["success"]:
            value["파일목록"] = item["files"]
        else:
            value["실패이유"] = item["reason"]
        translated.append(value)
    return translated


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parser().parse_args(argv)
    try:
        if args.youtube:
            if args.out is None:
                raise ValueError("--youtube에는 --out이 필요합니다.")
            issues = collect_top_issues(
                os.getenv("YOUTUBE_API_KEY", ""),
                _csv(args.keywords),
                channels=_csv(args.source_channels),
                channel_cache=args.out / "channels.json",
                days=args.days,
            )
            files = write_top_issues(issues, args.out)
            files.insert(0, args.out / "channels.json")
            output = _result(True, files, 수집개수=len(issues))
        else:
            material_dir = args.material or args.compose
            assert material_dir is not None
            output_dir = args.out or material_dir / "결과"
            try:
                blogs = [int(item) for item in _csv(args.blogs)]
            except ValueError as exc:
                raise ValueError("--blogs는 쉼표로 구분한 숫자여야 합니다.") from exc
            channels = set(_csv(args.channels))
            files, blog_results = build_blogs(
                material_dir,
                output_dir,
                blogs,
                channels,
                images_only=args.compose is not None,
            )
            success = all(bool(item["success"]) for item in blog_results)
            output = _result(
                success,
                files,
                블로그결과=_korean_blog_results(blog_results),
            )
    except Exception as exc:
        output = _result(False, [], 실패이유=str(exc))
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["성공"] else 1


if __name__ == "__main__":
    sys.exit(main())
