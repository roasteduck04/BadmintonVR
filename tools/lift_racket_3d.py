"""Stage 2 — lift the 2D racket onto the 3D body: skeleton.json v2 + joints 24/25/26.

The geometry
------------
Monocular depth is unrecoverable in general, but for a racket it is nearly free, because
three things pin it down:

1. **The grip is in the hand**, and the hand's 3D position comes from the SMPL pass.
2. **The racket length is fixed** — one rigid object, so |tip - grip| is constant.
3. **Its image direction is measured** — `handle -> top` from the RacketVision pass.

Under the weak-perspective camera `fit_camera.py` recovers (`u = s*X + tx`), inverting the
projection returns the racket's world **X and Y outright**. Only the depth difference is
unknown, and the length constraint gives it directly:

    dZ = +/- sqrt(L^2 - dX^2 - dY^2)

So every frame has exactly **two** candidate rackets — tip tilted toward the camera, or
away. That sign is the only thing left to decide, and it is decided per run of frames:
seed from the forearm (a racket extends away from the elbow far more often than back over
it), then propagate by choosing whichever sign keeps the direction closest to the previous
frame. A racket cannot flip end-over-end between two frames at 25 fps.

`L` is measured from the clip rather than assumed. Apparent length peaks when the racket is
perpendicular to the view axis (`dZ = 0`), so a high percentile of the observed apparent
lengths is the true length — this avoids having to guess where RacketVision's `handle`
keypoint sits along the grip.

Frames with no racket detection fall back to the forearm direction at the hand, written
with confidence 0 and `status: "prior"`, so a posed racket never masquerades as a measured
one. Output joints are converted to the Unity frame with the same `WORLD_TO_UNITY` the rest
of the skeleton uses.

Roll — the third degree of freedom
----------------------------------
Grip and tip fix only the shaft axis, which leaves the racket a **line**: nothing in the
long axis says whether the face is edge-on or flat-on. `left`/`right` straddle the head rim,
perpendicular to the shaft and in the racket plane, so they carry exactly that missing DOF,
and the solve mirrors the shaft's — head width gives |dZ|, perpendicularity picks its sign.

Roll is held as a scalar angle about the shaft, because that is what can be smoothed and
interpolated honestly, and it is treated as **pi-periodic**: `left` and `right` are
interchangeable on a symmetric head, so a 180-degree flip is a relabelling, not motion.
It carries its own status and confidence, separate from position — on test_6 the shaft is
solved in 44% of frames but the roll in only 33%, because `left`/`right` are the model's
weakest keypoints (74.6/75.5 published, vs 97-99 for the long axis) with the hand sitting
right on top of them.

Output: the input skeleton with three joints appended — **24 `racket_grip`** (parent: the
holding wrist), **25 `racket_head`** (parent: 24) and **26 `racket_side`** (parent: 25),
which sits half a head-width off the tip in the racket plane. Together they give a full
orientation: shaft = head-grip, across = side-head, normal = shaft x across. Note the joint
count becomes 27; consumers that hardcode 24 need `joint_names`/`parents` instead.

Usage
-----
    python tools/lift_racket_3d.py \
        --skeleton data/skeleton/test_6.skeleton.json \
        --track    data/racket/test_6.rackettrack.json \
        --camera   data/calib/test_6_camera.json \
        --out      data/skeleton/test_6.skeleton_racket.json
"""

import argparse
import json

import numpy as np

import fit_camera as fc
from smpl_to_skeleton import WORLD_TO_UNITY, apply_transform

# SMPL joint indices, per side: (wrist, hand, elbow)
HAND_CHAIN = {"right": (21, 23, 19), "left": (20, 22, 18)}
GRIP_INDEX = 24
HEAD_INDEX = 25
SIDE_INDEX = 26
LENGTH_PERCENTILE = 90.0    # apparent length peaks at dZ=0; the tail is noise, not signal
WIDTH_PERCENTILE = 90.0     # same argument for the head width, across the rim
MIN_LENGTH_SAMPLES = 5

# Roll gates. `left`/`right` are the model's weakest keypoints (74.6/75.5 published vs
# 97-99 for the long axis) because the hand occludes the head sides, so roll needs a
# stricter admission test than the shaft does.
MIN_SIDE_SCORE = 0.50       # min(left, right) keypoint score
MAX_PERP_ERROR_DEG = 25.0   # how far the raw width vector may sit off perpendicular
ROLL_SMOOTH_WINDOW = 3      # median filter, in frames
MAX_ROLL_GAP = 4            # frames of roll interpolation, matching the 2D track's limit

