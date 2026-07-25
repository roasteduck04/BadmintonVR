"""Pick ONE racket per frame out of a RacketVision 2D pass, and write a clean track.

Why this exists
---------------
`racketvision_extract.ipynb` (v4) runs RTMDet at a deliberately permissive
`score_thr = 0.05` and keeps the top-K boxes per frame, each with its own RTMPose
keypoints (`frames[i].cands`). That is on purpose: on test_6 the detector score turned
out to be almost uninformative — a box scoring **0.08** carried a textbook racket fit,
while a 0.06 box on the far side of the frame was a net-post artifact. Raising the
detector threshold to make the output "clean" is what cost us 89% of the frames in v3.

The signal that *does* separate them is the **mean RTMPose keypoint score**. Real
rackets land at 0.6-0.75; false positives sit at 0.1-0.3, because the pose head cannot
find a shaft and a head in something that is not a racket. So this module re-ranks the
candidates by keypoint score, uses temporal continuity to recover borderline frames and
to throw out isolated jumps, and interpolates short gaps.

Output: `<id>.rackettrack.json` — one entry per source frame, each `detected`,
`interpolated`, or `missing`, so Stage 2 (lift to a 3D segment at the SMPL hand) reads a
single unambiguous series instead of re-deriving this policy.

Usage
-----
    python tools/select_racket_track.py data/racket/test_6.racket2d.json \
        --out data/racket/test_6.rackettrack.json
"""

import argparse
import json
import math
import statistics

# Defaults tuned on test_6 (189 frames, 1920x1080, 25 fps). See the module docstring.
MIN_KP_SCORE = 0.50     # strict gate: mean keypoint score for an unassisted accept
RELAX_KP_SCORE = 0.35   # relaxed gate, only honoured next to an already-accepted frame
MAX_JUMP_PX = 250.0     # plausible racket-centre travel between adjacent frames
MAX_LEN_RATIO = 2.0     # grip-to-tip length may differ from the anchor's by at most this factor
MAX_INTERP_GAP = 4      # gaps up to this many frames are filled by linear interpolation

KEYPOINT_NAMES = ["top", "bottom", "handle", "left", "right"]   # RacketVision repo order

STATUS_DETECTED = "detected"
STATUS_INTERPOLATED = "interpolated"
STATUS_MISSING = "missing"


def shaft_length_px(keypoints, names=KEYPOINT_NAMES):
    """Grip-to-tip pixel length — the scale Stage 2 uses to place the 3D segment."""
    h, t = keypoints[names.index("handle")], keypoints[names.index("top")]
    return math.dist(h, t)


def mean_kp_score(cand):
    """Mean RTMPose keypoint score — the real confidence signal (see module docstring)."""
    return statistics.fmean(cand["keypoint_scores"])


def bbox_center(bbox):
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def candidates(frame):
    """All candidates for a frame, newest schema first, falling back to the v3 flat fields.

    v3 files have no `cands` key at all; treating their single argmax box as a one-element
    candidate list lets the same selection policy run over both.
    """
    cands = frame.get("cands")
    if cands:
        return cands
    if frame.get("keypoints"):
        return [{"bbox": frame["bbox"], "det_score": frame["det_score"],
                 "keypoints": frame["keypoints"], "keypoint_scores": frame["keypoint_scores"]}]
    return []


