"""
label_moves.py — detect WHICH badminton move each frame belongs to (Approach A).

Heuristic, transparent, CPU-only. Reads a skeleton.json, finds stroke moments
from racket-wrist speed peaks (joints are HIP-CENTERED world landmarks, so
wrist speed is body-relative — running can't fake a swing), tiles the clip
into stroke/moving/idle segments, labels strokes with explainable rules, and
writes a `moves` block back into the json (schema 1.0 -> 1.1).

Spec: docs/superpowers/specs/2026-07-17-move-recognition-design.md
v1 labels: overhead_smash, overhead_clear, drop, underarm_lift, net_shot,
drive, moving, idle. smash<->clear and drop<->net confusion is EXPECTED at
this stage; the trained classifier (Approach B) is the fix, behind the same
contract.

Usage:
  tools/.venv/Scripts/python tools/label_moves.py data/skeleton/test_3.json --report
  tools/.venv/Scripts/python tools/label_moves.py data/skeleton/test_3.json --write
  tools/.venv/Scripts/python tools/label_moves.py data/skeleton/test_3.json \
      --overlay data/raw/test_3.mp4        # debug video -> data/moves/ (gitignored)
"""

import argparse
import json
import os

import numpy as np

NUM_JOINTS, STRIDE = 33, 4
NOSE, L_SHOULDER, R_SHOULDER = 0, 11, 12
L_WRIST, R_WRIST = 15, 16
L_HIP, R_HIP = 23, 24

STROKE_LABELS = ("overhead_smash", "overhead_clear", "drop",
                 "underarm_lift", "net_shot", "drive")

# --- classification thresholds (printed by --report) ---
TH_DROP_SPEED = 4.5      # overhead below this = drop
TH_SMASH_VY = -1.5       # overhead + post-peak wrist vy below this = smash
TH_NET_Z = 2.0           # root z at/under this = net region (net z=0)
TH_NET_SPEED = 5.0       # net region + peak below this = net_shot
TH_LIFT_VY = 1.0         # upward follow-through above this = lift
POST_WINDOW_S = 0.15     # follow-through window after the peak