STATUS_MEASURED = "measured"
STATUS_PRIOR = "prior"
STATUS_NONE = "none"
# Roll gets its own vocabulary: it can be solved in a frame whose position was solved too,
# bridged across a short gap, or absent entirely — and "bridged" must never read as "seen".
ROLL_MEASURED = "measured"
ROLL_INTERPOLATED = "interpolated"
ROLL_NONE = "none"
ROLL_STATUSES = (ROLL_MEASURED, ROLL_INTERPOLATED, ROLL_NONE)


def detect_handedness(track, cams, joints3d, frame_size):
    """Which hand holds the racket, decided by which one the `handle` keypoint follows.

    Cheaper and safer than hardcoding: a left-handed clip would otherwise produce a racket
    welded to the wrong arm, and the error would be subtle on the twin.
    """
    hi = track["keypoint_names"].index("handle")
    scores = {}
    for side, (_, hand, _) in HAND_CHAIN.items():
        d = []
        for rec in track["frames"]:
            t = rec["frame"]
            if rec["status"] == "missing" or t >= len(joints3d) or not cams[t]:
                continue
            uv = normalized_uv(rec["keypoints"][hi], frame_size)
            d.append(np.linalg.norm(fc.unproject_xy(cams[t], uv) - joints3d[t][hand][:2]))
        scores[side] = float(np.median(d)) if d else float("inf")
    best = min(scores, key=scores.get)
    return best, scores


def normalized_uv(px, frame_size):
    """Pixels in the racket pass's frame -> the camera's width-normalized coords."""
    return np.array([px[0] / frame_size[0], px[1] / frame_size[0]], dtype=np.float64)


def apparent_vectors(track, cams, frame_size):
    """Per frame, the racket's world (dX, dY) from grip to tip, or None."""
    names = track["keypoint_names"]
    hi, ti = names.index("handle"), names.index("top")
    out = []
    for rec in track["frames"]:
        t = rec["frame"]
        cam = cams[t] if t < len(cams) else None
        if rec["keypoints"] is None or cam is None:
            out.append(None)
            continue
        h = fc.unproject_xy(cam, normalized_uv(rec["keypoints"][hi], frame_size))
        tip = fc.unproject_xy(cam, normalized_uv(rec["keypoints"][ti], frame_size))
        out.append((h, tip - h))
    return out


def estimate_length(vectors, percentile=LENGTH_PERCENTILE):
    """Racket length in metres from the apparent lengths (see module docstring)."""
    lens = [float(np.linalg.norm(v)) for hv in vectors if hv is not None
            for v in [hv[1]] if np.linalg.norm(v) > 0]
    if len(lens) < MIN_LENGTH_SAMPLES:
        raise ValueError(f"only {len(lens)} usable frames; cannot estimate racket length")
    return float(np.percentile(lens, percentile))


def resolve_depths(vectors, length, forearm_dirs):
    """Choose the sign of dZ per frame. Returns a list of 3-vectors (grip->tip) or None.

    Runs of consecutive measured frames are resolved independently: seed the run from the
    forearm prior, then propagate by continuity. Starting each run fresh means a long gap
    cannot carry a stale sign across it.
    """
    out = [None] * len(vectors)
    i = 0
    while i < len(vectors):
        if vectors[i] is None:
            i += 1
            continue
        start = i
        while i < len(vectors) and vectors[i] is not None:
            i += 1
        prev = None
        for k in range(start, i):
            dx, dy = vectors[k][1]
            flat = dx * dx + dy * dy
            dz = float(np.sqrt(max(0.0, length * length - flat)))   # clamp: dZ=0 if over-long
            cands = [np.array([dx, dy, dz]), np.array([dx, dy, -dz])]
            if prev is not None:
                pick = max(cands, key=lambda c: float(np.dot(c, prev)))
            else:
                fa = forearm_dirs[k]
                pick = (max(cands, key=lambda c: float(np.dot(c, fa))) if fa is not None
                        else cands[0])
            out[k] = pick
            prev = pick / (np.linalg.norm(pick) or 1.0)
    return out


