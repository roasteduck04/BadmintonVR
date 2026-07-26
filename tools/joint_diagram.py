"""A labelled reference figure of the SMPL-24 joints.

    tools/.venv/Scripts/python tools/joint_diagram.py

Renders the twin's armature in its REST pose — nodes and bone vectors, no mesh, no racket —
then labels every joint with its index and its `skeleton.json` name. Writes
`data/render/smpl24_joints.png`.

Rest pose, not a frame of the clip: a mid-smash figure folds the arms across the torso and
half the labels end up pointing into the same few hundred pixels. The T-pose separates every
limb, and the topology is the point of this figure, not the motion.

Label placement
---------------
Labels live in two columns in the margins, never over the figure, with a leader line back to
their node. Each column starts every label level with its own joint and then relaxes
overlapping pairs apart until none are closer than one row — so labels cannot collide within
a column, and because the columns sit outside the figure's x-range they cannot collide across
columns either. That is the whole placement rule; there are no per-joint nudges to re-tune
when the pose or the resolution changes.

The spine chain is drawn in a second colour. It is the reason this skeleton replaced the
MediaPipe one: `pelvis → spine1 → spine2 → spine3 → neck → head` is exactly what BlazePose's
33 landmarks do not have.
"""

import argparse
import json
import pathlib
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

from side_by_side_video import find_blender

REPO = pathlib.Path(__file__).resolve().parent.parent

# The chain MediaPipe cannot produce; drawn apart from the limbs for that reason.
SPINE_CHAIN = ("pelvis", "spine1", "spine2", "spine3", "neck", "head")

PAD = 340                      # margin added either side of the render, for the columns
MARGIN_TOP, MARGIN_BOTTOM = 96, 132
BG = (46, 46, 48)          # fallback only; the figure corner wins (see annotate)
SPINE_RGB = (255, 214, 102)
LIMB_RGB = (232, 236, 244)
LEADER_RGB = (150, 154, 162)
DIM_RGB = (168, 172, 180)

FONT_BOLD = "C:/Windows/Fonts/arialbd.ttf"
FONT_REGULAR = "C:/Windows/Fonts/arial.ttf"

TITLE = "SMPL-24 skeleton - joint index and skeleton.json name"
SUBTITLE = ("Rest pose, front view (the figure faces you, so its left is on your right).  "
            "Highlighted: the spine chain pelvis -> spine1 -> spine2 -> spine3 -> neck -> head.")
FOOTER = ("Bone vectors run parent -> child; 24 joints, 23 bones.  "
          "The lifted racket adds racket_grip 24 / racket_head 25 / racket_side 26.")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--blend", default=None,
                   help="scene to render (default models/smpl/test_6_compare.blend)")
    p.add_argument("--out", default=None, help="default data/render/smpl24_joints.png")
    p.add_argument("--res", default="1400x1500", help="size of the FIGURE, before margins")
    p.add_argument("--blender", default=None, help="path to blender.exe")
    p.add_argument("--body", default="A", help="which twin to pose (A raw, B smoothed)")
    p.add_argument("--keep-parts", action="store_true", help="keep the render and the dump")
    return p.parse_args(argv)