def select_track(frames, min_kp_score=MIN_KP_SCORE, relax_kp_score=RELAX_KP_SCORE,
                 max_jump_px=MAX_JUMP_PX, max_len_ratio=MAX_LEN_RATIO,
                 names=KEYPOINT_NAMES):
    """Choose at most one candidate per frame. Returns a list of picks (None where empty).

    Three passes, deliberately in this order:
      1. **Anchors** — best-by-keypoint-score candidate, if it clears `min_kp_score`.
         Selection never depends on neighbours here, so a bad frame cannot drag the track.
      2. **Outlier rejection** — drop an anchor that sits further than `max_jump_px` from
         every anchor within +/-2 frames. A racket cannot teleport; an isolated pick that
         far away is an artifact. Anchors with no neighbours at all are left alone —
         absence of corroboration is not evidence against.
      3. **Continuity recovery** — for still-empty frames, accept a candidate down to
         `relax_kp_score` if it is within `max_jump_px` of a surviving neighbour AND its
         grip-to-tip length is within `max_len_ratio` of that neighbour's. This is where
         the top-K pays off: the right box is often present but out-ranked. The length
         guard is what keeps the relaxed gate honest — on test_6 frames 57-58 it admitted
         fits that sat on the grip but never found the head, giving a 68 px shaft next to
         a 200 px one. Apparent length changes smoothly under foreshortening; a factor-of-
         three collapse between adjacent frames means the keypoints, not the racket, moved.
    """
    n = len(frames)
    picks = [None] * n

    # --- pass 1: anchors -----------------------------------------------------
    for i, fr in enumerate(frames):
        cands = candidates(fr)
        if not cands:
            continue
        best = max(cands, key=mean_kp_score)
        if mean_kp_score(best) >= min_kp_score:
            picks[i] = best

    # --- pass 2: outlier rejection ------------------------------------------
    keep = list(picks)
    for i, p in enumerate(picks):
        if p is None:
            continue
        c = bbox_center(p["bbox"])
        neighbours = [picks[j] for j in range(max(0, i - 2), min(n, i + 3))
                      if j != i and picks[j] is not None]
        if neighbours and all(math.dist(c, bbox_center(q["bbox"])) > max_jump_px
                              for q in neighbours):
            keep[i] = None
    picks = keep

    # --- pass 3: continuity recovery ----------------------------------------
    # Sweep forward then backward so a recovered frame can itself anchor the next one,
    # letting a run grow outward from a confident core in both directions.
    for step in (1, -1):
        order = range(n) if step == 1 else range(n - 1, -1, -1)
        for i in order:
            if picks[i] is not None:
                continue
            j = i - step
            if not (0 <= j < n) or picks[j] is None:
                continue
            anchor = bbox_center(picks[j]["bbox"])
            anchor_len = shaft_length_px(picks[j]["keypoints"], names)
            near = [c for c in candidates(frames[i])
                    if mean_kp_score(c) >= relax_kp_score
                    and math.dist(bbox_center(c["bbox"]), anchor) <= max_jump_px
                    and _length_plausible(shaft_length_px(c["keypoints"], names),
                                          anchor_len, max_len_ratio)]
            if near:
                picks[i] = max(near, key=mean_kp_score)
    return picks


def _length_plausible(length, anchor_len, max_ratio):
    """True when `length` is within a factor of `max_ratio` of `anchor_len` either way.

    A degenerate anchor (zero-length shaft) carries no scale information, so it cannot
    veto anything — fall through rather than dividing by zero.
    """
    if anchor_len <= 0 or length <= 0:
        return True
    ratio = length / anchor_len
    return 1.0 / max_ratio <= ratio <= max_ratio


def interpolate_gaps(picks, max_gap=MAX_INTERP_GAP):
    """Linearly fill runs of <= max_gap missing frames that are bracketed on BOTH sides.

    Returns a list of (keypoints, status) — keypoints is None for frames left missing.
    A one-sided gap is never extrapolated: past the end of a detected run there is no
    evidence about where the racket went, and inventing some would be indistinguishable
    from data downstream.
    """
    n = len(picks)
    out = [(p["keypoints"] if p else None,
            STATUS_DETECTED if p else STATUS_MISSING) for p in picks]
    i = 0
    while i < n:
        if picks[i] is not None:
            i += 1
            continue
        start = i
        while i < n and picks[i] is None:
            i += 1
        end = i                      # picks[start:end] are all None
        if start == 0 or end >= n:   # unbracketed -> leave missing
            continue
        gap = end - start
        if gap > max_gap:
            continue
        a = picks[start - 1]["keypoints"]
        b = picks[end]["keypoints"]
        for k in range(gap):
            t = (k + 1) / (gap + 1)
            out[start + k] = ([[a[j][0] + (b[j][0] - a[j][0]) * t,
                                a[j][1] + (b[j][1] - a[j][1]) * t]
                               for j in range(len(a))], STATUS_INTERPOLATED)
    return out


def build_track_document(doc, picks, filled, *, min_kp_score, relax_kp_score,
                         max_jump_px, max_len_ratio, max_interp_gap, source_path):
    """Assemble the output JSON. Geometry fields are carried through verbatim —
    Stage 2 needs `frame_size`/`source_size` to map these pixels onto the SMPL body."""
    frames_out = []
    for fr, pick, (kps, status) in zip(doc["frames"], picks, filled):
        frames_out.append({
            "frame": fr["frame"],
            "status": status,
            "keypoints": kps,
            "kp_score": round(mean_kp_score(pick), 4) if pick else None,
            # Per-keypoint scores, not just the mean: the racket ROLL is derived from
            # `left`/`right` alone, and those two are the model's weakest (74.6/75.5 vs
            # 97-99 for the long axis), so a roll consumer must gate on them specifically.
            "keypoint_scores": pick["keypoint_scores"] if pick else None,
            "det_score": pick["det_score"] if pick else None,
            "bbox": pick["bbox"] if pick else None,
        })
    counts = {s: sum(1 for f in frames_out if f["status"] == s)
              for s in (STATUS_DETECTED, STATUS_INTERPOLATED, STATUS_MISSING)}
    return {
        "video_id": doc["video_id"],
        "fps": doc["fps"],
        "stride": doc.get("stride", 1),
        "frame_size": doc["frame_size"],
        "source_size": doc["source_size"],
        "source": f"select_racket_track.py from {source_path}",
        "upstream": doc.get("source"),
        "keypoint_names": doc["keypoint_names"],
        "selection": {"min_kp_score": min_kp_score, "relax_kp_score": relax_kp_score,
                      "max_jump_px": max_jump_px, "max_len_ratio": max_len_ratio,
                      "max_interp_gap": max_interp_gap},
        "coverage": counts,
        "num_frames": len(frames_out),
        "frames": frames_out,
    }


