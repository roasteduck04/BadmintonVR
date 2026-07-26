"""Four views of one clip in a 2x2 grid — the progress showcase.

    tools/.venv/Scripts/python tools/quad_video.py test_6

    +---------------------------+---------------------------+
    | RAW POSE                  | RAW POSE                  |
    | nodes + bone vectors      | nodes + bone vectors      |
    | no mesh                   | + mesh                    |
    +---------------------------+---------------------------+
    | SMOOTHED POSE             | SOURCE VIDEO              |
    | nodes + bone vectors      |                           |
    | + mesh                    |                           |
    +---------------------------+---------------------------+

The three twin panels are separate headless Blender renders of the compare scene
(`tools/blender/render_compare.py`), stacked with the source clip by ffmpeg. Titles and
the colour key are drawn here, on the finished frame, for the reasons in
`side_by_side_video.py` — which this shares its helpers with.

Why one camera for three panels
-------------------------------
`render_compare` solves its own framing from whatever it can see, so three independent
renders would put the twin at three slightly different sizes — the raw and smoothed
bodies do not sweep quite the same volume, and a body without its mesh samples a smaller
one still. Read side by side that reads as a rendering inconsistency rather than as the
pose difference the grid exists to show. So the first panel solves the camera, saves it,
and the other two inherit it; the stored framing is relative to its body's origin, so the
second twin (1.4 m away in the scene) still lands centred in its own panel.

Why the mesh panels are X-ray
-----------------------------
The joints and bone arrows live inside the body. Workbench's only transparency is the
global X-ray toggle, so a mesh panel that also shows nodes has to fade everything — the
racket's confidence colours included. The no-mesh panel is therefore the one to read the
racket colour from; the mesh panels are there for the pose, not the palette.
"""

import argparse
import pathlib
import subprocess
import sys

from side_by_side_video import (FONT_BOLD, FONT_REGULAR, KEY as RACKET_KEY, esc, esc_path,
                                find_blender, srgb_hex)

REPO = pathlib.Path(__file__).resolve().parent.parent

# Linear RGB, matching render_compare.BODY_COLOUR / JOINT_COLOUR / BONE_COLOUR.
KEY = [
    ((0.42, 0.58, 0.85), "body mesh - SMPL pose fitted to the video"),
    ((1.00, 0.95, 0.55), "joint node - one per SMPL-24 joint"),
    ((0.98, 0.98, 1.00), "bone vector - parent joint to child joint"),
] + list(RACKET_KEY[1:])          # the racket's three confidence colours
KEY_HEADER = "COLOUR KEY"

# (title lines, render_compare flags). None = the source clip, which Blender never sees.
PANELS = [
    (("RAW POSE", "nodes + bone vectors, no mesh"),
     ["--bodies", "A", "--no-mesh", "--joints", "--bones"]),
    (("RAW POSE", "nodes + bone vectors + mesh"),
     ["--bodies", "A", "--joints", "--bones"]),
    (("SMOOTHED POSE", "nodes + bone vectors + mesh"),
     ["--bodies", "B", "--joints", "--bones"]),
    (("SOURCE VIDEO", ""), None),
]


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("clip", nargs="?", default="test_6", help="clip id, e.g. test_6")
    p.add_argument("--video", default=None, help="source clip (default data/raw/<clip>.mp4)")
    p.add_argument("--blend", default=None,
                   help="scene to render (default models/smpl/<clip>_compare.blend)")
    p.add_argument("--out", default=None, help="default data/render/<clip>_quad.mp4")
    p.add_argument("--res", default="960x540", help="size of ONE panel")
    p.add_argument("--blender", default=None, help="path to blender.exe")
    p.add_argument("--azimuth", type=float, default=0.0, help="passed to render_compare")
    p.add_argument("--elevation", type=float, default=8.0, help="passed to render_compare")
    p.add_argument("--xray", type=float, default=0.5,
                   help="mesh-panel transparency; lower shows the nodes more clearly")
    p.add_argument("--keep-panels", action="store_true", help="keep the intermediate renders")
    return p.parse_args(argv)


