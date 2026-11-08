from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from content_tool.images import compose_images
from content_tool.material import MaterialError, load_material
from content_tool.writers import title_candidates, write_text_outputs, x_posts
from content_tool.youtube import collect_top_issues, load_sample_issues, write_top_issues

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
    home = client.get("/")
    assert '<option value="1" selected>최근 하루</option>'.encode() in home.data
    response = client.post(
        "/run",
        data={
            "action": "material",
            "material": str(ROOT / "examples"),
            "out": str(output),
            "blogs": ["1", "2"],
            "channels": ["threads", "x", "instagram", "clip"],
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "블로그 글 복사하기".encode() in response.data
    assert (output / "blog2" / "본문.md").is_file()
    assert (output / "blog2" / "clip" / "대본.txt").is_file()
    image_response = client.get("/download/blog1/썸네일.png")
    assert image_response.status_code == 200
    assert image_response.mimetype == "image/png"


def test_korean_cli_alias_and_json(capsys, tmp_path: Path) -> None:
    import run

    exit_code = run.main(
        [
            "--그림다시",
            str(ROOT / "examples"),
            "--블로그",
            "1",
            "--저장폴더",
            str(tmp_path / "result"),
        ]
    )
    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert output["성공"] is True
    assert output["블로그결과"][0]["블로그"] == 1


def test_sample_youtube_runs_without_api_key(capsys, tmp_path: Path, monkeypatch) -> None:
    import run

    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    sample = ROOT / "sample_youtube.json"
    issues = load_sample_issues(
        sample,
        now=datetime(2026, 11, 8, 17, tzinfo=timezone.utc),
    )
    assert len(issues) == 10
    assert issues[0]["묶인영상수"] == 2
    assert all("대통령" not in item["제목"] for item in issues)

    output_dir = tmp_path / "youtube"
    exit_code = run.main(
        [
            "--유튜브",
            "--유튜브예시",
            str(sample),
            "--저장폴더",
            str(output_dir),
        ]
    )
    result = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert result["성공"] is True
    assert result["수집개수"] == 10
    assert (output_dir / "youtube_top10.json").is_file()
    assert (output_dir / "youtube_top10.md").is_file()
