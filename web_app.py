#!/usr/bin/env python3
"""Local-only web interface for the deterministic content pipeline."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, abort, redirect, render_template_string, request, send_file, url_for

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
<title>블로그와 SNS 글 만들기</title>
<style>
body{font-family:sans-serif;max-width:1040px;margin:32px auto;padding:0 20px;color:#102a43}
section{border:1px solid #ccd9e2;border-radius:14px;padding:20px;margin:18px 0}
label{display:block;margin:10px 0 4px}.text{width:95%;padding:9px}
button{padding:12px 18px;border:0;border-radius:8px;background:#126e5b;color:white;font-weight:bold}
.checks label{display:inline-block;margin-right:18px}.checks input{width:auto}
small{display:block;color:#526b7a;margin-top:5px}details{margin-top:14px}
pre{white-space:pre-wrap;background:#f1f6f8;padding:16px;border-radius:10px}
.images{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
img{width:100%;border-radius:8px}.ok{color:#087f5b}.fail{color:#c92a2a}
</style></head><body>
<h1>블로그와 SNS 글·그림 만들기</h1>
<p>위에서부터 차례대로 누르면 됩니다. 어려운 설정은 바꾸지 않아도 됩니다.</p>
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
{% if result %}<section><h2 class="{{ 'ok' if result.success else 'fail' }}">
{{ '잘 만들었습니다!' if result.success else '만들지 못했습니다' }}</h2>
{% if result.reason %}<p>이유: {{ result.reason }}</p>{% endif %}
{% if body %}<h3>블로그 글 미리보기</h3><button onclick="navigator.clipboard.writeText(
document.getElementById('body').innerText)">블로그 글 복사하기</button><pre id="body">{{ body }}</pre>{% endif %}
{% if images %}<h3>그림 미리보기·받기</h3><div class="images">{% for image in images %}
<a href="{{ url_for('download', name=image.rel) }}?download=1"><img src="{{ url_for('download', name=image.rel) }}"
alt="{{ image.name }}"><small>{{ image.name }}</small></a>{% endfor %}</div>{% endif %}
</section>{% endif %}</body></html>"""


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@app.get("/")
def index():
    output = app.config["LAST_OUTPUT"]
    body = None
    images: list[dict[str, str]] = []
    if output and Path(output).exists():
        body_files = sorted(Path(output).glob("blog*/본문.txt"))
        if body_files:
            body = "\n\n".join(path.read_text(encoding="utf-8") for path in body_files)
        images = [
            {"name": path.name, "rel": str(path.relative_to(output))}
            for path in sorted(Path(output).glob("blog*/**/*.png"))
        ]
    return render_template_string(
        PAGE,
        keywords=",".join(DEFAULT_KEYWORDS),
        channels=",".join(DEFAULT_CHANNELS),
        result=app.config["LAST_RESULT"],
        body=body,
        images=images,
    )


@app.post("/run")
def run_pipeline():
    try:
        output = Path(request.form["out"]).expanduser().resolve()
        if request.form["action"] == "youtube":
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


@app.get("/download/<path:name>")
def download(name: str):
    output = app.config["LAST_OUTPUT"]
    if not output:
        abort(404)
    root = Path(output).resolve()
    candidate = (root / name).resolve()
    if root not in candidate.parents or candidate.suffix.lower() != ".png" or not candidate.is_file():
        abort(404)
    return send_file(candidate, as_attachment=request.args.get("download") == "1")


if __name__ == "__main__":
    load_dotenv()
    app.run(host="127.0.0.1", port=5000, debug=False)
