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
    write_top_issues,
)

app = Flask(__name__)
app.config["LAST_OUTPUT"] = None
app.config["LAST_RESULT"] = None

PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>블로그·SNS 콘텐츠 정리</title>
<style>
body{font-family:sans-serif;max-width:1040px;margin:32px auto;padding:0 20px;color:#102a43}
section{border:1px solid #ccd9e2;border-radius:14px;padding:20px;margin:18px 0}
label{display:block;margin:10px 0 4px}input{width:95%;padding:9px}button{padding:10px 16px}
pre{white-space:pre-wrap;background:#f1f6f8;padding:16px;border-radius:10px}
.images{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}
img{width:100%;border-radius:8px}.ok{color:#087f5b}.fail{color:#c92a2a}
</style></head><body>
<h1>블로그·SNS 콘텐츠 정리</h1>
<section><h2>유튜브 인기 이슈</h2><form method="post" action="/run">
<input type="hidden" name="action" value="youtube"><label>출력 폴더</label>
<input name="out" value="오늘폴더" required><label>검색어</label>
<input name="keywords" value="{{ keywords }}"><label>뉴스 채널</label>
<input name="source_channels" value="{{ channels }}"><p><button>이슈 10개 만들기</button></p></form></section>
<section><h2>블로그·SNS 결과</h2><form method="post" action="/run">
<input type="hidden" name="action" value="material"><label>재료 폴더</label>
<input name="material" value="오늘폴더" required><label>출력 폴더</label>
<input name="out" value="오늘폴더/결과" required><label>블로그 번호</label>
<input name="blogs" value="1,2"><label>채널</label>
<input name="channels" value="threads,x,instagram,clip"><p>
<button>전체 결과 만들기</button> <button name="images_only" value="1">그림만 다시 만들기</button>
</p></form></section>
{% if result %}<section><h2 class="{{ 'ok' if result.success else 'fail' }}">
{{ '성공' if result.success else '실패' }}</h2>
{% if result.reason %}<p>{{ result.reason }}</p>{% endif %}
{% if body %}<h3>본문 미리보기</h3><button onclick="navigator.clipboard.writeText(
document.getElementById('body').innerText)">본문 복사</button><pre id="body">{{ body }}</pre>{% endif %}
{% if images %}<h3>PNG 미리보기·다운로드</h3><div class="images">{% for image in images %}
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
            issues = collect_top_issues(
                os.getenv("YOUTUBE_API_KEY", ""),
                _csv(request.form["keywords"]),
                channels=_csv(request.form["source_channels"]),
                channel_cache=output / "channels.json",
            )
            files = write_top_issues(issues, output)
            files.insert(0, output / "channels.json")
            result = {"success": True, "files": [str(path) for path in files]}
        else:
            material = Path(request.form["material"]).expanduser().resolve()
            blogs = [int(value) for value in _csv(request.form["blogs"])]
            channels = set(_csv(request.form["channels"]))
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
