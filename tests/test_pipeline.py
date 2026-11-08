from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from content_tool.images import compose_images
from content_tool.material import MaterialError, load_material
from content_tool.writers import title_candidates, write_text_outputs, x_posts
from content_tool.youtube import collect_top_issues, write_top_issues

ROOT = Path(__file__).resolve().parent.parent


def test_material_text_and_images(tmp_path: Path) -> None:
    material = load_material(ROOT / "examples" / "blog1.json")
    output = tmp_path / "blog1"
    files = write_text_outputs(
        material, output, {"threads", "x", "instagram", "clip"}
    )
    files += compose_images(material, 1, tmp_path, output)

    assert len(title_candidates(material)) == 5
    assert all(title.startswith(material.primary_keyword) for title in title_candidates(material))
    assert all(len(post) <= 280 for post in x_posts(material))
    assert (output / "본문.md") in files
    assert "106만9,034명" not in (output / "본문.md").read_text(encoding="utf-8")
    with Image.open(output / "썸네일.png") as image:
        assert image.size == (1080, 1080)
    with Image.open(output / "instagram" / "카드뉴스1.png") as image:
        assert image.size == (1080, 1350)


def test_invalid_material_reports_missing_field(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"주제": "테스트"}', encoding="utf-8")
    try:
        load_material(path)
    except MaterialError as exc:
        assert "필수 항목" in str(exc)
    else:
        raise AssertionError("invalid material was accepted")


def test_youtube_filters_politics_and_groups_similar(monkeypatch, tmp_path: Path) -> None:
    import content_tool.youtube as youtube

    monkeypatch.setattr(youtube, "_video_ids", lambda *_args: {"a", "b", "c", "d"})
    items = [
        {
            "id": "a",
            "snippet": {
                "title": "환율 급등 원화 전망",
                "channelTitle": "경제채널",
                "publishedAt": "2026-11-07T00:00:00Z",
            },
            "statistics": {"viewCount": "1000", "likeCount": "10"},
        },
        {
            "id": "b",
            "snippet": {
                "title": "환율 급등 원화 분석",
                "channelTitle": "머니채널",
                "publishedAt": "2026-11-07T00:00:00Z",
            },
            "statistics": {"viewCount": "900"},
        },
        {
            "id": "c",
            "snippet": {
                "title": "국민연금 수령 방법",
                "channelTitle": "생활채널",
                "publishedAt": "2026-11-06T00:00:00Z",
            },
            "statistics": {"viewCount": "800", "likeCount": "8"},
        },
        {
            "id": "d",
            "snippet": {
                "title": "대통령 국회 정치 뉴스",
                "channelTitle": "뉴스채널",
                "publishedAt": "2026-11-07T00:00:00Z",
            },
            "statistics": {"viewCount": "5000"},
        },
    ]
    monkeypatch.setattr(youtube, "_request", lambda *_args, **_kwargs: {"items": items})
    result = collect_top_issues(
        "key",
        now=datetime(2026, 11, 8, tzinfo=timezone.utc),
    )

    assert [item["제목"] for item in result] == [
        "환율 급등 원화 전망",
        "국민연금 수령 방법",
    ]
    assert result[0]["좋아요수"] == 10
    assert result[0]["묶인영상수"] == 2
    paths = write_top_issues(result, tmp_path)
    assert json.loads(paths[0].read_text(encoding="utf-8"))[0]["순위"] == 1
    assert "|순위|주제 대표 영상|" in paths[1].read_text(encoding="utf-8")


def test_youtube_channel_ids_are_exact_and_cached(monkeypatch, tmp_path: Path) -> None:
    import content_tool.youtube as youtube

    calls = []

    def fake_request(resource, params, _api_key):
        calls.append((resource, params["q"]))
        return {
            "items": [
                {
                    "id": {"channelId": "UC_FAKE"},
                    "snippet": {"title": f"{params['q']} 다시보기"},
                },
                {
                    "id": {"channelId": "UC_EXACT"},
                    "snippet": {"title": params["q"]},
                },
            ]
        }

    monkeypatch.setattr(youtube, "_request", fake_request)
    cache = tmp_path / "channels.json"
    result = youtube._resolve_channel_ids("key", ["KBS News"], cache)
    assert result == {"KBS News": "UC_EXACT"}
    assert calls == [("search", "KBS News")]

    monkeypatch.setattr(
        youtube,
        "_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("cache missed")),
    )
    assert youtube._resolve_channel_ids("key", ["KBS News"], cache) == result


def test_web_preview_copy_and_png_download(tmp_path: Path) -> None:
    from web_app import app

    app.config.update(TESTING=True, LAST_OUTPUT=None, LAST_RESULT=None)
    output = tmp_path / "result"
    client = app.test_client()
    response = client.post(
        "/run",
        data={
            "action": "material",
            "material": str(ROOT / "examples"),
            "out": str(output),
            "blogs": "1",
            "channels": "threads,x,instagram,clip",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "본문 복사".encode() in response.data
    image_response = client.get("/download/blog1/썸네일.png")
    assert image_response.status_code == 200
    assert image_response.mimetype == "image/png"
