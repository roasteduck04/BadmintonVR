# Move Recognition (Approach A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Label every frame of a clip with the badminton move being performed (heuristic rules on skeleton.json) and display the label on the Unity twin during replay.

**Architecture:** `tools/label_moves.py` detects stroke moments from racket-wrist speed peaks (hip-centered landmarks → body-relative speed, so locomotion can't fake a swing), tiles the clip into stroke/`moving`/`idle` segments, classifies strokes with transparent rules, and writes a `moves` block into skeleton.json (schema 1.0 → 1.1). Unity's `SkeletonDoc` parses the optional block; a new `MoveLabelHUD` shows the current label + a segment timeline. Spec: `docs/superpowers/specs/2026-07-17-move-recognition-design.md`.

**Tech Stack:** Python 3.12 (venv at `tools/.venv`, numpy + scipy already installed, pytest added by Task 1), Unity 6000.1.4f1 / C# with JsonUtility, new Input System.

## Global Constraints

- Python runs via `tools/.venv/Scripts/python` — never the system python.
- No NVIDIA GPU: everything here is CPU-only (it is — rules, not models).
- Privacy: never commit frame-bearing images/videos. Overlay videos go to `data/moves/` and `data/**/*.mp4` must remain gitignored (Task 5 verifies).
- skeleton.json is the load-bearing Python↔Unity contract. The `moves` block is OPTIONAL: old files must keep loading in Unity, and unknown labels must not crash it.
- Unity: `UnityEngine.Input.*` throws (new Input System) — use the `#if ENABLE_INPUT_SYSTEM` + `Keyboard.current[k].wasPressedThisFrame` pattern.
- Runtime helper GameObjects must live at the SCENE ROOT (SkeletonRenderer.Clear() destroys twin children) — `MoveLabelHUD` is OnGUI-only, so this does not bite, but do not add child objects to the twin.
- MediaPipe joint indices: nose 0, shoulders 11/12, elbows 13/14, wrists 15/16 (right=16), hips 23/24. `joints_flat` = 33 × [x, y, z, conf], HIP-CENTERED world meters, Y up.
- Frame fields: `frame_id`, `time`, `root_court_xz` ([x,z] court meters, net z=0, baseline z=6.70; may be null), `root_confidence`, `joints_flat`.
- Racket hand default: right (project decision), `--hand left` must exist.
- Work happens on branch `spec/move-recognition` (PR #1). Do NOT merge the PR — the user merges when they're satisfied.

## File Structure

- Create `tools/label_moves.py` — the whole Approach-A tool (loading, speed, peaks, segmentation, rules, report, write, overlay). One file, functions importable for tests, mirroring the one-file style of `check_position.py`.
- Create `tools/tests/__init__.py`, `tools/tests/test_label_moves.py` — pytest suite on SYNTHETIC docs (no real-data dependency).
- Modify `Assets/Scripts/SkeletonPlayer/SkeletonData.cs` — `MoveSegment` class, `moves` array, `HasMoves`, `MoveAt(frame)`.
- Create `Assets/Scripts/SkeletonPlayer/MoveLabelHUD.cs` — current-move banner + segment timeline, OnGUI, toggle M.
- Create `Assets/Editor/MoveLabelSetup.cs` — `Tools ▸ Badminton ▸ Move Label ▸ Add To Twin / Remove` (mirrors `DebugHUDSetup.cs`).
- Data: `data/skeleton/test_{3,4,5}.json` + `Assets/StreamingAssets/skeleton/test_{3,4,5}.json` gain `moves` blocks (committed — they are JSON, not imagery). test_1/test_2 get labeled too (no racket → mostly moving/idle; harmless and consistent).
- Modify `docs/PROGRESS.md` — dated entry at the end.

---

### Task 1: Speed + stroke-peak detection (Python core)

**Files:**
- Create: `tools/tests/__init__.py` (empty)
- Create: `tools/tests/test_label_moves.py`
- Create: `tools/label_moves.py`

**Interfaces:**
- Produces: `load_doc(path) -> dict`; `wrist_speed(doc, hand="right", conf_cutoff=0.3) -> np.ndarray` (m/s per frame, `np.nan` where wrist conf < cutoff); `detect_strokes(speed, fps, min_peak_speed=3.0, min_gap_s=0.5) -> list[int]` (peak frame indices). Joint constants `R_WRIST=16`, `L_WRIST=15`.

- [ ] **Step 1: Install pytest into the venv**

```bash
tools/.venv/Scripts/python -m pip install pytest --quiet
```

- [ ] **Step 2: Write the failing tests**

`tools/tests/__init__.py`: empty file. `tools/tests/test_label_moves.py`:

```python
"""Tests for tools/label_moves.py on SYNTHETIC skeleton docs."""
import sys, os
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from label_moves import (load_doc, wrist_speed, detect_strokes,
                         R_WRIST, NUM_JOINTS, STRIDE)


def make_doc(n_frames=200, fps=60.0, root_xz=(0.0, 4.0)):
    """Neutral standing doc: all joints at fixed plausible heights, conf 1.0."""
    frames = []
    for i in range(n_frames):
        jf = [0.0] * (NUM_JOINTS * STRIDE)
        for j in range(NUM_JOINTS):
            jf[j * STRIDE + 1] = 1.0   # y
            jf[j * STRIDE + 3] = 1.0   # conf
        frames.append({"frame_id": i, "time": i / fps,
                       "root_court_xz": list(root_xz),
                       "root_confidence": 1.0, "joints_flat": jf})
    return {"schema_version": "1.0", "video_id": "synth",
            "source": {"type": "phone_static", "fps": fps},
            "frames": frames}


def set_joint(doc, frame, joint, x=None, y=None, z=None, conf=None):
    jf = doc["frames"][frame]["joints_flat"]
    b = joint * STRIDE
    for off, v in enumerate((x, y, z, conf)):
        if v is not None:
            jf[b + off] = v


def add_swing(doc, peak_frame, peak_speed=6.0, width=8):
    """Move the right wrist so its speed ramps to ~peak_speed at peak_frame."""
    fps = doc["source"]["fps"]
    x = 0.0
    for i in range(peak_frame - width, peak_frame + width + 1):
        # triangular speed profile, motion along +x
        s = peak_speed * (1 - abs(i - peak_frame) / width)
        x += s / fps
        set_joint(doc, i, R_WRIST, x=x)


def test_wrist_speed_still_is_zero():
    doc = make_doc()
    sp = wrist_speed(doc)
    assert sp.shape == (200,)
    assert np.nanmax(sp) < 0.1


def test_wrist_speed_moving():
    doc = make_doc()
    add_swing(doc, peak_frame=100, peak_speed=6.0)
    sp = wrist_speed(doc)
    assert np.nanmax(sp[92:109]) > 3.0   # smoothing lowers the 6.0 peak


def test_wrist_speed_nan_when_low_conf():
    doc = make_doc()
    set_joint(doc, 50, R_WRIST, conf=0.1)
    sp = wrist_speed(doc)
    assert np.isnan(sp[50])


def test_detect_strokes_two_peaks():
    doc = make_doc(n_frames=400)
    add_swing(doc, 100); add_swing(doc, 300)
    sp = wrist_speed(doc)
    peaks = detect_strokes(sp, fps=60.0)
    assert len(peaks) == 2
    assert abs(peaks[0] - 100) <= 3 and abs(peaks[1] - 300) <= 3


def test_detect_strokes_min_gap_merges():
    doc = make_doc(n_frames=400)
    add_swing(doc, 100); add_swing(doc, 112)   # 0.2 s apart < 0.5 s min gap
    sp = wrist_speed(doc)
    assert len(detect_strokes(sp, fps=60.0)) == 1


def test_detect_strokes_below_threshold_ignored():
    doc = make_doc(n_frames=400)
    add_swing(doc, 100, peak_speed=1.0)        # gentle drift, not a stroke
    sp = wrist_speed(doc)
    assert detect_strokes(sp, fps=60.0) == []
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `tools/.venv/Scripts/python -m pytest tools/tests -v`
Expected: collection error — `ModuleNotFoundError: No module named 'label_moves'`.

- [ ] **Step 4: Implement `tools/label_moves.py` (loading, speed, peaks)**

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `tools/.venv/Scripts/python -m pytest tools/tests -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add tools/label_moves.py tools/tests/
git commit -m "label_moves: wrist speed + stroke-peak detection (TDD core)"
```

---

### Task 2: Segmentation — tile the clip into stroke/moving/idle

**Files:**
- Modify: `tools/label_moves.py`
- Modify: `tools/tests/test_label_moves.py`

**Interfaces:**
- Consumes: `wrist_speed`, `detect_strokes` from Task 1.
- Produces: `root_speed(doc) -> np.ndarray` (court-space m/s, mid-hip XZ fallback when no `root_court_xz`); `segment_clip(doc, speed, peaks, fps, moving_speed=0.8) -> list[dict]` — dicts `{"start","end","label"}` (+`"peak"` on strokes, label placeholder `"stroke"`), tiling frames 0..n-1 with no gaps/overlaps; stroke window = frames around the peak where speed > max(0.25 × peak speed, 1.0), clamped to 0.15–1.0 s each side.

- [ ] **Step 1: Write the failing tests** (append to `tools/tests/test_label_moves.py`)

```python
from label_moves import root_speed, segment_clip


def assert_tiles(segments, n_frames):
    assert segments[0]["start"] == 0
    assert segments[-1]["end"] == n_frames - 1
    for a, b in zip(segments, segments[1:]):
        assert b["start"] == a["end"] + 1


def test_segment_tiling_no_strokes_idle():
    doc = make_doc()
    sp = wrist_speed(doc)
    segs = segment_clip(doc, sp, [], fps=60.0)
    assert_tiles(segs, 200)
    assert [s["label"] for s in segs] == ["idle"]


def test_segment_stroke_window_and_tiling():
    doc = make_doc(n_frames=400)
    add_swing(doc, 200)
    sp = wrist_speed(doc)
    segs = segment_clip(doc, sp, detect_strokes(sp, 60.0), fps=60.0)
    assert_tiles(segs, 400)
    strokes = [s for s in segs if s["label"] == "stroke"]
    assert len(strokes) == 1
    s = strokes[0]
    assert s["start"] <= 200 <= s["end"] and s["peak"] == pytest_approx_peak(s)
    dur = (s["end"] - s["start"] + 1) / 60.0
    assert 0.2 <= dur <= 2.0        # spec acceptance bounds


def pytest_approx_peak(s):
    return s["peak"]  # peak must lie inside its own segment


def test_segment_moving_vs_idle_by_root():
    doc = make_doc(n_frames=200)
    for i in range(200):             # walk 2 m/s along +z in court space
        doc["frames"][i]["root_court_xz"] = [0.0, 2.0 + 2.0 * i / 60.0]
    sp = wrist_speed(doc)
    segs = segment_clip(doc, sp, [], fps=60.0)
    assert [s["label"] for s in segs] == ["moving"]


def test_root_speed_falls_back_to_hips():
    doc = make_doc()
    for f in doc["frames"]:
        f["root_court_xz"] = None
    assert root_speed(doc).shape == (200,)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `tools/.venv/Scripts/python -m pytest tools/tests -v`
Expected: 4 new tests FAIL with `ImportError: cannot import name 'root_speed'`.

- [ ] **Step 3: Implement** (append to `tools/label_moves.py`, above the `__main__` guard)

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `tools/.venv/Scripts/python -m pytest tools/tests -v`
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/label_moves.py tools/tests/test_label_moves.py
git commit -m "label_moves: tile clip into stroke/moving/idle segments"
```

---

### Task 3: Rule classification + confidence

**Files:**
- Modify: `tools/label_moves.py`
- Modify: `tools/tests/test_label_moves.py`

**Interfaces:**
- Consumes: `segment_clip` output (segments with `"label": "stroke"`).
- Produces: `classify_stroke(doc, seg, speed, fps, hand="right") -> (label, confidence, dict_of_features)`; `label_segments(doc, segments, speed, fps, hand="right") -> segments` (in place: every `"stroke"` label replaced by a v1 stroke label + `"confidence"`). Feature dict keys: `peak_speed`, `wrist_above_nose`, `wrist_below_hip`, `post_vy`, `root_z`.

Rules (deciding feature first; thresholds are constants at module top so `--report` can print them):
- overhead (`wrist_above_nose`): `drop` if `peak_speed < 4.5`; else `overhead_smash` if `post_vy < -1.5` (mean wrist vertical velocity over 0.15 s after the peak — fast downward follow-through); else `overhead_clear`.
- not overhead: `net_shot` if `root_z <= 2.0` (near the net, court z: net 0 → baseline 6.70) and `peak_speed < 5.0`; else `underarm_lift` if `wrist_below_hip` or `post_vy > 1.0`; else `drive`.
- confidence: 0.5 base, +0.2 if the deciding feature clears its threshold by ≥50 % of the threshold's magnitude, +0.1 if a second listed feature agrees, capped 0.9. `moving`/`idle` get no confidence key.

- [ ] **Step 1: Write the failing tests** (append)

```python
from label_moves import classify_stroke, label_segments


def make_stroke_doc(wrist_y_at_peak, post_vy=0.0, peak_speed=6.0,
                    root_z=4.0, n=400, peak=200):
    doc = make_doc(n_frames=n, root_xz=(0.0, root_z))
    add_swing(doc, peak, peak_speed=peak_speed)
    for i in range(n):
        set_joint(doc, i, 0, y=1.6)                 # nose at 1.6
        set_joint(doc, i, 23, y=1.0); set_joint(doc, i, 24, y=1.0)  # hips
    set_joint(doc, peak, R_WRIST, y=wrist_y_at_peak)
    fps = doc["source"]["fps"]
    for k in range(1, int(0.15 * fps) + 1):         # follow-through slope
        set_joint(doc, peak + k, R_WRIST, y=wrist_y_at_peak + post_vy * k / fps)
    return doc


def run_classify(doc):
    sp = wrist_speed(doc)
    segs = segment_clip(doc, sp, detect_strokes(sp, 60.0), fps=60.0)
    seg = next(s for s in segs if s["label"] == "stroke")
    return classify_stroke(doc, seg, sp, 60.0)


def test_overhead_fast_down_is_smash():
    label, conf, feats = run_classify(make_stroke_doc(2.0, post_vy=-3.0, peak_speed=7.0))
    assert label == "overhead_smash" and conf >= 0.5 and feats["wrist_above_nose"]


def test_overhead_gentle_is_drop():
    label, _, _ = run_classify(make_stroke_doc(2.0, post_vy=-0.5, peak_speed=3.5))
    assert label == "drop"


def test_overhead_up_follow_is_clear():
    label, _, _ = run_classify(make_stroke_doc(2.0, post_vy=1.0, peak_speed=7.0))
    assert label == "overhead_clear"


def test_low_wrist_upward_is_lift():
    label, _, _ = run_classify(make_stroke_doc(0.6, post_vy=2.0, peak_speed=6.0))
    assert label == "underarm_lift"


def test_near_net_gentle_is_net_shot():
    label, _, _ = run_classify(make_stroke_doc(1.2, post_vy=0.0, peak_speed=3.5, root_z=1.0))
    assert label == "net_shot"


def test_mid_height_horizontal_is_drive():
    label, _, _ = run_classify(make_stroke_doc(1.2, post_vy=0.0, peak_speed=6.0))
    assert label == "drive"


def test_label_segments_replaces_all_strokes():
    doc = make_stroke_doc(2.0, post_vy=-3.0, peak_speed=7.0)
    sp = wrist_speed(doc)
    segs = label_segments(doc, segment_clip(doc, sp, detect_strokes(sp, 60.0), fps=60.0),
                          sp, 60.0)
    assert all(s["label"] != "stroke" for s in segs)
    stroke = next(s for s in segs if "peak" in s)
    assert stroke["label"] in ("overhead_smash", "overhead_clear", "drop",
                               "underarm_lift", "net_shot", "drive")
    assert 0.0 < stroke["confidence"] <= 0.9
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `tools/.venv/Scripts/python -m pytest tools/tests -v`
Expected: new tests FAIL with `ImportError: cannot import name 'classify_stroke'`.

- [ ] **Step 3: Implement** (append to `tools/label_moves.py`; constants at module top, under the joint indices)

```python
# --- classification thresholds (printed by --report; tune via flags later) ---
TH_DROP_SPEED = 4.5      # overhead below this = drop
TH_SMASH_VY = -1.5       # overhead + post-peak wrist vy below this = smash
TH_NET_Z = 2.0           # root z at/under this = net region (net z=0)
TH_NET_SPEED = 5.0       # net region + peak below this = net_shot
TH_LIFT_VY = 1.0         # upward follow-through above this = lift
POST_WINDOW_S = 0.15     # follow-through window after the peak
```

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `tools/.venv/Scripts/python -m pytest tools/tests -v`
Expected: 17 passed.

- [ ] **Step 5: Commit**

```bash
git add tools/label_moves.py tools/tests/test_label_moves.py
git commit -m "label_moves: transparent rule classification with margin confidence"
```

---

### Task 4: CLI — report, write (schema bump), run on real clips

**Files:**
- Modify: `tools/label_moves.py` (replace the `__main__` guard)
- Modify: `tools/tests/test_label_moves.py`
- Data: `data/skeleton/test_{1..5}.json`, `Assets/StreamingAssets/skeleton/test_{1..5}.json`

**Interfaces:**
- Consumes: everything above.
- Produces: `build_moves(doc, hand="right", min_peak_speed=3.0) -> list[dict]` (labeled, tiled, JSON-ready); `write_moves(path, moves) -> None` (sets `schema_version` to `"1.1"`, replaces any existing `moves`, preserves all other keys); CLI described in the module docstring. The written JSON is what Unity Task 6 parses — key names exactly `start`, `peak`, `end`, `label`, `confidence`.

- [ ] **Step 1: Write the failing tests** (append)

```python
import json, tempfile
from label_moves import build_moves, write_moves


def test_build_moves_end_to_end():
    doc = make_stroke_doc(2.0, post_vy=-3.0, peak_speed=7.0)
    moves = build_moves(doc)
    assert_tiles(moves, 400)
    assert any(m["label"] == "overhead_smash" for m in moves)


def test_write_moves_bumps_schema_and_is_idempotent():
    doc = make_stroke_doc(2.0, post_vy=-3.0, peak_speed=7.0)
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "clip.json")
        with open(p, "w") as f:
            json.dump(doc, f)
        moves = build_moves(doc)
        write_moves(p, moves)
        write_moves(p, moves)                     # idempotent
        out = json.load(open(p))
        assert out["schema_version"] == "1.1"
        assert out["moves"] == moves
        assert out["video_id"] == "synth"         # nothing else lost
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `tools/.venv/Scripts/python -m pytest tools/tests -v`
Expected: `ImportError: cannot import name 'build_moves'`.

- [ ] **Step 3: Implement** (append; then replace the `__main__` guard entirely)

```python
def build_moves(doc, hand="right", min_peak_speed=3.0, conf_cutoff=0.3):
    fps = fps_of(doc)
    speed = wrist_speed(doc, hand, conf_cutoff)
    peaks = detect_strokes(speed, fps, min_peak_speed)
    segs = label_segments(doc, segment_clip(doc, speed, peaks, fps), speed, fps, hand)
    for s in segs:                       # JSON-ready: plain ints/strs/floats
        s["start"], s["end"] = int(s["start"]), int(s["end"])
        if "peak" in s:
            s["peak"] = int(s["peak"])
    return segs


def write_moves(path, moves):
    doc = load_doc(path)
    doc["schema_version"] = "1.1"
    doc["moves"] = moves
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, separators=(",", ":"))


def print_report(doc, moves, speed, fps, hand):
    print(f"clip {doc.get('video_id')}  fps {fps:.1f}  frames {len(doc['frames'])}")
    print(f"thresholds: drop<{TH_DROP_SPEED} m/s  smash vy<{TH_SMASH_VY}  "
          f"net z<={TH_NET_Z} & <{TH_NET_SPEED} m/s  lift vy>{TH_LIFT_VY}")
    for m in moves:
        t0, t1 = m["start"] / fps, m["end"] / fps
        line = f"  {t0:7.2f}-{t1:7.2f}s  {m['label']:<15}"
        if "peak" in m:
            seg = dict(m); seg["label"] = "stroke"
            feats = stroke_features(doc, seg, speed, fps, hand)
            line += (f" conf {m.get('confidence', 0):.2f}  peak {feats['peak_speed']:.1f} m/s"
                     f"  vy {feats['post_vy']:+.1f}  root_z {feats['root_z']:.1f}"
                     f"  {'overhead' if feats['wrist_above_nose'] else 'low'}")
        print(line)
    strokes = [m for m in moves if "peak" in m]
    print(f"{len(strokes)} strokes / {len(moves)} segments")


def main():
    ap = argparse.ArgumentParser(description="Label badminton moves in a skeleton.json")
    ap.add_argument("skeleton", help="e.g. data/skeleton/test_3.json")
    ap.add_argument("--hand", choices=("right", "left"), default="right")
    ap.add_argument("--min-peak-speed", type=float, default=3.0)
    ap.add_argument("--report", action="store_true", help="print the timeline (default)")
    ap.add_argument("--write", action="store_true",
                    help="write moves into the json AND the StreamingAssets copy")
    args = ap.parse_args()

    doc = load_doc(args.skeleton)
    fps = fps_of(doc)
    speed = wrist_speed(doc, args.hand)
    moves = build_moves(doc, args.hand, args.min_peak_speed)
    print_report(doc, moves, speed, fps, args.hand)

    if args.write:
        write_moves(args.skeleton, moves)
        stem = os.path.splitext(os.path.basename(args.skeleton))[0]
        ua = os.path.join("Assets", "StreamingAssets", "skeleton", stem + ".json")
        if os.path.exists(ua):
            write_moves(ua, moves)
            print(f"wrote moves -> {args.skeleton} and {ua}")
        else:
            print(f"wrote moves -> {args.skeleton} (no StreamingAssets copy found)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `tools/.venv/Scripts/python -m pytest tools/tests -v`
Expected: 19 passed.

- [ ] **Step 5: Run on the real clips and sanity-check the timelines**

```bash
for c in test_1 test_2 test_3 test_4 test_5; do
  tools/.venv/Scripts/python tools/label_moves.py data/skeleton/$c.json --report | tail -3
done
```

Expected sanity (tune `--min-peak-speed` if violated, then re-run):
- stroke count is plausible (a 25 s active clip has ~5–30 strokes, not 0 and not 200);
- test_1/test_2 (no racket) may still show "strokes" (arm swings) — that is fine, they're gated by the per-clip racket flag on the Unity side only for the racket visual; labels are still honest arm-swing classifications;
- no stroke segment shorter than 0.2 s or longer than 2 s (spec acceptance).
Then read one full `--report` for test_3 and eyeball against the video (open `data/raw/test_3.mp4` or use Video Compare later in Unity).

- [ ] **Step 6: Write the labels into all clips (both copies)**

```bash
for c in test_1 test_2 test_3 test_4 test_5; do
  tools/.venv/Scripts/python tools/label_moves.py data/skeleton/$c.json --write | tail -1
done
```

Expected: each prints `wrote moves -> data/skeleton/<c>.json and Assets/StreamingAssets/skeleton/<c>.json`.

- [ ] **Step 7: Commit (JSONs are data, not imagery — committable)**

```bash
git add tools/label_moves.py tools/tests/test_label_moves.py data/skeleton/*.json Assets/StreamingAssets/skeleton/*.json
git commit -m "label_moves: CLI report/write, schema 1.1, all clips labeled"
```

---

### Task 5: Overlay debug video (`--overlay`)

**Files:**
- Modify: `tools/label_moves.py` (add `--overlay` to `main`, plus `render_overlay`)

**Interfaces:**
- Consumes: `build_moves` output; the raw video.
- Produces: `render_overlay(video_path, moves, fps_doc, out_path)` — writes an mp4 with the current label burned in top-left. Output dir `data/moves/` (created), which MUST be gitignored (verify; `*.mp4` under data/ already is — if `git check-ignore` fails, add `data/moves/` to `.gitignore`).

- [ ] **Step 1: Implement `render_overlay`** (append; no unit test — it's a visual artifact; the assertion is the ignore-check + eyeball)

```python
def render_overlay(video_path, moves, doc_fps, out_path):
    import cv2
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise SystemExit(f"cannot open {video_path}")
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    vfps = cap.get(cv2.CAP_PROP_FPS) or doc_fps
    out = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"), vfps, (w, h))
    seg_i, i = 0, 0
    while True:
        ok, img = cap.read()
        if not ok:
            break
        f = int(round(i * doc_fps / vfps))        # video frame -> skeleton frame
        while seg_i + 1 < len(moves) and f > moves[seg_i]["end"]:
            seg_i += 1
        m = moves[seg_i]
        text = m["label"] + (f"  {m['confidence']:.2f}" if "confidence" in m else "")
        cv2.rectangle(img, (10, 10), (560, 70), (0, 0, 0), -1)
        cv2.putText(img, text, (20, 55), cv2.FONT_HERSHEY_SIMPLEX, 1.4,
                    (80, 220, 255), 3)
        out.write(img); i += 1
    cap.release(); out.release()
    print(f"overlay -> {out_path}")
```

In `main()`, add the flag and the call:

```python
    ap.add_argument("--overlay", metavar="VIDEO",
                    help="raw video path; writes data/moves/<stem>_moves.mp4 (gitignored)")
```

```python
    if args.overlay:
        os.makedirs(os.path.join("data", "moves"), exist_ok=True)
        stem = os.path.splitext(os.path.basename(args.skeleton))[0]
        render_overlay(args.overlay, moves, fps,
                       os.path.join("data", "moves", stem + "_moves.mp4"))
```

- [ ] **Step 2: Run it on test_3 and verify privacy + correctness**

```bash
tools/.venv/Scripts/python tools/label_moves.py data/skeleton/test_3.json --overlay data/raw/test_3.mp4
git check-ignore -v data/moves/test_3_moves.mp4
```

Expected: overlay written; `git check-ignore` prints a matching rule (if it prints nothing, ADD `data/moves/` to `.gitignore` before anything else). Then watch ~20 s of the overlay: labels change at plausible moments.

- [ ] **Step 3: Full suite still green, then commit**

```bash
tools/.venv/Scripts/python -m pytest tools/tests -q
git add tools/label_moves.py .gitignore
git commit -m "label_moves: --overlay debug video (output gitignored)"
```

---

### Task 6: Unity — parse `moves` in SkeletonDoc

**Files:**
- Modify: `Assets/Scripts/SkeletonPlayer/SkeletonData.cs`

**Interfaces:**
- Consumes: the JSON written by Task 4 (keys `start`, `peak`, `end`, `label`, `confidence`).
- Produces (for Task 7): `MoveSegment` class (`int start, peak, end; string label; float confidence`); on `SkeletonDoc`: `MoveSegment[] moves;`, `bool HasMoves`, `MoveSegment MoveAt(int frame)` (binary search; null when no moves or out of range).

- [ ] **Step 1: Add the types** — in `SkeletonData.cs`, insert after the `SkeletonFrame` class:

```csharp
    [Serializable]
    public class MoveSegment
    {
        public int start;
        public int peak;        // 0 when absent (moving/idle) — JsonUtility default
        public int end;
        public string label;    // may be a label Unity doesn't know — display raw
        public float confidence;
    }
```

Inside `SkeletonDoc`, after `public SkeletonFrame[] frames;`:

```csharp
        public MoveSegment[] moves;   // optional (schema 1.1) — null on old files
```

And after `RootConf`:

```csharp
        /// <summary>True if this clip carries move labels (schema 1.1 `moves`).</summary>
        public bool HasMoves => moves != null && moves.Length > 0;

        /// <summary>Segment containing this frame, or null. Segments tile the
        /// clip and are sorted, so binary search.</summary>
        public MoveSegment MoveAt(int frame)
        {
            if (!HasMoves) return null;
            int lo = 0, hi = moves.Length - 1;
            while (lo <= hi)
            {
                int mid = (lo + hi) / 2;
                var m = moves[mid];
                if (frame < m.start) hi = mid - 1;
                else if (frame > m.end) lo = mid + 1;
                else return m;
            }
            return null;
        }
```

- [ ] **Step 2: Validate + console check**

Validate `Assets/Scripts/SkeletonPlayer/SkeletonData.cs` (unity-mcp `Unity_ValidateScript`, standard) — expect 0 errors. Then check the Unity console (`Unity_GetConsoleLogs`, errors) after focus/recompile — expect 0 errors. Old clips (no `moves`) must still load: JsonUtility leaves `moves` null → `HasMoves` false.

- [ ] **Step 3: Commit**

```bash
git add Assets/Scripts/SkeletonPlayer/SkeletonData.cs
git commit -m "Unity: SkeletonDoc parses optional moves block (schema 1.1)"
```

---

### Task 7: Unity — MoveLabelHUD + menu

**Files:**
- Create: `Assets/Scripts/SkeletonPlayer/MoveLabelHUD.cs`
- Create: `Assets/Editor/MoveLabelSetup.cs`

**Interfaces:**
- Consumes: `SkeletonDoc.HasMoves` / `MoveAt(int)` / `MoveSegment` (Task 6); `SkeletonPlayback` members `Doc` and `CurrentFrame` (existing — same usage as `PipelineDebugHUD`).
- Produces: menu `Tools ▸ Badminton ▸ Move Label ▸ Add To Twin / Remove`; runtime banner + timeline, M toggles.

- [ ] **Step 1: Create `Assets/Scripts/SkeletonPlayer/MoveLabelHUD.cs`**

```csharp
using UnityEngine;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
#endif

namespace BadmintonVR.SkeletonPlayer
{
    /// <summary>
    /// Subtitle track for the twin: shows the current move label (from the
    /// clip's `moves` block, schema 1.1) as a banner, plus a colored segment
    /// timeline with a playhead. Zero inference — labels come from
    /// tools/label_moves.py. M toggles. No child objects are added anywhere
    /// (OnGUI only), so the SkeletonRenderer.Clear() rule is not a concern.
    /// </summary>
    [RequireComponent(typeof(SkeletonPlayback))]
    public class MoveLabelHUD : MonoBehaviour
    {
        public KeyCode toggleKey = KeyCode.M;
        [Tooltip("Timeline bar height in pixels.")]
        public float barHeight = 14f;

        SkeletonPlayback _playback;
        bool _visible = true;
        Texture2D _white;

        void Awake()
        {
            _playback = GetComponent<SkeletonPlayback>();
            _white = Texture2D.whiteTexture;
        }

        void Update()
        {
            if (TogglePressed()) _visible = !_visible;
        }

        static Color LabelColor(string label)
        {
            switch (label)
            {
                case "overhead_smash": return new Color(0.95f, 0.25f, 0.2f);
                case "overhead_clear": return new Color(0.25f, 0.6f, 0.95f);
                case "drop":           return new Color(0.95f, 0.75f, 0.2f);
                case "underarm_lift":  return new Color(0.5f, 0.85f, 0.4f);
                case "net_shot":       return new Color(0.85f, 0.45f, 0.9f);
                case "drive":          return new Color(0.35f, 0.9f, 0.85f);
                case "moving":         return new Color(0.55f, 0.55f, 0.55f);
                case "idle":           return new Color(0.35f, 0.35f, 0.35f);
                default:               return Color.white;   // unknown label: still shown
            }
        }

        void OnGUI()
        {
            if (!_visible) return;
            var doc = _playback.Doc;
            if (doc == null || !doc.HasMoves) return;

            int f = _playback.CurrentFrame;
            var cur = doc.MoveAt(f);

            // banner, top-center
            string text = cur == null ? "-" :
                cur.confidence > 0f ? $"{cur.label}  ({cur.confidence:F2})" : cur.label;
            var style = new GUIStyle(GUI.skin.box)
            {
                fontSize = 28, alignment = TextAnchor.MiddleCenter,
                normal = { textColor = cur == null ? Color.white : LabelColor(cur.label) }
            };
            GUI.Box(new Rect(Screen.width / 2f - 180, 8, 360, 46), text, style);

            // timeline bar, bottom
            float y = Screen.height - barHeight - 8, w = Screen.width - 16f;
            int n = doc.FrameCount;
            for (int i = 0; i < doc.moves.Length; i++)
            {
                var m = doc.moves[i];
                float x0 = 8 + w * m.start / n, x1 = 8 + w * (m.end + 1) / n;
                GUI.color = LabelColor(m.label);
                GUI.DrawTexture(new Rect(x0, y, x1 - x0, barHeight), _white);
            }
            GUI.color = Color.white;   // playhead
            GUI.DrawTexture(new Rect(8 + w * f / n - 1, y - 3, 2, barHeight + 6), _white);
        }

        bool TogglePressed()
        {
#if ENABLE_INPUT_SYSTEM
            var kb = Keyboard.current;
            if (kb == null) return false;
            Key k = System.Enum.TryParse(toggleKey.ToString(), out Key parsed) ? parsed : Key.M;
            return kb[k].wasPressedThisFrame;
#else
            return Input.GetKeyDown(toggleKey);
#endif
        }
    }
}
```

- [ ] **Step 2: Create `Assets/Editor/MoveLabelSetup.cs`** (mirror of `DebugHUDSetup.cs`)

```csharp
using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using BadmintonVR.SkeletonPlayer;

/// <summary>
/// Tools > Badminton > Move Label
/// Adds/removes the move-label subtitle HUD (banner + segment timeline) on
/// the scene's twin(s). Labels come from the clip's `moves` block — run
/// tools/label_moves.py --write first. M toggles at runtime.
/// </summary>
public static class MoveLabelSetup
{
    [MenuItem("Tools/Badminton/Move Label/Add To Twin")]
    public static void Add()
    {
        var playbacks = Object.FindObjectsByType<SkeletonPlayback>(
            FindObjectsInactive.Include, FindObjectsSortMode.None);
        if (playbacks.Length == 0)
        {
            EditorUtility.DisplayDialog("Move Label",
                "No SkeletonPlayback in the open scene. Open the 'badminton' scene first.", "OK");
            return;
        }
        int added = 0;
        foreach (var p in playbacks)
        {
            if (p.GetComponent<MoveLabelHUD>() != null) continue;
            Undo.AddComponent<MoveLabelHUD>(p.gameObject);
            EditorUtility.SetDirty(p.gameObject);
            added++;
        }
        EditorSceneManager.MarkSceneDirty(playbacks[0].gameObject.scene);
        Debug.Log($"[MoveLabel] added to {added} twin(s). Play mode: banner top-center, " +
                  "timeline bottom. M toggles. Clips without a moves block show nothing.");
    }

    [MenuItem("Tools/Badminton/Move Label/Remove")]
    public static void Remove()
    {
        var huds = Object.FindObjectsByType<MoveLabelHUD>(
            FindObjectsInactive.Include, FindObjectsSortMode.None);
        foreach (var h in huds)
        {
            EditorSceneManager.MarkSceneDirty(h.gameObject.scene);
            Undo.DestroyObjectImmediate(h);
        }
        Debug.Log($"[MoveLabel] removed {huds.Length} move-label HUD(s).");
    }
}
```

- [ ] **Step 3: Validate + console check**

Validate both new files (unity-mcp `Unity_ValidateScript`, standard): 0 errors each. Console (`Unity_GetConsoleLogs`): 0 errors after recompile.

- [ ] **Step 4: Commit**

```bash
git add Assets/Scripts/SkeletonPlayer/MoveLabelHUD.cs Assets/Editor/MoveLabelSetup.cs
git commit -m "Unity: MoveLabelHUD subtitle track + Tools menu"
```

---

### Task 8: Acceptance run + docs

**Files:**
- Modify: `docs/PROGRESS.md` (append dated entry)
- Modify: `tools/README.md` if it lists tools (add one line for `label_moves.py`)

- [ ] **Step 1: Acceptance per spec §5** — with Unity open: `Tools ▸ Badminton ▸ Move Label ▸ Add To Twin`, press Play on test_3, then V (video compare) to eyeball: does the banner read plausibly against the video? Check test_5 too. Record observed stroke counts per clip (from Task 4 reports). The user is the judge for "timeline reads correctly"; smash↔clear / drop↔net confusion is acceptable by spec.

- [ ] **Step 2: Append to `docs/PROGRESS.md`** — dated entry: what landed (labeler, schema 1.1, HUD), the per-clip stroke counts + any threshold tuning done, known confusions observed, pointer to the spec, and "Approach B (trained classifier) is the designed upgrade — same contract".

- [ ] **Step 3: Final commit + push branch**

```bash
tools/.venv/Scripts/python -m pytest tools/tests -q   # green
git add docs/PROGRESS.md tools/README.md
git commit -m "docs: move recognition A landed (labeler + HUD + labeled clips)"
git push origin spec/move-recognition
```

PR #1 now carries spec + implementation. The USER merges it (do not merge for them).

---

## Self-Review (done at plan time)

- **Spec coverage:** contract §1 → Tasks 4+6; tool §2 → Tasks 1–5 (report/overlay/write all present); Unity §3 → Tasks 6–7; §4 Approach B is explicitly out of this plan (separate round per spec); acceptance §5 → Task 8 + duration bound asserted in Task 2 tests. Low-confidence handling (§2) → NaN speeds in Task 1 (peaks can't form on NaN) and NaN-tolerant window growth in Task 2.
- **Placeholder scan:** none — every code step carries the code.
- **Type consistency:** `moves` JSON keys `start/peak/end/label/confidence` identical in Task 4 (writer), Task 6 (C# fields), Task 7 (reader). `build_moves`/`write_moves`/`MoveAt` names match everywhere. `label_moves` synthetic-test helpers (`make_doc`, `add_swing`, `set_joint`, `assert_tiles`, `make_stroke_doc`) are defined in the earliest task that uses them and reused by name afterward.