def render_overlay(track, video_path, out_path):
    """Burn the selected track over the source clip. Interpolated frames draw dimmed, so a
    filled gap never looks like a measurement. Needs opencv (already in requirements.txt)."""
    import cv2
    import numpy as np

    names = track["keypoint_names"]
    colors = {"top": (0, 255, 0), "bottom": (0, 200, 255), "handle": (255, 80, 80),
              "left": (255, 0, 255), "right": (0, 255, 255)}
    W, H = track["frame_size"]
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise SystemExit(f"cannot open {video_path}")
    writer = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"),
                             track["fps"], (W, H))
    try:
        for rec in track["frames"]:
            ok, img = cap.read()
            if not ok:
                break
            if (img.shape[1], img.shape[0]) != (W, H):
                img = cv2.resize(img, (W, H))
            kps = rec["keypoints"]
            if kps:
                dim = rec["status"] == STATUS_INTERPOLATED
                pts = {n: (int(round(kps[i][0])), int(round(kps[i][1])))
                       for i, n in enumerate(names)}
                shade = (140, 140, 140) if dim else (255, 255, 255)
                cv2.line(img, pts["handle"], pts["top"], shade, 2 if dim else 3)
                cv2.line(img, pts["left"], pts["right"], shade, 2)
                for n in names:
                    c = colors[n]
                    cv2.circle(img, pts[n], 5, tuple(v // 2 for v in c) if dim else c, -1)
                label = (f"{rec['status']}  kp {rec['kp_score']:.2f}" if not dim
                         else rec["status"])
            else:
                label = "missing"
            cv2.putText(img, f"fr{rec['frame']}  {label}", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                        (0, 0, 255) if not kps else (255, 255, 255), 2)
            writer.write(img)
    finally:
        cap.release()
        writer.release()
    print(f"  overlay -> {out_path}")


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Select one racket per frame from a RacketVision 2D pass.")
    ap.add_argument("racket2d", help="<id>.racket2d.json from racketvision_extract.ipynb")
    ap.add_argument("--out", required=True, help="output <id>.rackettrack.json")
    ap.add_argument("--min-kp-score", type=float, default=MIN_KP_SCORE)
    ap.add_argument("--relax-kp-score", type=float, default=RELAX_KP_SCORE)
    ap.add_argument("--max-jump-px", type=float, default=MAX_JUMP_PX)
    ap.add_argument("--max-len-ratio", type=float, default=MAX_LEN_RATIO)
    ap.add_argument("--max-interp-gap", type=int, default=MAX_INTERP_GAP)
    ap.add_argument("--overlay", metavar="SOURCE_MP4",
                    help="also render the selected track over this clip (frame-bearing "
                         "video: keep it under data/, which is gitignored)")
    args = ap.parse_args(argv)

    with open(args.racket2d, encoding="utf-8") as fh:
        doc = json.load(fh)

    names = doc.get("keypoint_names", KEYPOINT_NAMES)
    picks = select_track(doc["frames"], min_kp_score=args.min_kp_score,
                         relax_kp_score=args.relax_kp_score, max_jump_px=args.max_jump_px,
                         max_len_ratio=args.max_len_ratio, names=names)
    filled = interpolate_gaps(picks, max_gap=args.max_interp_gap)
    out = build_track_document(doc, picks, filled,
                               min_kp_score=args.min_kp_score,
                               relax_kp_score=args.relax_kp_score,
                               max_jump_px=args.max_jump_px,
                               max_len_ratio=args.max_len_ratio,
                               max_interp_gap=args.max_interp_gap,
                               source_path=args.racket2d)

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1)

    c = out["coverage"]
    n = out["num_frames"]
    print(f"wrote {args.out}")
    print(f"  detected     {c['detected']:4d}/{n}  ({100 * c['detected'] / n:.0f}%)")
    print(f"  interpolated {c['interpolated']:4d}/{n}  ({100 * c['interpolated'] / n:.0f}%)")
    print(f"  missing      {c['missing']:4d}/{n}  ({100 * c['missing'] / n:.0f}%)")
    lens = [shaft_length_px(f["keypoints"], out["keypoint_names"])
            for f in out["frames"] if f["status"] == STATUS_DETECTED]
    if lens:
        print(f"  shaft length px: min {min(lens):.0f}  median "
              f"{statistics.median(lens):.0f}  max {max(lens):.0f}")
    if args.overlay:
        stem = args.out[:-5] if args.out.endswith(".json") else args.out
        render_overlay(out, args.overlay, stem + "_overlay.mp4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
