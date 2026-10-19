"""Render the actual shared SVG screens and encode a captioned prototype tour.

This is an authored walkthrough, not a recording of live vendor execution.
Needs PyMuPDF and ffmpeg. Run render-seo-walkthrough.mjs first.
"""
import json
import pathlib
import shutil
import subprocess
import sys

import fitz

frames = pathlib.Path(sys.argv[1]).resolve()
output = pathlib.Path(__file__).resolve().parents[1] / "public/showcase/seo-audit"
scenes = json.loads((frames / "scenes.json").read_text())
for source in sorted(frames.glob("scene-*.svg")):
    svg = fitz.open(stream=source.read_bytes(), filetype="svg")
    pdf = fitz.open("pdf", svg.convert_to_pdf())
    pdf[0].get_pixmap(alpha=False).save(source.with_suffix(".png"))

cursor_svg = '<svg xmlns="http://www.w3.org/2000/svg" width="48" height="52"><circle cx="17" cy="17" r="16" fill="#b39bff" opacity="0.24"/><path d="M17 17 l0 25 7 -7 5 12 5 -2 -5 -11 10 -1 Z" fill="#fff" stroke="#101428" stroke-width="2"/></svg>'
cursor = fitz.open(stream=cursor_svg.encode(), filetype="svg")
cursor_pdf = fitz.open("pdf", cursor.convert_to_pdf())
cursor_pdf[0].get_pixmap(alpha=True).save(frames / "cursor.png")
concat = "".join(f"file '{(frames / f'scene-{index:02}.png').as_posix()}'\nduration 6\n" for index in range(len(scenes)))
concat += f"file '{(frames / f'scene-{len(scenes) - 1:02}.png').as_posix()}'\n"
(frames / "frames.txt").write_text(concat)

def movement(axis):
    expressions = []
    for index, scene in enumerate(scenes):
        previous = scenes[index - 1]["pointer"][axis] if index else [1150, 700][axis]
        target = scene["pointer"][axis]
        expressions.append(f"{previous - 17}+({target - previous})*min(1,max(0,(t-{index * 6})/1.2))")
    expression = expressions[-1]
    for index in reversed(range(len(expressions) - 1)):
        expression = f"if(lt(t,{(index + 1) * 6}),{expressions[index]},{expression})"
    return expression

filters = f"[0:v]fps=24,format=yuv420p[screen];[screen][1:v]overlay=x='{movement(0)}':y='{movement(1)}':eval=frame:shortest=1,format=yuv420p[video]"
subprocess.run([
    "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
    "-f", "concat", "-safe", "0", "-i", str(frames / "frames.txt"),
    "-loop", "1", "-i", str(frames / "cursor.png"),
    "-filter_complex", filters, "-map", "[video]", "-t", str(len(scenes) * 6),
    "-c:v", "libx264", "-preset", "fast", "-crf", "27", "-pix_fmt", "yuv420p",
    "-movflags", "+faststart", "-metadata", "title=AURA SEO audit prototype walkthrough",
    "-metadata", "comment=Real anonymized Screaming Frog evidence; explicitly simulated Semrush, Ahrefs and Sitebulb. No live execution.",
    str(output / "walkthrough.mp4"),
], check=True)
shutil.copyfile(frames / "scene-02.png", output / "poster.png")
print(json.dumps({"seconds": len(scenes) * 6, "video_bytes": (output / "walkthrough.mp4").stat().st_size}))
