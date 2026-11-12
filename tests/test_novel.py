from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from content_tool.novel import (
    build_novel_episodes,
    load_episode,
    load_series_bible,
    save_plain_episode,
)

ROOT = Path(__file__).resolve().parent.parent
NOVEL_DIR = ROOT / "novels" / "wall_3pm"


def test_wall_3pm_series_bible_and_episodes_load() -> None:
    bible = load_series_bible(NOVEL_DIR)
    assert bible.title == "벽 너머, 오후 세 시"
    assert "서연" in bible.characters
    assert "빅터" in bible.characters
    for ep_num in range(1, 7):
        ep = load_episode(NOVEL_DIR / f"ep0{ep_num}.json", bible)
        assert ep.number == ep_num
        assert len(ep.paragraphs) >= 10
        assert len(ep.scenes) >= 3


def test_novel_builds_images_prompts_srt_and_mp4(tmp_path: Path) -> None:
    out_dir = tmp_path / "novel_out"
    files, results = build_novel_episodes(
        NOVEL_DIR,
        out_dir,
        episode_numbers=[3],
        aspect="9:16",
        render_video=True,
        fps=12,
    )
    assert results[0]["success"] is True
    assert results[0]["title"] == "소나기가 벗겨 낸 윤곽"
    ep_out = out_dir / "ep03"
    assert (ep_out / "원고.md").is_file()
    assert (ep_out / "스토리보드.md").is_file()
    assert (ep_out / "자막.srt").is_file()
    assert (ep_out / "영상.mp4").is_file()
    assert (ep_out / "영상.mp4").stat().st_size > 10_000
    assert (ep_out / "영상.mp4") in files

    img_prompts = (ep_out / "이미지_프롬프트.txt").read_text(encoding="utf-8")
    motion_prompts = (ep_out / "영상전환_프롬프트.txt").read_text(encoding="utf-8")
    assert "35-year-old Korean married woman" in img_prompts
    assert "Image-to-Video" in motion_prompts

    with Image.open(ep_out / "scenes" / "scene_02.png") as scene_img:
        assert scene_img.size == (1080, 1920)


def test_plain_markdown_episode_auto_splits_and_uses_custom_bg(tmp_path: Path) -> None:
    work_novel = tmp_path / "custom_novel"
    work_novel.mkdir()
    (work_novel / "series_bible.json").write_text(
        (NOVEL_DIR / "series_bible.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    bg_dir = work_novel / "bg"
    bg_dir.mkdir()
    Image.new("RGB", (600, 900), "#334E68").save(bg_dir / "ep06_scene_01.png", "PNG")

    save_plain_episode(
        work_novel,
        6,
        "찻잔 너머로 스친 손끝",
        (
            "수요일 오후 세 시, 베란다 블라인드 사이로 햇살이 길게 드리워졌다.\n\n"
            "윤서연은 찻잔을 내려놓으며 강태주의 시선을 애써 피했다.\n\n"
            "얇은 니트 너머로 가쁜 숨결이 스치자 거실 공기가 무겁게 가라앉았다."
        ),
    )
    out_dir = tmp_path / "out"
    _, results = build_novel_episodes(
        work_novel,
        out_dir,
        episode_numbers=[6],
        aspect="16:9",
        render_video=False,
    )
    assert results[0]["success"] is True
    with Image.open(out_dir / "ep06" / "scenes" / "scene_01.png") as img:
        assert img.size == (1920, 1080)


def test_cli_and_web_novel_workflow(capsys, tmp_path: Path) -> None:
    import run
    from web_app import app

    cli_out = tmp_path / "cli_out"
    code = run.main(
        [
            "--소설",
            str(NOVEL_DIR),
            "--회차",
            "1",
            "--영상생략",
            "--저장폴더",
            str(cli_out),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["성공"] is True
    assert payload["회차결과"][0]["회차"] == 1

    app.config.update(TESTING=True, LAST_OUTPUT=None, LAST_RESULT=None)
    web_out = tmp_path / "web_out"
    client = app.test_client()
    response = client.post(
        "/run",
        data={
            "action": "novel",
            "novel": str(NOVEL_DIR),
            "episodes": "3",
            "aspect": "9:16",
            "out": str(web_out),
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "이미지 프롬프트 복사하기".encode() in response.data
    assert "영상 전환 프롬프트 복사하기".encode() in response.data
    mp4_resp = client.get("/media/ep03/영상.mp4")
    assert mp4_resp.status_code == 200
    assert mp4_resp.mimetype == "video/mp4"
