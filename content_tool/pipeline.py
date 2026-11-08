"""Pipeline orchestration shared by CLI and web UI."""

from __future__ import annotations

from pathlib import Path

from .images import compose_images
from .material import load_material
from .writers import write_text_outputs

SUPPORTED_CHANNELS = {"threads", "x", "instagram", "clip"}


def build_blogs(
    material_dir: Path,
    output_dir: Path,
    blog_numbers: list[int],
    channels: set[str],
    *,
    images_only: bool = False,
) -> tuple[list[Path], list[dict[str, object]]]:
    unknown = channels - SUPPORTED_CHANNELS
    if unknown:
        raise ValueError(f"지원하지 않는 채널: {', '.join(sorted(unknown))}")
    files: list[Path] = []
    results: list[dict[str, object]] = []
    for number in blog_numbers:
        try:
            material = load_material(material_dir / f"blog{number}.json")
            blog_output = output_dir / f"blog{number}"
            blog_files: list[Path] = []
            if not images_only:
                blog_files.extend(write_text_outputs(material, blog_output, channels))
            blog_files.extend(
                compose_images(
                    material,
                    number,
                    material_dir,
                    blog_output,
                    instagram="instagram" in channels or images_only,
                )
            )
            files.extend(blog_files)
            results.append(
                {
                    "blog": number,
                    "success": True,
                    "files": [str(path) for path in blog_files],
                }
            )
        except Exception as exc:  # each blog reports its own failure
            results.append({"blog": number, "success": False, "reason": str(exc)})
    return files, results