def render_figure(args, blend, base, dump, width, height):
    """The rest-pose figure, plus where each joint landed in it."""
    blender = find_blender(args.blender)
    script = REPO / "tools" / "blender" / "render_compare.py"
    cmd = [blender, "-b", str(blend), "-P", str(script), "--",
           "--bodies", args.body, "--rest", "--no-mesh", "--joints", "--bones",
           "--no-floor", "--no-racket", "--still", "0",
           "--samples", "999",              # the rest pose is one pose; sample it once
           "--elevation", "0", "--margin", "0.22",
           "--res", f"{width}x{height}",
           "--out", str(base.relative_to(REPO)).replace("\\", "/"),
           "--dump-joints", str(dump.relative_to(REPO)).replace("\\", "/")]
    print("+", " ".join(str(c) for c in cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    finished = False
    for line in proc.stdout.splitlines():
        if line.startswith("render_compare:"):
            print(" ", line)
            finished |= line.startswith("render_compare: wrote")
    if not (finished and base.exists() and dump.exists()):
        sys.stderr.write(proc.stdout[-4000:] + "\n" + proc.stderr[-2000:] + "\n")
        raise SystemExit("blender render failed")


def order_key(joint, centre):
    """Sort joints down a column, breaking near-ties by how far out the limb they sit.

    The five arm joints of a T-pose share a y to within twenty pixels, so sorting on y
    alone puts them in essentially random order -- and a column ordered differently from
    the limb it labels produces crossed leader lines. Rounding y into bands first, then
    ordering a band from the column outward, makes collar/shoulder/elbow/wrist/hand come
    out in limb order.
    """
    return (round(joint["y"] / 60.0), -abs(joint["x"] - centre))


def pack_column(joints, row_h, top, bottom, centre):
    """Give each joint a label row, with no two rows closer than `row_h`.

    Overlaps are relieved by pushing the pair APART, not by cascading everything downward.
    A one-directional pack sends a cluster of five near-identical y values 200 px below the
    limb it belongs to; splitting the correction keeps every label beside its own node.
    """
    rows = [[j, float(j["y"])] for j in sorted(joints, key=lambda j: order_key(j, centre))]
    for _ in range(200):
        worst = 0.0
        for a, b in zip(rows, rows[1:]):
            overlap = row_h - (b[1] - a[1])
            if overlap > 0:
                a[1] -= overlap / 2.0
                b[1] += overlap / 2.0
                worst = max(worst, overlap)
        if worst < 0.5:
            break
    # Only now clamp to the canvas, as a rigid block, so the relaxed spacing survives.
    shift = max(0.0, top - rows[0][1]) - max(0.0, rows[-1][1] - bottom)
    return [(j, y + shift) for j, y in rows]


def draw_column(draw, rows, column_x, align_right, font, dot_r=7):
    """Label rows in one margin column, each with a leader line back to its node."""
    for joint, row_y in rows:
        spine = joint["name"] in SPINE_CHAIN
        colour = SPINE_RGB if spine else LIMB_RGB
        text = f"{joint['index']:>2}  {joint['name']}"
        w = draw.textlength(text, font=font)
        text_x = column_x - w if align_right else column_x
        # Leader: out of the node, a short horizontal run into the column, then the text.
        knee_x = column_x + (28 if align_right else -28)
        draw.line([(joint["x"], joint["y"]), (knee_x, row_y + font.size // 2)],
                  fill=LEADER_RGB, width=2)
        draw.line([(knee_x, row_y + font.size // 2), (column_x + (8 if align_right else -8),
                                                      row_y + font.size // 2)],
                  fill=LEADER_RGB, width=2)
        draw.ellipse([joint["x"] - dot_r, joint["y"] - dot_r,
                      joint["x"] + dot_r, joint["y"] + dot_r],
                     outline=colour, width=3)
        draw.text((text_x, row_y), text, font=font, fill=colour)


def annotate(base, dump, out, body_centre=None):
    figure = Image.open(base).convert("RGB")
    data = json.loads(dump.read_text(encoding="utf-8"))
    joints = data["joints"]

    # Crop to the skeleton. `render_compare` frames for the widest extent and a T-pose is
    # far wider than it is deep, so the raw render carries bands of empty floor colour that
    # would only push the figure smaller once the label columns are added.
    bleed = 80
    box = (max(0, min(j["x"] for j in joints) - bleed),
           max(0, min(j["y"] for j in joints) - bleed),
           min(figure.width, max(j["x"] for j in joints) + bleed),
           min(figure.height, max(j["y"] for j in joints) + bleed))
    figure = figure.crop(tuple(round(v) for v in box))
    for j in joints:
        j["x"] -= box[0]
        j["y"] -= box[1]

    # Take the canvas colour from the render's own corner rather than the BG constant, so
    # the pasted figure has no visible edge. Workbench's background follows the Blender
    # theme, which is not ours to predict.
    canvas = Image.new("RGB", (figure.width + 2 * PAD,
                               figure.height + MARGIN_TOP + MARGIN_BOTTOM),
                       figure.getpixel((1, 1)))
    canvas.paste(figure, (PAD, MARGIN_TOP))
    draw = ImageDraw.Draw(canvas)

    for j in joints:                       # into canvas coordinates, once
        j["x"] += PAD
        j["y"] += MARGIN_TOP

    label_font = ImageFont.truetype(FONT_REGULAR, 27)
    title_font = ImageFont.truetype(FONT_BOLD, 40)
    small_font = ImageFont.truetype(FONT_REGULAR, 23)

    # Split on the figure's own midline rather than the canvas's: the rest pose is
    # symmetric, so this puts the subject's right limbs in the left column and vice versa,
    # and the spine chain goes with whichever side keeps the columns even.
    centre = body_centre if body_centre is not None else \
        sum(j["x"] for j in joints) / len(joints)
    def goes_left(j):
        return j["x"] < centre - 1 or j["name"] in SPINE_CHAIN

    left = [j for j in joints if goes_left(j)]
    right = [j for j in joints if not goes_left(j)]

    row_h = 42
    top, bottom = MARGIN_TOP + 10, MARGIN_TOP + figure.height - row_h
    draw_column(draw, pack_column(left, row_h, top, bottom, centre),
                PAD - 40, True, label_font)
    draw_column(draw, pack_column(right, row_h, top, bottom, centre),
                PAD + figure.width + 40, False, label_font)

    draw.text((PAD - 40, 24), TITLE, font=title_font, fill=(255, 255, 255))
    draw.text((PAD - 40, 72), SUBTITLE, font=small_font, fill=DIM_RGB)
    draw.text((PAD - 40, canvas.height - 78), FOOTER, font=small_font, fill=DIM_RGB)

    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out)
    return canvas.size


def main(argv=None):
    args = parse_args(argv)
    width, height = (int(v) for v in args.res.lower().split("x"))
    blend = (pathlib.Path(args.blend) if args.blend
             else REPO / "models/smpl" / "test_6_compare.blend")
    out = (pathlib.Path(args.out) if args.out
           else REPO / "data/render" / "smpl24_joints.png")
    if not blend.exists():
        raise SystemExit(f"scene not found: {blend}")
    for font in (FONT_BOLD, FONT_REGULAR):
        if not pathlib.Path(font).exists():
            raise SystemExit(f"font not found: {font}")

    base = out.parent / "_smpl24_figure.png"
    dump = out.parent / "_smpl24_joints.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    render_figure(args, blend, base, dump, width, height)
    size = annotate(base, dump, out)

    if not args.keep_parts:
        base.unlink(missing_ok=True)
        dump.unlink(missing_ok=True)
    print(f"wrote {out} ({size[0]}x{size[1]})")


if __name__ == "__main__":
    main()
