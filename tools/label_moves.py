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


if __name__ == "__main__":
    raise SystemExit("CLI arrives in a later task; import the functions for now.")
