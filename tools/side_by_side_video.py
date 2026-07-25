"""Source footage next to the smoothed twin, with a colour key.

    tools/.venv/Scripts/python tools/side_by_side_video.py test_6

Renders the twin panel (Blender, headless, via `tools/blender/render_compare.py`) and stacks
it beside the original clip with ffmpeg, writing `data/render/<id>_video_vs_twin.mp4`.

Why the text lives here and not in Blender
------------------------------------------
An earlier version drew the labels as 3D text in the scene. Text in 3D has to be placed
before the camera is framed and then re-checked against it, and the first attempt put the
words outside the frame — invisible, but still casting a shadow onto the floor. Text drawn on
the finished frame is placed in pixels, cannot be occluded by a limb, and covers both panels,
only one of which Blender renders at all.

The colour key is the point of this view. Most frames of test_6 have no racket detection, so
the racket is a forearm prior and shows red; without the key that reads as a tracking failure
rather than as the honest confidence signal it is. Swatch colours are the linear values from
`tools/blender/racket_viewer.py`, converted here to sRGB so they match what Blender renders.
"""

import argparse
import glob
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent

# Linear RGB, copied from racket_viewer.COLOUR_* / render_compare.BODY_COLOUR.
KEY = [
    ((0.42, 0.58, 0.85), "body - pose estimated from the video"),
    ((0.15, 0.85, 0.25), "racket - position and rotation measured"),
    ((1.00, 0.65, 0.05), "racket - rotation estimated"),
    ((0.90, 0.15, 0.15), "racket - position estimated from the arm"),
]
KEY_HEADER = "COLOUR KEY"
TITLES = ("SOURCE VIDEO", "SMOOTHED TWIN")

FONT_BOLD = "C:/Windows/Fonts/arialbd.ttf"
FONT_REGULAR = "C:/Windows/Fonts/arial.ttf"


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("clip", nargs="?", default="test_6", help="clip id, e.g. test_6")
    p.add_argument("--video", default=None, help="source clip (default data/raw/<clip>.mp4)")
    p.add_argument("--twin", default=None,
                   help="pre-rendered twin panel; skips Blender when given")
    p.add_argument("--blend", default=None,
                   help="scene to render (default models/smpl/<clip>_compare.blend)")
    p.add_argument("--out", default=None,
                   help="default data/render/<clip>_video_vs_twin.mp4")
    p.add_argument("--res", default="1280x720", help="size of ONE panel")
    p.add_argument("--blender", default=None, help="path to blender.exe")
    p.add_argument("--azimuth", type=float, default=0.0, help="passed to render_compare")
    p.add_argument("--elevation", type=float, default=8.0, help="passed to render_compare")
    p.add_argument("--keep-panel", action="store_true", help="keep the intermediate render")
    return p.parse_args(argv)


def find_blender(explicit):
    """Newest installed Blender, unless told otherwise."""
    if explicit:
        return explicit
    if os.environ.get("BLENDER"):
        return os.environ["BLENDER"]
    found = glob.glob(r"C:\Program Files\Blender Foundation\Blender *\blender.exe")
    if not found:
        raise SystemExit("blender.exe not found -- pass --blender or set BLENDER")
    return sorted(found)[-1]


def srgb_hex(linear):
    """Blender stores object colours linear; ffmpeg wants what the eye sees.

    Skipping this conversion makes every swatch noticeably darker than the thing it labels --
    the mid-green racket would get a near-black key entry.
    """
    out = []
    for c in linear:
        c = max(0.0, min(1.0, c))
        s = 12.92 * c if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055
        out.append(round(s * 255))
    return "0x{:02X}{:02X}{:02X}".format(*out)


def esc(text):
    """Escape a string for use inside a drawtext filter argument."""
    for a, b in (("\\", r"\\"), (":", r"\:"), ("'", r"\'"), ("%", r"\%"), (",", r"\,")):
        text = text.replace(a, b)
    return text


def esc_path(path):
    """A Windows font path inside a filtergraph: the drive colon has to be escaped."""
    return str(path).replace("\\", "/").replace(":", r"\:")