# --------------------------------------------------------------------------------------
# Roll (rotation about the shaft) -- the racket's third degree of freedom.
#
# `handle`->`top` fixes only the shaft axis, which leaves the racket a line: the face could
# be edge-on or flat-on and nothing in the long axis says which. `left`/`right` straddle the
# head rim, perpendicular to the shaft and *in* the racket plane, so they carry exactly the
# missing DOF. The solve mirrors the shaft's: inverting weak perspective gives the width
# vector's X and Y, the known head width gives |dZ|, and perpendicularity to the shaft picks
# its sign.
#
# Roll is stored as a scalar angle about the shaft rather than a vector, because that is
# what can be smoothed and interpolated honestly. It is treated as **pi-periodic**: `left`
# and `right` are interchangeable on a symmetric head, so a 180-degree "flip" is a
# relabelling, not motion, and must not be smoothed as though the racket spun.
# --------------------------------------------------------------------------------------

def reference_frame(d):
    """A deterministic pair of unit vectors perpendicular to shaft direction `d`.

    Roll is meaningless without a zero, and the zero must depend only on `d` so the same
    shaft always yields the same reference — otherwise smoothing would chase its own frame.
    """
    d = np.asarray(d, float)
    d = d / np.linalg.norm(d)
    up = np.array([0.0, 1.0, 0.0])
    if abs(float(d @ up)) > 0.95:            # shaft near-vertical: `up` is a poor reference
        up = np.array([1.0, 0.0, 0.0])
    ref = up - (up @ d) * d
    ref /= np.linalg.norm(ref)
    return ref, np.cross(d, ref)


def width_vector(cam, keypoints, names, frame_size, d, width):
    """3D unit vector across the head rim, or (None, None) if the geometry is degenerate.

    Returns (unit vector, perpendicularity correction in degrees). The correction is how far
    the raw solve sat off the shaft-perpendicular plane — a direct quality signal, since a
    good `left`/`right` pair on a real racket should already be nearly perpendicular.
    """
    li, ri = names.index("left"), names.index("right")
    left = fc.unproject_xy(cam, normalized_uv(keypoints[li], frame_size))
    right = fc.unproject_xy(cam, normalized_uv(keypoints[ri], frame_size))
    wxy = right - left
    flat = float(wxy @ wxy)
    wz = float(np.sqrt(max(0.0, width * width - flat)))
    # Perpendicularity fixes the sign of the depth component: w.d = 0 has one solution for
    # wz, and we take the sign of that rather than its magnitude (which collapses to zero
    # when the head is edge-on and the 2D width vanishes).
    sign = -np.sign(float(wxy @ d[:2])) * np.sign(d[2]) if abs(d[2]) > 1e-9 else 1.0
    raw = np.array([wxy[0], wxy[1], (sign if sign != 0 else 1.0) * wz])
    n = float(np.linalg.norm(raw))
    if n < 1e-9:
        return None, None
    raw /= n
    perp = raw - float(raw @ d) * d          # project onto the plane normal to the shaft
    n2 = float(np.linalg.norm(perp))
    if n2 < 0.2:                             # width vector nearly along the shaft: nonsense
        return None, None
    correction = float(np.degrees(np.arccos(np.clip(abs(float(raw @ (perp / n2))), 0.0, 1.0))))
    return perp / n2, correction


def estimate_width(track, cams, frame_size, percentile=WIDTH_PERCENTILE):
    """Head width in metres, from the apparent rim separation (peaks when the face is flat on)."""
    names = track["keypoint_names"]
    li, ri = names.index("left"), names.index("right")
    widths = []
    for r in track["frames"]:
        cam = cams[r["frame"]] if r["frame"] < len(cams) else None
        if r["keypoints"] is None or cam is None:
            continue
        left = fc.unproject_xy(cam, normalized_uv(r["keypoints"][li], frame_size))
        right = fc.unproject_xy(cam, normalized_uv(r["keypoints"][ri], frame_size))
        widths.append(float(np.linalg.norm(right - left)))
    if len(widths) < MIN_LENGTH_SAMPLES:
        raise ValueError(f"only {len(widths)} usable frames; cannot estimate head width")
    return float(np.percentile(widths, percentile))


def roll_angle(d, w):
    """Signed roll of width vector `w` about shaft `d`, measured from the reference frame."""
    ref, orth = reference_frame(d)
    return float(np.arctan2(float(w @ orth), float(w @ ref)))


def roll_to_vector(d, theta):
    """Inverse of `roll_angle`: rebuild the unit width vector from an angle."""
    ref, orth = reference_frame(d)
    return np.cos(theta) * ref + np.sin(theta) * orth


