"""Render a terminal-style demo GIF from the project's *real* command output.

Each step actually runs (data generation, tests, the eval gate, the engine
eval); the captured stdout is what gets typed onto the fake terminal, so the GIF
can never drift from what the code really does. Output: ``docs/demo.gif``.

Run:  python scripts/make_demo_gif.py   (needs the ``demo`` extra: pillow)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "demo.gif"

# Terminal look
BG = (13, 17, 23)
FG = (201, 209, 217)
PROMPT = (63, 185, 80)
CMD = (121, 192, 255)
DIM = (139, 148, 158)
GOOD = (63, 185, 80)
WIDTH = 960
PAD = 24
LINE_H = 22
MAX_LINES = 26
FONT_SIZE = 15


def _font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "C:/Windows/Fonts/consola.ttf",
        "C:/Windows/Fonts/CascadiaMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Menlo.ttc",
    ]
    for c in candidates:
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size)
            except OSError:
                continue
    return ImageFont.load_default()


FONT = _font(FONT_SIZE)


def run(cmd: list[str], max_lines: int = 14) -> list[str]:
    """Run a command from the repo root and return trimmed stdout lines."""
    proc = subprocess.run(
        cmd, cwd=ROOT, capture_output=True, text=True, timeout=600
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    lines = [ln.rstrip() for ln in out.splitlines() if ln.strip()]
    if len(lines) > max_lines:
        lines = lines[:max_lines] + [f"... ({len(lines) - max_lines} more lines)"]
    return lines


class Line:
    def __init__(self, text: str, color, prompt: bool = False):
        self.text = text
        self.color = color
        self.prompt = prompt


def render_frame(lines: list[Line], partial_cmd: str | None = None) -> Image.Image:
    height = PAD * 2 + LINE_H * MAX_LINES
    img = Image.new("RGB", (WIDTH, height), BG)
    d = ImageDraw.Draw(img)
    # top window chrome
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([PAD + i * 20, 12, PAD + i * 20 + 12, 24], fill=c)
    d.text((WIDTH // 2 - 90, 12), "claims-audit-agent", font=FONT, fill=DIM)

    y = 40
    visible = lines[-(MAX_LINES - 1):] if len(lines) >= MAX_LINES else lines
    for ln in visible:
        x = PAD
        if ln.prompt:
            d.text((x, y), "$", font=FONT, fill=PROMPT)
            d.text((x + 16, y), ln.text, font=FONT, fill=ln.color)
        else:
            d.text((x, y), ln.text, font=FONT, fill=ln.color)
        y += LINE_H
    if partial_cmd is not None:
        d.text((PAD, y), "$", font=FONT, fill=PROMPT)
        d.text((PAD + 16, y), partial_cmd + "█", font=FONT, fill=CMD)
    return img


def color_for(text: str):
    t = text.lower()
    if "passed" in t or "gate passed" in t or "1.0" in t:
        return GOOD
    if "error" in t or "failed" in t:
        return (248, 81, 73)
    if text.startswith("|") or text.startswith("+"):
        return FG
    return FG


def build():
    steps = [
        ("python -m data.generate", ["python", "-m", "data.generate"], 12),
        ("pytest -q", [sys.executable, "-m", "pytest", "-q"], 3),
        ("python -m evals.gate", [sys.executable, "-m", "evals.gate"], 8),
        (
            "python -m evals.run_eval --arm engine",
            [sys.executable, "-m", "evals.run_eval", "--arm", "engine"],
            10,
        ),
    ]

    frames: list[Image.Image] = []
    durations: list[int] = []
    history: list[Line] = []

    def add(img, ms):
        frames.append(img)
        durations.append(ms)

    for display_cmd, argv, max_lines in steps:
        # type the command
        step = max(1, len(display_cmd) // 4)
        for i in range(0, len(display_cmd) + 1, step):
            add(render_frame(history, partial_cmd=display_cmd[:i]), 45)
        add(render_frame(history, partial_cmd=display_cmd), 350)
        history.append(Line(display_cmd, CMD, prompt=True))

        # run + reveal output
        out_lines = run(argv, max_lines=max_lines)
        for text in out_lines:
            history.append(Line(text, color_for(text)))
            add(render_frame(history), 120)
        add(render_frame(history), 900)

    # hold the final frame
    add(render_frame(history), 3000)

    OUT.parent.mkdir(exist_ok=True)
    frames[0].save(
        OUT,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    total = sum(durations) / 1000.0
    print(f"Wrote {OUT} — {len(frames)} frames, ~{total:.1f}s loop")


if __name__ == "__main__":
    build()
