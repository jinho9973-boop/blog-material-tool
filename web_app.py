#!/usr/bin/env python3
"""Local-only web interface for the deterministic content and novel-video pipeline."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, abort, redirect, render_template_string, request, send_file, url_for

from content_tool.novel import build_novel_episodes, save_plain_episode
from content_tool.pipeline import build_blogs
from content_tool.youtube import (
    DEFAULT_CHANNELS,
    DEFAULT_KEYWORDS,
    collect_top_issues,
    load_sample_issues,
    write_top_issues,
)

app = Flask(__name__)
app.config["LAST_OUTPUT"] = None
app.config["LAST_RESULT"] = None

PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>블로그·SNS·소설 영상 만들기</title>
<style>
body{font-family:sans-serif;max-width:1080px;margin:32px auto;padding:0 20px;color:#102a43}
section{border:1px solid #ccd9e2;border-radius:14px;padding:20px;margin:18px 0}
label{display:block;margin:10px 0 4px}.text,textarea{width:96%;padding:9px;font-family:inherit}
textarea{min-height:170px;line-height:1.55}
button{padding:11px 17px;border:0;border-radius:8px;background:#126e5b;color:white;font-weight:bold;cursor:pointer;margin-right:6px}
button.sub{background:#2c5282}
.checks label{display:inline-block;margin-right:18px}.checks input{width:auto}
small{display:block;color:#526b7a;margin-top:5px}details{margin-top:14px}
pre{white-space:pre-wrap;background:#f1f6f8;padding:16px;border-radius:10px;max-height:380px;overflow:auto}
.images{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
.videos{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px;margin:12px 0}
img,video{width:100%;border-radius:8px;background:#09131f}.ok{color:#087f5b}.fail{color:#c92a2a}
</style></head><body>
<h1>블로그·SNS 및 소설 이미지·영상 만들기</h1>
<p>원하는 작업 칸에서 버튼을 누르면 글·이미지·프롬프트·MP4 영상을 한 번에 정리합니다.</p>

<section><h2>① 오늘의 유튜브 이야기 찾기</h2><form method="post" action="/run">
<input type="hidden" name="action" value="youtube"><label>찾은 내용을 저장할 폴더</label>
<input class="text" name="out" value="오늘폴더" required>
<small>보통 ‘오늘폴더’ 그대로 두면 됩니다.</small>
<label>얼마나 오래된 영상까지 볼까요?</label>
<select name="days" autocomplete="off"><option value="1" selected>최근 하루</option><option value="3">최근 3일</option>
<option value="7">최근 7일</option></select>
<details><summary>자세한 설정 보기</summary><label>특정 주제만 찾을 때 쓰는 말</label>
<input class="text" name="keywords" value="{{ keywords }}" placeholder="비워 두면 모든 주제를 찾습니다">
<small>기본값은 공란입니다. 사회·사건·날씨·연예·국제·경제를 모두 찾습니다.</small>
<label>뉴스 채널</label>
<input class="text" name="source_channels" value="{{ channels }}"></details>
<p><button>유튜브 이야기 찾기</button>
<button name="sample_mode" value="1">예시 데이터로 연습하기</button></p></form></section>

<section><h2>② 블로그와 SNS 완성하기</h2><form method="post" action="/run">
<input type="hidden" name="action" value="material"><label>재료 파일이 있는 폴더</label>
<input class="text" name="material" value="오늘폴더" required>
<small>이 폴더 안에 blog1.json과 blog2.json을 넣으세요.</small>
<label>완성 파일을 저장할 폴더</label>
<input class="text" name="out" value="오늘폴더/결과" required>
<label>어느 블로그를 만들까요?</label><div class="checks">
<label><input type="checkbox" name="blogs" value="1" checked> 블로그 1</label>
<label><input type="checkbox" name="blogs" value="2" checked> 블로그 2</label></div>
<label>어느 SNS 글을 만들까요?</label><div class="checks">
<label><input type="checkbox" name="channels" value="threads" checked> 쓰레드</label>
<label><input type="checkbox" name="channels" value="x" checked> X</label>
<label><input type="checkbox" name="channels" value="instagram" checked> 인스타그램</label>
<label><input type="checkbox" name="channels" value="clip" checked> 네이버 클립</label></div><p>
<button>글과 그림 모두 만들기</button> <button name="images_only" value="1">그림만 다시 만들기</button>
</p></form></section>

<section><h2>③ 소설 → 이미지·영상 전환하기</h2><form method="post" action="/run">
<input type="hidden" name="action" value="novel">
<label>소설 원고 폴더</label>
<input class="text" name="novel" value="novels/wall_3pm" required>
<small>기본값 ‘novels/wall_3pm’에 장편 《벽 너머, 오후 세 시》 설정집과 1~5화가 들어 있습니다. AI 생성 이미지를 넣으려면 이 폴더 아래 bg/ep03_scene_02.png 형태로 넣으세요.</small>
<label>변환할 회차 번호 (비워 두면 전체 회차)</label>
<input class="text" name="episodes" value="3" placeholder="예: 1,2,3 또는 공란(전체)">
<label>화면 비율</label>
<select name="aspect" autocomplete="off">
<option value="9:16" selected>9:16 세로 (쇼츠·릴스·틱톡)</option>
<option value="16:9">16:9 가로 (유튜브·웹드라마)</option>
<option value="1:1">1:1 정사각형</option>
</select>
<label>완성 파일 저장 폴더</label>
<input class="text" name="out" value="결과/소설영상" required>
<p><button>소설 이미지 + MP4 영상 만들기</button>
<button class="sub" name="no_video" value="1">원고·프롬프트·장면 이미지만 만들기</button></p></form>

<details><summary><strong>새 회차 소설 원고 직접 쓰고 바로 변환하기</strong></summary>
<form method="post" action="/run">
<input type="hidden" name="action" value="novel_write">
<label>소설 폴더</label>
<input class="text" name="novel" value="novels/wall_3pm" required>
<label>회차 번호</label>
<input class="text" name="episode_number" type="number" min="1" value="6" required>
<label>회차 제목</label>
<input class="text" name="episode_title" placeholder="예: 찻잔 너머로 스친 손끝" required>
<label>소설 본문 (문단 사이는 빈 줄로 구분하면 자동으로 장면을 나눕니다)</label>
<textarea name="episode_body" placeholder="여기에 소설 본문을 적으면 장면 분할, 캐릭터 일관성 이미지 프롬프트, I2V 영상 프롬프트, 자막, MP4 영상까지 자동으로 만들어 줍니다." required></textarea>
<label>화면 비율</label>
<select name="aspect" autocomplete="off"><option value="9:16" selected>9:16 세로</option><option value="16:9">16:9 가로</option></select>
<label>완성 파일 저장 폴더</label>
<input class="text" name="out" value="결과/소설영상" required>
<p><button>원고 저장 후 이미지·영상 바로 만들기</button></p>
</form></details></section>

{% if result %}<section><h2 class="{{ 'ok' if result.success else 'fail' }}">
{{ '잘 만들었습니다!' if result.success else '만들지 못했습니다' }}</h2>
{% if result.reason %}<p>이유: {{ result.reason }}</p>{% endif %}
{% if videos %}<h3>완성된 MP4 영상 미리보기·받기</h3><div class="videos">{% for video in videos %}
<div><video controls preload="metadata" src="{{ url_for('media', name=video.rel) }}"></video>
<small><a href="{{ url_for('media', name=video.rel) }}?download=1">{{ video.rel }} 내려받기</a></small></div>
{% endfor %}</div>{% endif %}
{% if body %}<h3>블로그 글 미리보기</h3><button onclick="navigator.clipboard.writeText(
document.getElementById('body').innerText)">블로그 글 복사하기</button><pre id="body">{{ body }}</pre>{% endif %}
{% if novel_body %}<h3>소설 원고 미리보기</h3><button onclick="navigator.clipboard.writeText(
document.getElementById('novel_body').innerText)">소설 원고 복사하기</button><pre id="novel_body">{{ novel_body }}</pre>{% endif %}
{% if image_prompts %}<h3>AI 이미지 생성 프롬프트 (Grok · Midjourney · Flux)</h3>
<button class="sub" onclick="navigator.clipboard.writeText(document.getElementById('img_p').innerText)">이미지 프롬프트 복사하기</button>
<pre id="img_p">{{ image_prompts }}</pre>{% endif %}
{% if motion_prompts %}<h3>이미지 → 영상(I2V) 전환 프롬프트 (Kling · Runway · Grok Video)</h3>
<button class="sub" onclick="navigator.clipboard.writeText(document.getElementById('vid_p').innerText)">영상 전환 프롬프트 복사하기</button>
<pre id="vid_p">{{ motion_prompts }}</pre>{% endif %}
{% if images %}<h3>그림 미리보기·받기</h3><div class="images">{% for image in images %}
<a href="{{ url_for('download', name=image.rel) }}?download=1"><img src="{{ url_for('download', name=image.rel) }}"
alt="{{ image.name }}"><small>{{ image.rel }}</small></a>{% endfor %}</div>{% endif %}
</section>{% endif %}</body></html>"""


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _join_files(paths: list[Path]) -> str | None:
    if not paths:
        return None
    return "\n\n".join(path.read_text(encoding="utf-8") for path in paths)