def render_panel(args, blend, panel, width, height):
    blender = find_blender(args.blender)
    script = REPO / "tools" / "blender" / "render_compare.py"
    cmd = [blender, "-b", str(blend), "-P", str(script), "--",
           "--bodies", "B",
           "--out", str(panel.relative_to(REPO)).replace("\\", "/"),
           "--res", f"{width}x{height}",
           "--azimuth", str(args.azimuth), "--elevation", str(args.elevation)]
    print("+", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    for line in proc.stdout.splitlines():
        if line.startswith("render_compare:"):
            print(" ", line)
    if proc.returncode != 0 or not panel.exists():
        sys.stderr.write(proc.stdout[-4000:] + "\n" + proc.stderr[-2000:] + "\n")
        raise SystemExit("blender render failed")


def build_filter(width, height):
    """The whole overlay chain, in pixels, for a two-panel frame of 2*width x height."""
    right = width
    title_size = max(16, round(height * 0.047))
    key_size = max(11, round(height * 0.026))
    pad = max(8, round(height * 0.022))
    line_h = round(key_size * 1.6)
    swatch = key_size
    box_w = round(width * 0.46)
    box_h = pad * 2 + line_h * (len(KEY) + 1)
    box_x, box_y = right + pad, height - pad - box_h
    text_x = box_x + pad + swatch + round(swatch * 0.6)

    parts = [
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[left]",
        f"[1:v]scale={width}:{height},setsar=1[right]",
        "[left][right]hstack=inputs=2[stacked]",
    ]

    chain = [f"drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}:color=black@0.5:t=fill"]
    y = box_y + pad
    chain.append(f"drawtext=fontfile='{esc_path(FONT_BOLD)}':text='{esc(KEY_HEADER)}'"
                 f":x={box_x + pad}:y={y}:fontsize={key_size}:fontcolor=white")
    for linear, label in KEY:
        y += line_h
        chain.append(f"drawbox=x={box_x + pad}:y={y + 2}:w={swatch}:h={swatch}"
                     f":color={srgb_hex(linear)}@1:t=fill")
        chain.append(f"drawtext=fontfile='{esc_path(FONT_REGULAR)}':text='{esc(label)}'"
                     f":x={text_x}:y={y}:fontsize={key_size}:fontcolor=white")

    # `w` inside drawtext is the full stacked width, so quarter and three-quarter centre the
    # titles over their own panels whatever --res is.
    for i, title in enumerate(TITLES):
        centre = "w/4" if i == 0 else "3*w/4"
        chain.append(f"drawtext=fontfile='{esc_path(FONT_BOLD)}':text='{esc(title)}'"
                     f":x={centre}-text_w/2:y={pad}:fontsize={title_size}:fontcolor=white"
                     f":box=1:boxcolor=black@0.5:boxborderw={round(pad * 0.6)}")

    parts.append("[stacked]" + ",".join(chain) + "[out]")
    return ";".join(parts)


def main(argv=None):
    args = parse_args(argv)
    width, height = (int(v) for v in args.res.lower().split("x"))
    video = pathlib.Path(args.video) if args.video else REPO / "data/raw" / f"{args.clip}.mp4"
    blend = (pathlib.Path(args.blend) if args.blend
             else REPO / "models/smpl" / f"{args.clip}_compare.blend")
    out = (pathlib.Path(args.out) if args.out
           else REPO / "data/render" / f"{args.clip}_video_vs_twin.mp4")
    panel = pathlib.Path(args.twin) if args.twin else \
        REPO / "data/render" / f"_{args.clip}_twin_panel.mp4"

    if not video.exists():
        raise SystemExit(f"source clip not found: {video}")
    for font in (FONT_BOLD, FONT_REGULAR):
        if not pathlib.Path(font).exists():
            raise SystemExit(f"font not found: {font}")

    out.parent.mkdir(parents=True, exist_ok=True)
    if args.twin is None:
        if not blend.exists():
            raise SystemExit(f"scene not found: {blend}")
        render_panel(args, blend, panel, width, height)

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-i", str(video), "-i", str(panel),
           "-filter_complex", build_filter(width, height),
           "-map", "[out]", "-an",
           "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", str(out)]
    print("+ ffmpeg ->", out)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr[-4000:] + "\n")
        raise SystemExit("ffmpeg composite failed")

    if args.twin is None and not args.keep_panel:
        panel.unlink(missing_ok=True)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
