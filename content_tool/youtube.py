"""YouTube issue collection without generative AI."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

API_URL = "https://www.googleapis.com/youtube/v3"
DEFAULT_KEYWORDS = ("경제", "주식", "연금", "환율", "부동산", "지원금")
DEFAULT_CHANNELS = ("KBS News", "SBS 뉴스", "MBCNEWS", "JTBC News", "연합뉴스TV")
POLITICS_TERMS = (
    "정당", "대통령", "국회", "선거", "총선", "대선", "국회의원", "민주당",
    "국민의힘", "정치", "탄핵", "특검", "이재명", "윤석열",
)
STOPWORDS = {
    "영상", "오늘", "이번", "대한", "관련", "이유", "진짜", "뉴스", "속보",
    "공개", "정리", "알아보기", "그리고", "하지만", "에서", "으로", "하는",
    "하면", "입니다", "있습니다", "없습니다",
}


class YouTubeError(RuntimeError):
    """A concise, user-facing YouTube collection error."""


def _request(resource: str, params: dict[str, Any], api_key: str) -> dict[str, Any]:
    try:
        response = requests.get(
            f"{API_URL}/{resource}",
            params={**params, "key": api_key},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        detail = ""
        if exc.response is not None:
            try:
                detail = exc.response.json().get("error", {}).get("message", "")
            except ValueError:
                detail = exc.response.text[:200]
        raise YouTubeError(detail or str(exc)) from exc


def _chunks(values: list[str], size: int = 50) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _normalized_channel_name(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _resolve_channel_ids(
    api_key: str,
    channel_names: Iterable[str],
    cache_path: Path | None,
) -> dict[str, str]:
    cached: dict[str, str] = {}
    if cache_path and cache_path.exists():
        try:
            value = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                cached = {
                    str(name): str(channel_id)
                    for name, channel_id in value.items()
                    if isinstance(channel_id, str) and channel_id.startswith("UC")
                }
        except (OSError, json.JSONDecodeError):
            cached = {}
    resolved: dict[str, str] = {}
    for name in channel_names:
        if name in cached:
            resolved[name] = cached[name]
            continue
        result = _request(
            "search",
            {
                "part": "snippet",
                "type": "channel",
                "q": name,
                "maxResults": 10,
                "regionCode": "KR",
                "relevanceLanguage": "ko",
            },
            api_key,
        )
        exact = next(
            (
                item
                for item in result.get("items", [])
                if _normalized_channel_name(item.get("snippet", {}).get("title", ""))
                == _normalized_channel_name(name)
            ),
            None,
        )
        channel_id = exact and exact.get("id", {}).get("channelId")
        if not channel_id:
            raise YouTubeError(f"채널을 정확히 찾지 못했습니다: {name}")
        resolved[name] = channel_id
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(resolved, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return resolved


def _video_ids(
    api_key: str,
    keywords: Iterable[str],
    now: datetime,
    channel_names: Iterable[str] = DEFAULT_CHANNELS,
    cache_path: Path | None = None,
    days: int = 1,
) -> set[str]:
    channels = _resolve_channel_ids(api_key, channel_names, cache_path)
    details = _request(
        "channels",
        {
            "part": "contentDetails",
            "id": ",".join(channels.values()),
            "maxResults": 50,
        },
        api_key,
    )
    playlists = [
        item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        for item in details.get("items", [])
    ]
    cutoff = now - timedelta(days=days)
    keyword_values = tuple(word.casefold() for word in keywords)
    ids: set[str] = set()
    for playlist_id in filter(None, playlists):
        page_token: str | None = None
        for _ in range(30):
            params: dict[str, Any] = {
                "part": "snippet,contentDetails",
                "playlistId": playlist_id,
                "maxResults": 50,
            }
            if page_token:
                params["pageToken"] = page_token
            result = _request("playlistItems", params, api_key)
            reached_old_video = False
            for item in result.get("items", []):
                snippet = item.get("snippet", {})
                published_value = (
                    item.get("contentDetails", {}).get("videoPublishedAt")
                    or snippet.get("publishedAt")
                )
                if not published_value:
                    continue
                if _parse_time(published_value) < cutoff:
                    reached_old_video = True
                    continue
                text = f"{snippet.get('title', '')} {snippet.get('description', '')}".casefold()
                if not keyword_values or any(word in text for word in keyword_values):
                    video_id = item.get("contentDetails", {}).get("videoId")
                    if video_id:
                        ids.add(video_id)
            page_token = result.get("nextPageToken")
            if reached_old_video or not page_token:
                break
    return ids


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _tokens(title: str) -> set[str]:
    words = re.findall(r"[가-힣A-Za-z0-9]{2,}", title.lower())
    return {word for word in words if word not in STOPWORDS and not word.isdigit()}


def _similar(left: dict[str, Any], right: dict[str, Any]) -> bool:
    a, b = set(left["_tokens"]), set(right["_tokens"])
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= 0.34 or len(a & b) >= 2


def _duration_days(published_at: datetime, now: datetime) -> float:
    return max((now - published_at).total_seconds() / 86_400, 1 / 24)


def collect_top_issues(
    api_key: str,
    keywords: Iterable[str] = DEFAULT_KEYWORDS,
    *,
    channels: Iterable[str] = DEFAULT_CHANNELS,
    channel_cache: Path | None = None,
    days: int = 1,
    limit: int = 10,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Collect and rank Korean videos, keeping one representative per topic."""
    if days < 1:
        raise YouTubeError("조회 기간은 1일 이상이어야 합니다.")
    if not api_key:
        raise YouTubeError(
            "유튜브 API 키가 없습니다. .env 파일에 YOUTUBE_API_KEY를 넣어 주세요."
        )
    now = now or datetime.now(timezone.utc)
    ids = sorted(_video_ids(api_key, keywords, now, channels, channel_cache, days))
    videos: list[dict[str, Any]] = []
    for batch in _chunks(ids):
        payload = _request(
            "videos",
            {"part": "snippet,statistics", "id": ",".join(batch), "maxResults": 50},
            api_key,
        )
        for item in payload.get("items", []):
            snippet = item["snippet"]
            title = snippet["title"]
            searchable = " ".join(
                [
                    title,
                    snippet.get("description", ""),
                    " ".join(snippet.get("tags", [])),
                ]
            ).lower()
            if any(term.lower() in searchable for term in POLITICS_TERMS):
                continue
            stats = item.get("statistics", {})
            published = _parse_time(snippet["publishedAt"])
            views = int(stats.get("viewCount", 0))
            videos.append(
                {
                    "제목": title,
                    "채널명": snippet["channelTitle"],
                    "조회수": views,
                    "좋아요수": (
                        int(stats["likeCount"]) if "likeCount" in stats else None
                    ),
                    "올린날짜": snippet["publishedAt"],
                    "주소": f"https://www.youtube.com/watch?v={item['id']}",
                    "일평균조회수": math.floor(views / _duration_days(published, now)),
                    "_tokens": sorted(_tokens(title)),
                }
            )
    videos.sort(key=lambda video: video["일평균조회수"], reverse=True)
    selected: list[dict[str, Any]] = []
    for video in videos:
        group = next((previous for previous in selected if _similar(video, previous)), None)
        if group is not None:
            group["_related"].append({"제목": video["제목"], "주소": video["주소"]})
            continue
        if len(selected) < limit:
            video["_related"] = []
            selected.append(video)
    for rank, video in enumerate(selected, 1):
        video.pop("_tokens", None)
        related = video.pop("_related")
        video["묶인영상수"] = 1 + len(related)
        video["관련영상"] = related
        video["순위"] = rank
    return selected


def write_top_issues(issues: list[dict[str, Any]], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "youtube_top10.json"
    md_path = output_dir / "youtube_top10.md"
    json_path.write_text(
        json.dumps(issues, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# 유튜브 인기 이슈 10",
        "",
        "|순위|주제 대표 영상|묶인 영상|채널|조회수|좋아요|일평균 조회수|올린 날짜|주소|",
        "|---:|---|---:|---|---:|---:|---:|---|---|",
    ]
    for item in issues:
        title = item["제목"].replace("|", "｜")
        likes = "-" if item["좋아요수"] is None else f"{item['좋아요수']:,}"
        lines.append(
            f"|{item['순위']}|{title}|{item['묶인영상수']}|{item['채널명']}|{item['조회수']:,}|"
            f"{likes}|{item['일평균조회수']:,}|{item['올린날짜'][:10]}|"
            f"[보기]({item['주소']})|"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return [json_path, md_path]