@app.get("/")
def index():
    output = app.config["LAST_OUTPUT"]
    body = None
    novel_body = None
    image_prompts = None
    motion_prompts = None
    images: list[dict[str, str]] = []
    videos: list[dict[str, str]] = []
    if output and Path(output).exists():
        out_root = Path(output)
        body = _join_files(sorted(out_root.glob("blog*/본문.txt")))
        novel_body = _join_files(sorted(out_root.glob("ep*/원고.txt")))
        image_prompts = _join_files(sorted(out_root.glob("ep*/이미지_프롬프트.txt")))
        motion_prompts = _join_files(sorted(out_root.glob("ep*/영상전환_프롬프트.txt")))
        images = [
            {"name": path.name, "rel": str(path.relative_to(out_root))}
            for path in sorted([*out_root.glob("blog*/**/*.png"), *out_root.glob("ep*/**/*.png")])
        ]
        videos = [
            {"name": path.name, "rel": str(path.relative_to(out_root))}
            for path in sorted(out_root.glob("ep*/*.mp4"))
        ]
    return render_template_string(
        PAGE,
        keywords=",".join(DEFAULT_KEYWORDS),
        channels=",".join(DEFAULT_CHANNELS),
        result=app.config["LAST_RESULT"],
        body=body,
        novel_body=novel_body,
        image_prompts=image_prompts,
        motion_prompts=motion_prompts,
        images=images,
        videos=videos,
    )


