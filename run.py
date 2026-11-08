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
        description="네이버 블로그·SNS 콘텐츠 자동 정리 도구"
    )
    modes = command.add_mutually_exclusive_group(required=True)
    modes.add_argument("--youtube", action="store_true", help="유튜브 인기 이슈 수집")
    modes.add_argument("--material", type=Path, help="blog1.json 등이 있는 폴더")
    modes.add_argument("--compose", type=Path, help="이미지만 다시 만드는 재료 폴더")
    command.add_argument("--out", type=Path, help="결과 폴더")
    command.add_argument("--blogs", default="1,2", help="블로그 번호(예: 1,2)")
    command.add_argument(
        "--channels",
        default="threads,x,instagram,clip",
        help="생성 채널(쉼표 구분)",
    )
    command.add_argument(
        "--keywords",
        default=",".join(DEFAULT_KEYWORDS),
        help="유튜브 검색 키워드(쉼표 구분)",
    )
    command.add_argument(
        "--source-channels",
        default=",".join(DEFAULT_CHANNELS),
        help="유튜브 원본 채널명(쉼표 구분)",
    )
    return command


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _result(success: bool, files: list[Path], **extra: object) -> dict[str, object]:
    return {
        "success": success,
        "files": [str(path) for path in files],
        **extra,
    }


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
            )
            files = write_top_issues(issues, args.out)
            files.insert(0, args.out / "channels.json")
            output = _result(True, files, count=len(issues))
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
            output = _result(success, files, blogs=blog_results)
    except Exception as exc:
        output = _result(False, [], reason=str(exc))
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