def load_doc(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fps_of(doc):
    return float(doc.get("source", {}).get("fps") or 30.0)


def joint_xyz(doc, frame, joint):
    jf = doc["frames"][frame]["joints_flat"]
    b = joint * STRIDE
    return np.array(jf[b:b + 3])


def joint_conf(doc, frame, joint):
    return doc["frames"][frame]["joints_flat"][joint * STRIDE + 3]


def wrist_speed(doc, hand="right", conf_cutoff=0.3):
    """Body-relative wrist speed in m/s per frame; NaN where conf < cutoff."""
    wrist = R_WRIST if hand == "right" else L_WRIST
    n, fps = len(doc["frames"]), fps_of(doc)
    pos = np.full((n, 3), np.nan)
    for i in range(n):
        if joint_conf(doc, i, wrist) >= conf_cutoff:
            pos[i] = joint_xyz(doc, i, wrist)
    speed = np.full(n, np.nan)
    d = np.linalg.norm(np.diff(pos, axis=0), axis=1) * fps
    speed[1:] = d
    speed[0] = speed[1] if n > 1 else 0.0
    # light smoothing (5-frame moving average) that keeps NaN gaps as NaN
    k = 5
    sm = np.copy(speed)
    for i in range(n):
        w = speed[max(0, i - k // 2):i + k // 2 + 1]
        if not np.isnan(speed[i]):
            sm[i] = np.nanmean(w)
    return sm


def detect_strokes(speed, fps, min_peak_speed=3.0, min_gap_s=0.5):
    """Local maxima above min_peak_speed, at least min_gap_s apart.
    Returns peak frame indices, ascending."""
    n = len(speed)
    gap = max(1, int(min_gap_s * fps))
    candidates = [i for i in range(1, n - 1)
                  if not np.isnan(speed[i]) and speed[i] >= min_peak_speed
                  and speed[i] >= np.nanmax(speed[max(0, i - gap):i + gap + 1]) - 1e-9]
    peaks = []
    for c in candidates:
        if not peaks or c - peaks[-1] >= gap:
            peaks.append(c)
        elif speed[c] > speed[peaks[-1]]:
            peaks[-1] = c
    return peaks


def root_speed(doc, smooth_k=9):
    """Court-space player speed m/s; falls back to mid-hip XZ (body drift ~0
    when hip-centered — that is fine: no court data usually also means the
    Phase-1 in-place clip, where 'moving' is meaningless anyway)."""
    n, fps = len(doc["frames"]), fps_of(doc)
    xz = np.zeros((n, 2))
    for i, fr in enumerate(doc["frames"]):
        r = fr.get("root_court_xz")
        if r and len(r) == 2:
            xz[i] = r
        else:
            hips = (joint_xyz(doc, i, L_HIP) + joint_xyz(doc, i, R_HIP)) / 2
            xz[i] = (hips[0], hips[2])
    sp = np.zeros(n)
    sp[1:] = np.linalg.norm(np.diff(xz, axis=0), axis=1) * fps
    sp[0] = sp[1] if n > 1 else 0.0
    k = np.ones(smooth_k) / smooth_k
    return np.convolve(sp, k, mode="same")


def segment_clip(doc, speed, peaks, fps, moving_speed=0.8,
                 edge_frac=0.25, edge_floor=1.0,
                 min_half_s=0.15, max_half_s=1.0):
    """Tile frames 0..n-1 into stroke ('stroke', labeled later) / moving /
    idle segments. No gaps, no overlaps; peak inside its stroke segment."""
    n = len(speed)
    windows = []
    for p in peaks:
        cut = max(edge_frac * speed[p], edge_floor)
        lo_lim = p - int(max_half_s * fps)
        hi_lim = p + int(max_half_s * fps)
        lo = p
        while lo - 1 >= max(0, lo_lim) and (np.isnan(speed[lo - 1]) or speed[lo - 1] > cut):
            lo -= 1
        hi = p
        while hi + 1 <= min(n - 1, hi_lim) and (np.isnan(speed[hi + 1]) or speed[hi + 1] > cut):
            hi += 1
        lo = min(lo, p - int(min_half_s * fps))
        hi = max(hi, p + int(min_half_s * fps))
        lo, hi = max(0, lo), min(n - 1, hi)
        if windows and lo <= windows[-1][1]:          # overlapping strokes: split at midpoint
            mid = (windows[-1][2] + p) // 2
            windows[-1] = (windows[-1][0], mid, windows[-1][2])
            lo = mid + 1
        windows.append((lo, hi, p))

    rsp = root_speed(doc)

    def fill_gap(a, b, out):
        """Label frames a..b (inclusive) as moving/idle runs by root speed."""
        if a > b:
            return
        run_start, run_moving = a, bool(rsp[a] > moving_speed)
        for i in range(a + 1, b + 2):
            moving = bool(rsp[i] > moving_speed) if i <= b else None
            if i > b or moving != run_moving:
                out.append({"start": run_start, "end": i - 1,
                            "label": "moving" if run_moving else "idle"})
                if i <= b:
                    run_start, run_moving = i, moving

    segments, cursor = [], 0
    for lo, hi, p in windows:
        fill_gap(cursor, lo - 1, segments)
        segments.append({"start": lo, "end": hi, "peak": int(p), "label": "stroke"})
        cursor = hi + 1
    fill_gap(cursor, n - 1, segments)
    return segments


def stroke_features(doc, seg, speed, fps, hand="right"):
    wrist = R_WRIST if hand == "right" else L_WRIST
    p = seg["peak"]
    wy = joint_xyz(doc, p, wrist)[1]
    nose_y = joint_xyz(doc, p, NOSE)[1]
    hip_y = (joint_xyz(doc, p, L_HIP)[1] + joint_xyz(doc, p, R_HIP)[1]) / 2
    k = max(1, int(POST_WINDOW_S * fps))
    hi = min(len(doc["frames"]) - 1, p + k)
    post_vy = ((joint_xyz(doc, hi, wrist)[1] - wy) * fps / (hi - p)) if hi > p else 0.0
    r = doc["frames"][p].get("root_court_xz")
    root_z = abs(r[1]) if r and len(r) == 2 else 99.0   # 99 = unknown, never "near net"
    return {"peak_speed": float(np.nanmax(speed[seg["start"]:seg["end"] + 1])),
            "wrist_above_nose": bool(wy > nose_y),
            "wrist_below_hip": bool(wy < hip_y),
            "post_vy": float(post_vy), "root_z": float(root_z)}


def _confidence(margin_frac, second_agrees):
    conf = 0.5
    if margin_frac >= 0.5:
        conf += 0.2
    if second_agrees:
        conf += 0.1
    return min(conf, 0.9)


def classify_stroke(doc, seg, speed, fps, hand="right"):
    f = stroke_features(doc, seg, speed, fps, hand)
    ps, vy = f["peak_speed"], f["post_vy"]
    if f["wrist_above_nose"]:
        if ps < TH_DROP_SPEED:
            return "drop", _confidence((TH_DROP_SPEED - ps) / TH_DROP_SPEED, vy > TH_SMASH_VY), f
        if vy < TH_SMASH_VY:
            return "overhead_smash", _confidence((TH_SMASH_VY - vy) / abs(TH_SMASH_VY), ps > 6.0), f
        return "overhead_clear", _confidence((vy - TH_SMASH_VY) / abs(TH_SMASH_VY), ps >= TH_DROP_SPEED), f
    if f["root_z"] <= TH_NET_Z and ps < TH_NET_SPEED:
        return "net_shot", _confidence((TH_NET_Z - f["root_z"]) / TH_NET_Z, ps < TH_DROP_SPEED), f
    if f["wrist_below_hip"] or vy > TH_LIFT_VY:
        return "underarm_lift", _confidence(max(vy - TH_LIFT_VY, 0.0) / TH_LIFT_VY,
                                            f["wrist_below_hip"]), f
    return "drive", _confidence(0.0, not f["wrist_above_nose"]), f


def label_segments(doc, segments, speed, fps, hand="right"):
    for s in segments:
        if s["label"] == "stroke":
            label, conf, _ = classify_stroke(doc, s, speed, fps, hand)
            s["label"], s["confidence"] = label, round(conf, 2)
    return segments


if __name__ == "__main__":
    raise SystemExit("CLI arrives in a later task; import the functions for now.")