@app.post("/run")
def run_pipeline():
    try:
        output = Path(request.form["out"]).expanduser().resolve()
        action = request.form["action"]
        if action == "youtube":
            sample_mode = request.form.get("sample_mode") == "1"
            if sample_mode:
                issues = load_sample_issues(
                    Path(__file__).resolve().parent / "sample_youtube.json"
                )
            else:
                issues = collect_top_issues(
                    os.getenv("YOUTUBE_API_KEY", ""),
                    _csv(request.form["keywords"]),
                    channels=_csv(request.form["source_channels"]),
                    channel_cache=output / "channels.json",
                    days=int(request.form.get("days", "1")),
                )
            files = write_top_issues(issues, output)
            if not sample_mode:
                files.insert(0, output / "channels.json")
            result = {"success": True, "files": [str(path) for path in files]}
        elif action in {"novel", "novel_write"}:
            novel_dir = Path(request.form["novel"]).expanduser().resolve()
            aspect = request.form.get("aspect", "9:16")
            if action == "novel_write":
                ep_num = int(request.form["episode_number"])
                save_plain_episode(
                    novel_dir,
                    ep_num,
                    request.form.get("episode_title", ""),
                    request.form.get("episode_body", ""),
                )
                ep_numbers: list[int] | None = [ep_num]
                render_video = True
            else:
                raw_eps = request.form.get("episodes", "").strip()
                ep_numbers = [int(item) for item in _csv(raw_eps)] if raw_eps else None
                render_video = request.form.get("no_video") != "1"
            files, details = build_novel_episodes(
                novel_dir,
                output,
                episode_numbers=ep_numbers,
                aspect=aspect,
                render_video=render_video,
            )
            reasons = [str(item.get("reason")) for item in details if not item["success"]]
            result = {
                "success": all(bool(item["success"]) for item in details),
                "files": [str(path) for path in files],
                "episodes": details,
                "reason": "; ".join(reasons) if reasons else None,
            }
        else:
            material = Path(request.form["material"]).expanduser().resolve()
            blogs = [int(value) for value in request.form.getlist("blogs")]
            channels = set(request.form.getlist("channels"))
            if not blogs:
                raise ValueError("만들 블로그를 하나 이상 골라 주세요.")
            if not channels and request.form.get("images_only") != "1":
                raise ValueError("만들 SNS를 하나 이상 골라 주세요.")
            files, details = build_blogs(
                material,
                output,
                blogs,
                channels,
                images_only=request.form.get("images_only") == "1",
            )
            result = {
                "success": all(bool(item["success"]) for item in details),
                "files": [str(path) for path in files],
                "blogs": details,
            }
    except Exception as exc:
        result = {"success": False, "files": [], "reason": str(exc)}
    app.config["LAST_OUTPUT"] = str(output) if "output" in locals() else None
    app.config["LAST_RESULT"] = result
    return redirect(url_for("index"))


def _safe_output_file(name: str, allowed_suffixes: set[str]) -> Path:
    output = app.config["LAST_OUTPUT"]
    if not output:
        abort(404)
    root = Path(output).resolve()
    candidate = (root / name).resolve()
    if root not in candidate.parents or candidate.suffix.lower() not in allowed_suffixes or not candidate.is_file():
        abort(404)
    return candidate


@app.get("/download/<path:name>")
def download(name: str):
    candidate = _safe_output_file(name, {".png"})
    return send_file(candidate, as_attachment=request.args.get("download") == "1")


@app.get("/media/<path:name>")
def media(name: str):
    candidate = _safe_output_file(name, {".mp4", ".srt"})
    return send_file(candidate, as_attachment=request.args.get("download") == "1")


if __name__ == "__main__":
    load_dotenv()
    app.run(host="127.0.0.1", port=5000, debug=False)