def unwrap_pi(angles):
    """Unwrap a sequence that is only defined modulo pi (left/right are interchangeable).

    Standard unwrapping assumes 2*pi periodicity and would read a relabelling flip as a
    half-turn of real rotation. `None` entries pass through untouched.
    """
    out = list(angles)
    prev = None
    for i, a in enumerate(out):
        if a is None:
            continue
        if prev is not None:
            a += np.pi * round((prev - a) / np.pi)
        out[i] = a
        prev = a
    return out


def smooth_rolls(angles, window=ROLL_SMOOTH_WINDOW, max_gap=MAX_ROLL_GAP):
    """Median-filter the known angles and fill only SHORT gaps between them.

    Median rather than mean because the failure mode is isolated outliers, not noise around
    a true value. `max_gap` matters: without it, two measurements 40 frames apart would be
    bridged by a smooth interpolation that looks exactly like data, across a stretch where
    the racket was never seen. Gaps outside the first and last measurement are never filled.
    """
    a = unwrap_pi(angles)
    known = [i for i, v in enumerate(a) if v is not None]
    if not known:
        return list(a)
    filtered = list(a)
    half = max(0, window // 2)
    for i in known:
        nearby = [a[j] for j in range(max(0, i - half), min(len(a), i + half + 1))
                  if a[j] is not None]
        filtered[i] = float(np.median(nearby))
    out = list(filtered)
    for lo, hi in zip(known, known[1:]):
        span = hi - lo
        if span == 1 or span - 1 > max_gap:
            continue
        for k in range(1, span):
            t = k / span
            out[lo + k] = filtered[lo] * (1 - t) + filtered[hi] * t
    return out


def solve_rolls(track, cams, frame_size, deltas, width,
                min_side_score=MIN_SIDE_SCORE, max_perp_error=MAX_PERP_ERROR_DEG):
    """Per frame, the roll angle about the shaft (or None), plus per-frame diagnostics."""
    names = track["keypoint_names"]
    li, ri = names.index("left"), names.index("right")
    angles, info = [], []
    for rec in track["frames"]:
        t = rec["frame"]
        cam = cams[t] if t < len(cams) else None
        delta = deltas[t] if t < len(deltas) else None
        if rec["keypoints"] is None or cam is None or delta is None:
            angles.append(None)
            info.append({"reason": "no_racket"})
            continue
        scores = rec.get("keypoint_scores")
        side_score = min(scores[li], scores[ri]) if scores else None
        if side_score is not None and side_score < min_side_score:
            angles.append(None)
            info.append({"reason": "low_side_score", "side_score": side_score})
            continue
        d = delta / np.linalg.norm(delta)
        w, correction = width_vector(cam, rec["keypoints"], names, frame_size, d, width)
        if w is None:
            angles.append(None)
            info.append({"reason": "degenerate"})
            continue
        if correction > max_perp_error:
            angles.append(None)
            info.append({"reason": "not_perpendicular", "correction_deg": correction})
            continue
        angles.append(roll_angle(d, w))
        info.append({"reason": "ok", "correction_deg": correction,
                     "side_score": side_score})
    return angles, info


def forearm_directions(joints3d, side):
    """Unit elbow->wrist vector per frame; the seed prior and the gap fallback."""
    _, _, elbow = HAND_CHAIN[side]
    wrist = HAND_CHAIN[side][0]
    out = []
    for j in joints3d:
        v = j[wrist] - j[elbow]
        n = float(np.linalg.norm(v))
        out.append(v / n if n > 1e-6 else None)
    return out


def build_racket_series(track, cams, joints3d, frame_size, side, length, width=None,
                        fill_missing=True):
    """Per frame, a dict of grip/head/side points (ROMP camera space) plus status flags.

    `side` is the third point that turns the racket from a line into an oriented body:
    it sits half a head-width off the tip, in the racket plane. With it, a consumer builds
    the full frame as shaft = head-grip, across = side-head, normal = shaft x across.
    """
    _, hand, _ = HAND_CHAIN[side]
    vectors = apparent_vectors(track, cams, frame_size)
    forearms = forearm_directions(joints3d, side)
    deltas = resolve_depths(vectors, length, forearms)

    if width is None:
        raw = rolls = [None] * len(track["frames"])
        roll_info = [{"reason": "no_width"}] * len(track["frames"])
    else:
        raw, roll_info = solve_rolls(track, cams, frame_size, deltas, width)
        rolls = smooth_rolls(raw)

    half_width = (width or 0.0) / 2.0
    series = []
    for i, rec in enumerate(track["frames"]):
        t = rec["frame"]
        if t >= len(joints3d):
            series.append({"grip": None, "head": None, "side": None,
                           "status": STATUS_NONE, "confidence": 0.0,
                           "roll_status": ROLL_NONE})
            continue
        hand_xyz = joints3d[t][hand]
        if deltas[t] is not None:
            gx, gy = vectors[t][0]
            # Depth is not observable under weak perspective; the hand's depth is the only
            # defensible anchor, and the grip is in the hand by construction.
            grip = np.array([gx, gy, hand_xyz[2]])
            head = grip + deltas[t]
            conf = float(rec["kp_score"] or 0.0) if rec["status"] == "detected" else 0.5
            status = STATUS_MEASURED
        elif fill_missing and forearms[t] is not None:
            grip = np.asarray(hand_xyz, float)
            head = grip + length * forearms[t]
            conf, status = 0.0, STATUS_PRIOR
        else:
            series.append({"grip": None, "head": None, "side": None,
                           "status": STATUS_NONE, "confidence": 0.0,
                           "roll_status": ROLL_NONE})
            continue

        d = head - grip
        d = d / (np.linalg.norm(d) or 1.0)
        theta = rolls[i] if i < len(rolls) else None
        if theta is None:
            # No roll evidence. Emit the deterministic reference orientation so the racket
            # frame is always well-formed, and flag it -- never leave a degenerate triangle
            # that a consumer would silently normalize into a random normal.
            w = reference_frame(d)[0]
            roll_status = ROLL_NONE
        else:
            w = roll_to_vector(d, theta)
            # Solved in THIS frame, or bridged from neighbours? The distinction is the whole
            # point of tracking `raw` separately from the smoothed series.
            roll_status = (ROLL_MEASURED if (i < len(raw) and raw[i] is not None)
                           else ROLL_INTERPOLATED)
        series.append({"grip": grip, "head": head, "side": head + half_width * w,
                       "status": status, "confidence": conf, "roll_status": roll_status})
    return series, roll_info


def append_racket_joints(skeleton, series, *, side, length, width, track_path, camera_path):
    """Return a copy of the skeleton document with joints 24/25/26 appended.

    Points arrive in ROMP camera space and are converted with the same `WORLD_TO_UNITY`
    the other 24 joints already went through — mixing frames inside one `joints_flat`
    would be invisible until the racket pointed the wrong way on the twin.
    """
    doc = dict(skeleton)
    doc["joint_names"] = list(skeleton["joint_names"]) + [
        "racket_grip", "racket_head", "racket_side"]
    doc["parents"] = list(skeleton["parents"]) + [
        HAND_CHAIN[side][0], GRIP_INDEX, HEAD_INDEX]
    doc["skeleton"] = "smpl-24+racket"
    doc["racket"] = {
        "source": "lift_racket_3d.py (RacketVision 2D + weak-perspective camera)",
        "grip_index": GRIP_INDEX, "head_index": HEAD_INDEX, "side_index": SIDE_INDEX,
        "handedness": side,
        "length_m": round(length, 4),
        "head_width_m": round(width, 4) if width else None,
        "track": track_path, "camera": camera_path,
        "orientation": ("shaft = head - grip; across = side - head; "
                        "normal = shaft x across. `racket_side` sits half a head-width "
                        "off the tip, in the racket plane."),
        "coverage": {s: sum(1 for e in series if e["status"] == s)
                     for s in (STATUS_MEASURED, STATUS_PRIOR, STATUS_NONE)},
        "roll_coverage": {s: sum(1 for e in series if e["roll_status"] == s)
                          for s in ROLL_STATUSES},
        "note": "joints_flat now holds 27 joints; read joint_names/parents, not a hardcoded 24",
    }
    frames = []
    for frame, entry in zip(skeleton["frames"], series):
        f = dict(frame)
        flat = list(frame["joints_flat"])
        if entry["grip"] is None:
            flat += [0.0, 0.0, 0.0, 0.0] * 3
        else:
            # Roll gets its own confidence: the shaft can be solidly measured while the
            # face angle is a guess, and collapsing the two would hide exactly that.
            roll_conf = (entry["confidence"]
                         if entry["roll_status"] != ROLL_NONE else 0.0)
            for key, conf in (("grip", entry["confidence"]), ("head", entry["confidence"]),
                              ("side", roll_conf)):
                p = apply_transform(np.asarray(entry[key], float).reshape(1, 3),
                                    WORLD_TO_UNITY)[0]
                flat += [float(p[0]), float(p[1]), float(p[2]), conf]
        f["joints_flat"] = flat
        f["racket_status"] = entry["status"]
        f["racket_roll_status"] = entry["roll_status"]
        frames.append(f)
    doc["frames"] = frames
    return doc


def main(argv=None):
    ap = argparse.ArgumentParser(description="Lift the 2D racket track into skeleton.json v2.")
    ap.add_argument("--skeleton", required=True, help="<id>.skeleton.json (v2)")
    ap.add_argument("--track", required=True, help="<id>.rackettrack.json")
    ap.add_argument("--camera", required=True, help="<id>_camera.json from fit_camera.py")
    ap.add_argument("--smpl-npz", help="npz with joints3d in ROMP camera space "
                                       "(default: alongside the camera's video_id)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--side", choices=["auto", "left", "right"], default="auto")
    ap.add_argument("--length", type=float, default=None,
                    help="racket grip-to-tip metres (default: measured from the clip)")
    ap.add_argument("--width", type=float, default=None,
                    help="racket head width metres (default: measured from the clip)")
    ap.add_argument("--no-roll", action="store_true",
                    help="skip the roll solve; emit the racket as a bare line")
    ap.add_argument("--no-fill", action="store_true",
                    help="leave undetected frames empty instead of using the forearm prior")
    args = ap.parse_args(argv)

    with open(args.skeleton, encoding="utf-8") as fh:
        skeleton = json.load(fh)
    with open(args.track, encoding="utf-8") as fh:
        track = json.load(fh)
    with open(args.camera, encoding="utf-8") as fh:
        camdoc = json.load(fh)

    npz = args.smpl_npz or f"models/smpl/{skeleton['video_id']}.smpl.npz"
    joints3d = np.asarray(np.load(npz)["joints3d"], dtype=np.float64)
    cams = camdoc["frames"]
    frame_size = track["frame_size"]

    n = min(len(skeleton["frames"]), len(track["frames"]), len(cams), len(joints3d))
    if len({len(skeleton["frames"]), len(track["frames"]), len(cams), len(joints3d)}) > 1:
        print(f"  WARNING: frame counts differ (skeleton {len(skeleton['frames'])}, "
              f"track {len(track['frames'])}, camera {len(cams)}, smpl {len(joints3d)}); "
              f"using the first {n}")
        skeleton = dict(skeleton, frames=skeleton["frames"][:n])
        track = dict(track, frames=track["frames"][:n])

    if args.side == "auto":
        side, scores = detect_handedness(track, cams, joints3d, frame_size)
        print(f"handedness: {side} "
              f"(median grip-to-hand: " +
              ", ".join(f"{k} {v:.3f} m" for k, v in scores.items()) + ")")
    else:
        side = args.side

    vectors = apparent_vectors(track, cams, frame_size)
    length = args.length if args.length else estimate_length(vectors)
    print(f"racket length: {length:.3f} m "
          f"({'given' if args.length else f'measured, p{LENGTH_PERCENTILE:.0f}'})")

    width = None
    if not args.no_roll:
        width = args.width if args.width else estimate_width(track, cams, frame_size)
        print(f"head width:    {width:.3f} m "
              f"({'given' if args.width else f'measured, p{WIDTH_PERCENTILE:.0f}'})")

    series, roll_info = build_racket_series(track, cams, joints3d, frame_size, side, length,
                                            width=width, fill_missing=not args.no_fill)
    doc = append_racket_joints(skeleton, series, side=side, length=length, width=width,
                               track_path=args.track, camera_path=args.camera)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)

    cov = doc["racket"]["coverage"]
    roll = doc["racket"]["roll_coverage"]
    print(f"wrote {args.out}")
    print("  position:")
    for k in (STATUS_MEASURED, STATUS_PRIOR, STATUS_NONE):
        print(f"    {k:9s} {cov[k]:4d}/{n}  ({100 * cov[k] / n:.0f}%)")
    if width is not None:
        print("  roll (rotation about the shaft):")
        for k in ROLL_STATUSES:
            print(f"    {k:12s} {roll[k]:4d}/{n}  ({100 * roll[k] / n:.0f}%)")
        reasons = {}
        for info in roll_info:
            reasons[info["reason"]] = reasons.get(info["reason"], 0) + 1
        print("    rejected because: " +
              ", ".join(f"{k} {v}" for k, v in sorted(reasons.items()) if k != "ok"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