def render_panel(args, blend, out, flags, width, height, camera, save_camera):
    """One headless Blender panel. `save_camera` on the first call, `camera` on the rest."""
    blender = find_blender(args.blender)
    script = REPO / "tools" / "blender" / "render_compare.py"
    cmd = [blender, "-b", str(blend), "-P", str(script), "--",
           "--out", str(out.relative_to(REPO)).replace("\\", "/"),
           "--res", f"{width}x{height}",
           "--no-floor",                      # X-ray dissolves it; keep all panels alike
           "--azimuth", str(args.azimuth), "--elevation", str(args.elevation)] + flags
    if "--no-mesh" not in flags:
        cmd += ["--xray", str(args.xray)]
    cmd += (["--save-camera", str(camera.relative_to(REPO)).replace("\\", "/")] if save_camera
            else ["--camera", str(camera.relative_to(REPO)).replace("\\", "/")])
    print("+", " ".join(str(c) for c in cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    finished = False
    for line in proc.stdout.splitlines():
        if line.startswith("render_compare:"):
            print(" ", line)
            finished |= line.startswith("render_compare: wrote")
    # Blender on Windows occasionally exits non-zero after a render that completed fine, so
    # the exit code alone would throw away three minutes of finished panels. `wrote` is only
    # printed once `render.render` has returned, which is the signal that actually matters.
    if not (finished and out.exists()):
        sys.stderr.write(proc.stdout[-4000:] + "\n" + proc.stderr[-2000:] + "\n")
        raise SystemExit(f"blender render failed for {out.name}")
    if proc.returncode != 0:
        print(f"  (blender exited {proc.returncode} after a completed render -- ignored)")


def build_filter(width, height):
    """The 2x2 stack plus every overlay, in pixels of the finished 2*width x 2*height frame."""
    title_size = max(15, round(height * 0.045))
    sub_size = max(11, round(height * 0.028))
    key_size = max(10, round(height * 0.025))
    pad = max(8, round(height * 0.022))
    line_h = round(key_size * 1.65)
    swatch = key_size
    box_w = round(width * 0.46)
    box_h = pad * 2 + line_h * (len(KEY) + 1)

    # The source clip is letterboxed into its cell; the Blender panels already fit exactly.
    parts = [f"[{i}:v]scale={width}:{height},setsar=1[p{i}]" for i in range(3)]
    parts.append(f"[3:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                 f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[p3]")
    parts.append("[p0][p1]hstack=inputs=2[top]")
    parts.append("[p2][p3]hstack=inputs=2[bottom]")
    parts.append("[top][bottom]vstack=inputs=2[grid]")

    chain = []
    # A hairline between the cells, so four dark panels do not read as one image.
    chain.append(f"drawbox=x={width - 1}:y=0:w=2:h=ih:color=white@0.25:t=fill")
    chain.append(f"drawbox=x=0:y={height - 1}:w=iw:h=2:color=white@0.25:t=fill")

    # Titles hug each panel's top-LEFT corner rather than centring: the twin renders
    # right of centre and its racket reaches the top of the frame on the smash, which a
    # centred caption sits squarely on top of.
    for i, (lines, _) in enumerate(PANELS):
        left = pad + (width if i % 2 else 0)
        top = pad + (height if i >= 2 else 0)
        chain.append(f"drawtext=fontfile='{esc_path(FONT_BOLD)}':text='{esc(lines[0])}'"
                     f":x={left}:y={top}:fontsize={title_size}:fontcolor=white"
                     f":box=1:boxcolor=black@0.55:boxborderw={round(pad * 0.5)}")
        if lines[1]:
            chain.append(f"drawtext=fontfile='{esc_path(FONT_REGULAR)}':text='{esc(lines[1])}'"
                         f":x={left}:y={top + round(title_size * 1.9)}"
                         f":fontsize={sub_size}:fontcolor=white@0.85"
                         f":box=1:boxcolor=black@0.55:boxborderw={round(pad * 0.4)}")

    # Bottom-left of the top-left panel: the twin sits right of centre in all three
    # renders, so this corner is the one reliably empty cell in the grid.
    box_x, box_y = pad, height - pad - box_h
    text_x = box_x + pad + swatch + round(swatch * 0.6)
    chain.append(f"drawbox=x={box_x}:y={box_y}:w={box_w}:h={box_h}:color=black@0.5:t=fill")
    y = box_y + pad
    chain.append(f"drawtext=fontfile='{esc_path(FONT_BOLD)}':text='{esc(KEY_HEADER)}'"
                 f":x={box_x + pad}:y={y}:fontsize={key_size}:fontcolor=white")
    for linear, label in KEY:
        y += line_h
        chain.append(f"drawbox=x={box_x + pad}:y={y + 2}:w={swatch}:h={swatch}"
                     f":color={srgb_hex(linear)}@1:t=fill")
        chain.append(f"drawtext=fontfile='{esc_path(FONT_REGULAR)}':text='{esc(label)}'"
                     f":x={text_x}:y={y}:fontsize={key_size}:fontcolor=white")

    parts.append("[grid]" + ",".join(chain) + "[out]")
    return ";".join(parts)


def main(argv=None):
    args = parse_args(argv)
    width, height = (int(v) for v in args.res.lower().split("x"))
    video = pathlib.Path(args.video) if args.video else REPO / "data/raw" / f"{args.clip}.mp4"
    blend = (pathlib.Path(args.blend) if args.blend
             else REPO / "models/smpl" / f"{args.clip}_compare.blend")
    out = (pathlib.Path(args.out) if args.out
           else REPO / "data/render" / f"{args.clip}_quad.mp4")

    if not video.exists():
        raise SystemExit(f"source clip not found: {video}")
    if not blend.exists():
        raise SystemExit(f"scene not found: {blend}")
    for font in (FONT_BOLD, FONT_REGULAR):
        if not pathlib.Path(font).exists():
            raise SystemExit(f"font not found: {font}")
    out.parent.mkdir(parents=True, exist_ok=True)

    camera = out.parent / f"_{args.clip}_quadcam.json"
    panels = []
    for i, (_, flags) in enumerate(PANELS):
        if flags is None:
            continue
        panel = out.parent / f"_{args.clip}_quad{i}.mp4"
        render_panel(args, blend, panel, flags, width, height, camera, save_camera=not panels)
        panels.append(panel)

    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for p in panels:
        cmd += ["-i", str(p)]
    cmd += ["-i", str(video),
            "-filter_complex", build_filter(width, height),
            "-map", "[out]", "-an",
            "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", str(out)]
    print("+ ffmpeg ->", out)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr[-4000:] + "\n")
        raise SystemExit("ffmpeg composite failed")

    if not args.keep_panels:
        for p in panels:
            p.unlink(missing_ok=True)
        camera.unlink(missing_ok=True)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
