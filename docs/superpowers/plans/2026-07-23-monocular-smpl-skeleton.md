# Monocular SMPL Skeleton → Unity Twin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn a monocular RGB clip of one person moving into a SMPL-24 skeleton with a real spine, land it in Unity as a moving twin, and measure its accuracy against SMPL ground truth.

**Architecture:** WHAM runs on Colab (GPU) and emits per-frame SMPL joints+params as a normalized `.npz`. A pure-Python, GPU-free converter (`smpl_to_skeleton.py`) turns that into `skeleton.json v2` — a superset of v1 carrying the SMPL-24 tree (`parents`, spine chain, `betas`, `smpl` params). Unity's `SmplSkeletonDriver` renders it as a procedural 24-joint twin. `eval_pose.py` computes MPJPE / PA-MPJPE. The v2 schema is producer-agnostic, so a future multi-view triangulation step writes the same file with no downstream change.

**Tech Stack:** Python 3.12 (`tools/.venv`), numpy, pytest (local, GPU-free); WHAM + smplx + torch (Colab only); Unity 6000.1.4f1 URP, C#, JsonUtility.

## Global Constraints

- **Python env:** run everything via `tools/.venv/Scripts/python.exe`. New local tools use **numpy only** (already installed). Do **not** add WHAM/smplx/torch-cuda to `tools/requirements.txt` — they live on Colab.
- **Coordinate conversion happens in Python, never Unity** — the single point is `apply_transform()` / `WORLD_TO_UNITY` in `smpl_to_skeleton.py`.
- **skeleton.json v2 is a superset of v1.** Unity-facing payload stays a **flat float array** (`joints_flat`) so `JsonUtility` parses with no extra packages. Extra blocks (`smpl`, `betas`) are optional and ignored by Unity.
- **SMPL-24 joint order (fixed contract), index order:** `pelvis, left_hip, right_hip, spine1, left_knee, right_knee, spine2, left_ankle, right_ankle, spine3, left_foot, right_foot, neck, left_collar, right_collar, head, left_shoulder, right_shoulder, left_elbow, right_elbow, left_wrist, right_wrist, left_hand, right_hand`.
- **SMPL-24 parents (fixed):** `[-1,0,0,0,1,2,3,4,5,6,7,8,9,9,9,12,13,14,16,17,18,19,20,21]`.
- **Unity runtime helper objects live at scene root / under the driver's own object;** `Clear()` destroys children on clip load. Do not park twin objects under an object that gets cleared unexpectedly.
- **Privacy:** never commit frame-bearing images/video. All tests use **synthetic** data or public datasets; never commit a real clip or a `.wham.npz` derived from an identifiable person.
- **Commits are local only and never pushed.** Frequent local commits per task are expected; pushing/PRs are user-gated.
- **SMPL model files** (`SMPL_NEUTRAL.pkl`) require a free account at `smpl.is.tue.mpg.de`. The user registers and provides the file; no task automates account creation.

---

### Task 1: v2 schema core — constants, transform, document builder, synthetic generator

**Files:**
- Create: `tools/smpl_to_skeleton.py`
- Create: `tools/tests/conftest.py`
- Test: `tools/tests/test_smpl_to_skeleton.py`

**Interfaces:**
- Produces:
  - `SMPL_JOINT_NAMES: list[str]` (24), `SMPL_PARENTS: list[int]` (24), `NUM_SMPL_JOINTS = 24`, `STRIDE = 4`, `SCHEMA_VERSION = "2.0"`, `WORLD_TO_UNITY: np.ndarray (3,3)`
  - `apply_transform(xyz, transform=WORLD_TO_UNITY) -> np.ndarray` — matrix on last axis of `(...,3)`
  - `build_v2_document(video_id, joints3d, fps, *, pose=None, betas=None, transl=None, confidences=None, resolution=None, rotate=0, extractor_pose="wham", transform=WORLD_TO_UNITY) -> dict` — `joints3d` is `(T,24,3)`
  - `make_synthetic(video_id="demo", fps=30.0, frames=12) -> dict` — a T-pose translating along +X
  - `write_skeleton_json(doc, out_path) -> None`

- [ ] **Step 1: Create the test import shim**

Create `tools/tests/conftest.py`:

```python
import pathlib
import sys

# Make tools/*.py importable as top-level modules from tools/tests/*.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
```

- [ ] **Step 2: Write failing tests for constants + transform + builder + synthetic**

Create `tools/tests/test_smpl_to_skeleton.py`:

```python
import numpy as np
import pytest

import smpl_to_skeleton as s2s


def test_constants_are_consistent():
    assert s2s.NUM_SMPL_JOINTS == 24
    assert len(s2s.SMPL_JOINT_NAMES) == 24
    assert len(s2s.SMPL_PARENTS) == 24
    assert s2s.SMPL_PARENTS[0] == -1
    # every non-root parent is a valid earlier joint index (a well-formed tree)
    for j, p in enumerate(s2s.SMPL_PARENTS[1:], start=1):
        assert 0 <= p < j
    # spine chain is present and correctly linked
    n = s2s.SMPL_JOINT_NAMES
    assert n[3] == "spine1" and s2s.SMPL_PARENTS[3] == 0
    assert n[6] == "spine2" and s2s.SMPL_PARENTS[6] == 3
    assert n[9] == "spine3" and s2s.SMPL_PARENTS[9] == 6
    assert n[12] == "neck" and s2s.SMPL_PARENTS[12] == 9
    assert n[15] == "head" and s2s.SMPL_PARENTS[15] == 12


def test_apply_transform_flips_z_by_default():
    pts = np.array([[1.0, 2.0, 3.0]])
    out = s2s.apply_transform(pts)
    np.testing.assert_allclose(out, [[1.0, 2.0, -3.0]])


def test_apply_transform_rejects_bad_shape():
    with pytest.raises(ValueError):
        s2s.apply_transform(np.zeros((4, 2)))


def test_build_v2_document_shape_and_schema():
    T = 5
    joints = np.random.RandomState(0).rand(T, 24, 3)
    doc = s2s.build_v2_document("clipA", joints, fps=30.0)
    assert doc["schema_version"] == "2.0"
    assert doc["skeleton"] == "smpl-24"
    assert doc["coordinate_system"] == "unity"
    assert doc["joint_names"] == s2s.SMPL_JOINT_NAMES
    assert doc["parents"] == s2s.SMPL_PARENTS
    assert len(doc["frames"]) == T
    f0 = doc["frames"][0]
    assert len(f0["joints_flat"]) == 24 * 4       # flat 24 x [x,y,z,conf]
    assert len(f0["root_world"]) == 3
    assert f0["root_court_xz"] is None
    # default confidence is 1.0
    assert f0["joints_flat"][3] == 1.0


def test_build_v2_document_applies_transform_to_joints():
    joints = np.zeros((1, 24, 3))
    joints[0, 0] = [1.0, 2.0, 3.0]               # pelvis
    doc = s2s.build_v2_document("clipB", joints, fps=30.0)
    fl = doc["frames"][0]["joints_flat"]
    assert fl[0:3] == [1.0, 2.0, -3.0]           # z flipped
    assert doc["frames"][0]["root_world"] == [1.0, 2.0, -3.0]


def test_build_v2_document_includes_smpl_block_when_pose_given():
    T = 2
    joints = np.zeros((T, 24, 3))
    pose = np.random.RandomState(1).rand(T, 72)
    betas = np.random.RandomState(2).rand(10)
    transl = np.random.RandomState(3).rand(T, 3)
    doc = s2s.build_v2_document("clipC", joints, fps=30.0, pose=pose, betas=betas, transl=transl)
    assert len(doc["betas"]) == 10
    smpl = doc["frames"][0]["smpl"]
    assert len(smpl["global_orient"]) == 3
    assert len(smpl["body_pose"]) == 69
    assert len(smpl["transl"]) == 3


def test_make_synthetic_is_wellformed_and_travels():
    doc = s2s.make_synthetic(frames=10)
    assert len(doc["frames"]) == 10
    assert len(doc["frames"][0]["joints_flat"]) == 24 * 4
    # pelvis x increases over time (the twin travels along +X)
    x0 = doc["frames"][0]["joints_flat"][0]
    x9 = doc["frames"][9]["joints_flat"][0]
    assert x9 > x0
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
cd "<repo>" && ./tools/.venv/Scripts/python.exe -m pytest tools/tests/test_smpl_to_skeleton.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'smpl_to_skeleton'`.

- [ ] **Step 4: Implement `tools/smpl_to_skeleton.py`**

```python
"""video-to-twin: convert monocular WHAM SMPL output -> skeleton.json v2.

Pure/offline (no GPU, no SMPL model): consumes per-frame SMPL joints + params
produced on Colab (tools/colab/wham_extract.ipynb) and emits skeleton.json v2 —
a superset of v1 that carries the SMPL-24 tree with a real spine.
See docs/superpowers/specs/2026-07-23-monocular-smpl-skeleton-design.md.
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np

SCHEMA_VERSION = "2.0"
NUM_SMPL_JOINTS = 24
STRIDE = 4  # x, y, z, confidence

SMPL_JOINT_NAMES = [
    "pelvis", "left_hip", "right_hip", "spine1", "left_knee", "right_knee",
    "spine2", "left_ankle", "right_ankle", "spine3", "left_foot", "right_foot",
    "neck", "left_collar", "right_collar", "head", "left_shoulder",
    "right_shoulder", "left_elbow", "right_elbow", "left_wrist", "right_wrist",
    "left_hand", "right_hand",
]
SMPL_PARENTS = [-1, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9, 9, 12, 13, 14,
                16, 17, 18, 19, 20, 21]

# WHAM world frame -> Unity frame (Y-up, left-handed). WHAM is right-handed;
# flipping Z converts handedness. VERIFY visually in Unity (Task 5); adjust this
# matrix if the twin comes out mirrored or upside-down.
WORLD_TO_UNITY = np.array([[1.0, 0.0, 0.0],
                           [0.0, 1.0, 0.0],
                           [0.0, 0.0, -1.0]])

# Approximate SMPL rest pose (Y-up meters), a T-pose. Used only by make_synthetic
# so Unity + eval can be exercised with no GPU. Index-aligned to SMPL_JOINT_NAMES.
_REST = np.array([
    [0.00, 0.95, 0.00], [0.08, 0.90, 0.00], [-0.08, 0.90, 0.00], [0.00, 1.05, 0.00],
    [0.09, 0.50, 0.00], [-0.09, 0.50, 0.00], [0.00, 1.15, 0.00], [0.09, 0.08, 0.00],
    [-0.09, 0.08, 0.00], [0.00, 1.25, 0.00], [0.09, 0.02, 0.12], [-0.09, 0.02, 0.12],
    [0.00, 1.45, 0.00], [0.06, 1.38, 0.00], [-0.06, 1.38, 0.00], [0.00, 1.60, 0.00],
    [0.18, 1.40, 0.00], [-0.18, 1.40, 0.00], [0.42, 1.40, 0.00], [-0.42, 1.40, 0.00],
    [0.65, 1.40, 0.00], [-0.65, 1.40, 0.00], [0.72, 1.40, 0.00], [-0.72, 1.40, 0.00],
])


def apply_transform(xyz, transform=WORLD_TO_UNITY):
    """Apply a 3x3 frame transform to the last axis of an (...,3) array."""
    a = np.asarray(xyz, dtype=np.float64)
    if a.shape[-1] != 3:
        raise ValueError(f"expected last axis == 3, got shape {a.shape}")
    return a @ np.asarray(transform, dtype=np.float64).T


def build_v2_document(video_id, joints3d, fps, *, pose=None, betas=None,
                      transl=None, confidences=None, resolution=None, rotate=0,
                      extractor_pose="wham", transform=WORLD_TO_UNITY):
    """Assemble a skeleton.json v2 dict from SMPL joints (+ optional params).

    joints3d: (T,24,3) SMPL joints in WHAM world frame, meters.
    pose:     (T,72) axis-angle (global_orient[:3] + body_pose[3:72]) or None.
    betas:    (10,) or None. transl: (T,3) or None. confidences: (T,24) or None.
    """
    joints3d = np.asarray(joints3d, dtype=np.float64)
    if joints3d.ndim != 3 or joints3d.shape[1:] != (NUM_SMPL_JOINTS, 3):
        raise ValueError(f"joints3d must be (T,{NUM_SMPL_JOINTS},3), got {joints3d.shape}")
    T = joints3d.shape[0]

    joints_u = apply_transform(joints3d, transform)

    if confidences is None:
        conf = np.ones((T, NUM_SMPL_JOINTS))
    else:
        conf = np.asarray(confidences, dtype=np.float64)
        if conf.shape != (T, NUM_SMPL_JOINTS):
            raise ValueError(f"confidences must be (T,{NUM_SMPL_JOINTS}), got {conf.shape}")

    transl_u = apply_transform(np.asarray(transl, dtype=np.float64), transform) if transl is not None else None
    pose_arr = np.asarray(pose, dtype=np.float64) if pose is not None else None

    frames = []
    for t in range(T):
        flat = []
        for j in range(NUM_SMPL_JOINTS):
            flat.extend([round(float(joints_u[t, j, 0]), 5),
                         round(float(joints_u[t, j, 1]), 5),
                         round(float(joints_u[t, j, 2]), 5),
                         round(float(conf[t, j]), 3)])
        frame = {
            "frame_id": t,
            "time": round(t / float(fps), 4),
            "joints_flat": flat,
            "root_world": [round(float(joints_u[t, 0, 0]), 5),
                           round(float(joints_u[t, 0, 1]), 5),
                           round(float(joints_u[t, 0, 2]), 5)],
            "root_court_xz": None,
        }
        if pose_arr is not None:
            frame["smpl"] = {
                "global_orient": [round(float(v), 6) for v in pose_arr[t, :3]],
                "body_pose": [round(float(v), 6) for v in pose_arr[t, 3:72]],
                "transl": ([round(float(v), 6) for v in transl_u[t]]
                           if transl_u is not None else [0.0, 0.0, 0.0]),
            }
        frames.append(frame)

    return {
        "schema_version": SCHEMA_VERSION,
        "video_id": video_id,
        "source": {"type": "monocular_rgb", "fps": round(float(fps), 3),
                   "resolution": list(resolution) if resolution else None,
                   "rotate": rotate},
        "extractor": {"pose": extractor_pose,
                      "notes": "world-grounded SMPL, converted to Unity frame"},
        "coordinate_system": "unity",
        "skeleton": "smpl-24",
        "joint_names": list(SMPL_JOINT_NAMES),
        "parents": list(SMPL_PARENTS),
        "betas": ([round(float(v), 6) for v in np.asarray(betas, dtype=np.float64).ravel()[:10]]
                  if betas is not None else None),
        "frames": frames,
    }


def make_synthetic(video_id="demo", fps=30.0, frames=12):
    """A GPU-free T-pose translating along +X — exercises Unity + eval offline."""
    joints = np.empty((frames, NUM_SMPL_JOINTS, 3))
    for t in range(frames):
        joints[t] = _REST + np.array([0.1 * t, 0.0, 0.0])
    return build_v2_document(video_id, joints, fps=fps, extractor_pose="synthetic")


def write_skeleton_json(doc, out_path):
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd "<repo>" && ./tools/.venv/Scripts/python.exe -m pytest tools/tests/test_smpl_to_skeleton.py -v
```
Expected: PASS (7 tests).

- [ ] **Step 6: Commit (local)**

```bash
cd "<repo>" && git add tools/smpl_to_skeleton.py tools/tests/conftest.py tools/tests/test_smpl_to_skeleton.py && git commit -m "feat(pose): skeleton.json v2 SMPL-24 builder + synthetic generator"
```

---

### Task 2: WHAM-output loader + CLI

**Files:**
- Modify: `tools/smpl_to_skeleton.py` (add `load_wham_output` + `main`/argparse at end)
- Test: `tools/tests/test_smpl_to_skeleton.py` (add cases)

**Interfaces:**
- Consumes: everything from Task 1.
- Produces:
  - `load_wham_output(path) -> dict` with keys `joints3d (T,24,3)`, `pose (T,72)|None`, `betas (10,)|None`, `transl (T,3)|None`, `fps (float)`
  - CLI: `python tools/smpl_to_skeleton.py --synthetic --out P` and `... --wham-output NPZ --video-id ID --out P [--fps F]`

- [ ] **Step 1: Write failing tests for the loader + CLI round-trip**

Append to `tools/tests/test_smpl_to_skeleton.py`:

```python
import json
import subprocess
import sys


def test_load_wham_output_normalizes_npz(tmp_path):
    npz = tmp_path / "clip.wham.npz"
    T = 4
    np.savez(npz,
             joints3d=np.random.RandomState(0).rand(T, 24, 3),
             pose=np.random.RandomState(1).rand(T, 72),
             betas=np.random.RandomState(2).rand(10),
             transl=np.random.RandomState(3).rand(T, 3),
             fps=np.array(30.0))
    data = s2s.load_wham_output(str(npz))
    assert data["joints3d"].shape == (T, 24, 3)
    assert data["pose"].shape == (T, 72)
    assert data["betas"].shape == (10,)
    assert data["transl"].shape == (T, 3)
    assert float(data["fps"]) == 30.0


def test_load_wham_output_requires_joints(tmp_path):
    npz = tmp_path / "bad.wham.npz"
    np.savez(npz, pose=np.zeros((3, 72)))
    with pytest.raises((KeyError, ValueError)):
        s2s.load_wham_output(str(npz))


def test_cli_synthetic_writes_valid_v2(tmp_path):
    out = tmp_path / "demo.skeleton.json"
    subprocess.run(
        [sys.executable, "tools/smpl_to_skeleton.py", "--synthetic",
         "--frames", "6", "--out", str(out)],
        check=True, cwd=".")
    doc = json.loads(out.read_text())
    assert doc["schema_version"] == "2.0"
    assert len(doc["frames"]) == 6
    assert len(doc["joint_names"]) == 24
```

- [ ] **Step 2: Run to verify the new tests fail**

```bash
cd "<repo>" && ./tools/.venv/Scripts/python.exe -m pytest tools/tests/test_smpl_to_skeleton.py -k "wham or cli" -v
```
Expected: FAIL — `AttributeError: module 'smpl_to_skeleton' has no attribute 'load_wham_output'` and CLI failure.

- [ ] **Step 3: Add the loader + CLI to `tools/smpl_to_skeleton.py`**

Add before the end of the file:

```python
def load_wham_output(path):
    """Load the normalized .npz written by tools/colab/wham_extract.ipynb.

    Required key: joints3d (T,24,3). Optional: pose (T,72), betas (10,),
    transl (T,3), fps (scalar).
    """
    with np.load(path, allow_pickle=False) as z:
        if "joints3d" not in z:
            raise KeyError("wham .npz is missing required key 'joints3d'")
        joints3d = np.asarray(z["joints3d"], dtype=np.float64)
        if joints3d.ndim != 3 or joints3d.shape[1:] != (NUM_SMPL_JOINTS, 3):
            raise ValueError(f"joints3d must be (T,24,3), got {joints3d.shape}")
        return {
            "joints3d": joints3d,
            "pose": np.asarray(z["pose"], dtype=np.float64) if "pose" in z else None,
            "betas": np.asarray(z["betas"], dtype=np.float64) if "betas" in z else None,
            "transl": np.asarray(z["transl"], dtype=np.float64) if "transl" in z else None,
            "fps": float(z["fps"]) if "fps" in z else 30.0,
        }


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build skeleton.json v2 from WHAM SMPL output.")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--wham-output", help="normalized .npz from wham_extract.ipynb")
    src.add_argument("--synthetic", action="store_true", help="emit a GPU-free demo clip")
    ap.add_argument("--video-id", default="demo")
    ap.add_argument("--fps", type=float, default=None)
    ap.add_argument("--frames", type=int, default=12, help="synthetic only")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    if args.synthetic:
        doc = make_synthetic(video_id=args.video_id, fps=args.fps or 30.0, frames=args.frames)
    else:
        d = load_wham_output(args.wham_output)
        doc = build_v2_document(args.video_id, d["joints3d"], fps=args.fps or d["fps"],
                                pose=d["pose"], betas=d["betas"], transl=d["transl"])
    write_skeleton_json(doc, args.out)
    print(f"wrote {args.out}: {len(doc['frames'])} frames, {len(doc['joint_names'])} joints")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify all tests pass**

```bash
cd "<repo>" && ./tools/.venv/Scripts/python.exe -m pytest tools/tests/test_smpl_to_skeleton.py -v
```
Expected: PASS (10 tests).

- [ ] **Step 5: Commit (local)**

```bash
cd "<repo>" && git add tools/smpl_to_skeleton.py tools/tests/test_smpl_to_skeleton.py && git commit -m "feat(pose): WHAM .npz loader + CLI for skeleton.json v2"
```

---

### Task 3: Accuracy harness — MPJPE / PA-MPJPE

**Files:**
- Create: `tools/eval_pose.py`
- Test: `tools/tests/test_eval_pose.py`

**Interfaces:**
- Consumes: `smpl_to_skeleton.make_synthetic` (test fixture).
- Produces:
  - `load_skeleton_joints(path) -> (np.ndarray (T,J,3), list[str])`
  - `match_joints(pred_names, gt_names) -> (np.ndarray, np.ndarray)`
  - `mpjpe(pred, gt) -> float`, `per_joint_error(pred, gt) -> np.ndarray (J,)`
  - `procrustes_align(pred, gt) -> np.ndarray`, `pa_mpjpe(pred, gt) -> float`

- [ ] **Step 1: Write failing tests**

Create `tools/tests/test_eval_pose.py`:

```python
import json

import numpy as np
import pytest

import eval_pose as ep
import smpl_to_skeleton as s2s


def test_load_skeleton_joints_from_synthetic(tmp_path):
    doc = s2s.make_synthetic(frames=5)
    p = tmp_path / "demo.skeleton.json"
    p.write_text(json.dumps(doc))
    joints, names = ep.load_skeleton_joints(str(p))
    assert joints.shape == (5, 24, 3)
    assert names == s2s.SMPL_JOINT_NAMES
    # first three floats of joints_flat == the joint's xyz
    assert np.allclose(joints[0, 0], doc["frames"][0]["joints_flat"][0:3])


def test_mpjpe_zero_for_identical():
    x = np.random.RandomState(0).rand(3, 24, 3)
    assert ep.mpjpe(x, x) == pytest.approx(0.0)


def test_match_joints_returns_common_indices():
    pred = ["pelvis", "neck", "head"]
    gt = ["head", "pelvis"]
    pi, gi = ep.match_joints(pred, gt)
    assert list(pred[i] for i in pi) == list(gt[i] for i in gi)
    assert set(pred[i] for i in pi) == {"pelvis", "head"}


def test_pa_mpjpe_invariant_to_similarity_transform():
    rng = np.random.RandomState(42)
    gt = rng.rand(4, 24, 3)
    # a random rotation, scale, translation applied to gt -> pred
    a = 0.7
    R = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    s, t = 2.5, np.array([3.0, -1.0, 0.5])
    pred = (s * (gt @ R.T)) + t
    assert ep.mpjpe(pred, gt) > 0.1                 # raw error is large
    assert ep.pa_mpjpe(pred, gt) == pytest.approx(0.0, abs=1e-6)  # alignment removes it
```

- [ ] **Step 2: Run to verify failure**

```bash
cd "<repo>" && ./tools/.venv/Scripts/python.exe -m pytest tools/tests/test_eval_pose.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'eval_pose'`.

- [ ] **Step 3: Implement `tools/eval_pose.py`**

```python
"""Accuracy harness for skeleton.json v2: MPJPE and PA-MPJPE vs ground truth.

GT source is another v2 skeleton.json, OR an .npz with keys
joints3d (T,J,3) and joint_names. Errors are reported in millimeters
(inputs are assumed meters). Badminton-free — works on any SMPL GT dataset
(EMDB, 3DPW).
"""
from __future__ import annotations

import argparse
import json

import numpy as np

import smpl_to_skeleton as s2s


def load_skeleton_joints(path):
    """Load a v2 skeleton.json -> (joints (T,J,3), names)."""
    with open(path, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    names = list(doc["joint_names"])
    frames = doc["frames"]
    T, J = len(frames), len(names)
    arr = np.zeros((T, J, 3), dtype=np.float64)
    for t, f in enumerate(frames):
        flat = f["joints_flat"]
        for j in range(J):
            b = j * s2s.STRIDE
            arr[t, j] = flat[b:b + 3]
    return arr, names


def load_gt(path):
    """Load GT as (joints (T,J,3), names) from a v2 json or an .npz."""
    if path.endswith(".npz"):
        with np.load(path, allow_pickle=True) as z:
            joints = np.asarray(z["joints3d"], dtype=np.float64)
            names = [str(n) for n in z["joint_names"]] if "joint_names" in z else s2s.SMPL_JOINT_NAMES
        return joints, names
    return load_skeleton_joints(path)


def match_joints(pred_names, gt_names):
    """Indices (pred_idx, gt_idx) of joints present in both, in pred order."""
    gt_index = {n: i for i, n in enumerate(gt_names)}
    pi, gi = [], []
    for i, n in enumerate(pred_names):
        if n in gt_index:
            pi.append(i)
            gi.append(gt_index[n])
    return np.array(pi, dtype=int), np.array(gi, dtype=int)


def per_joint_error(pred, gt):
    """Mean-over-time Euclidean error per joint, shape (J,). Same units as input."""
    return np.linalg.norm(pred - gt, axis=-1).mean(axis=0)


def mpjpe(pred, gt):
    """Mean per-joint position error over all frames/joints."""
    return float(np.linalg.norm(pred - gt, axis=-1).mean())


def _similarity_align(X, Y):
    """Umeyama: best sR·X + t fitting X onto Y (both (J,3))."""
    muX, muY = X.mean(0), Y.mean(0)
    X0, Y0 = X - muX, Y - muY
    U, S, Vt = np.linalg.svd(Y0.T @ X0)
    d = np.sign(np.linalg.det(U @ Vt))
    D = np.diag([1.0, 1.0, d])
    R = U @ D @ Vt
    varX = (X0 ** 2).sum()
    s = float((S * np.array([1.0, 1.0, d])).sum() / varX) if varX > 0 else 1.0
    t = muY - s * (R @ muX)
    return (s * (R @ X.T)).T + t


def procrustes_align(pred, gt):
    """Per-frame similarity-align pred onto gt. pred,gt: (T,J,3)."""
    out = np.empty_like(pred)
    for t in range(pred.shape[0]):
        out[t] = _similarity_align(pred[t], gt[t])
    return out


def pa_mpjpe(pred, gt):
    """MPJPE after per-frame Procrustes alignment."""
    return mpjpe(procrustes_align(pred, gt), gt)


def main(argv=None):
    ap = argparse.ArgumentParser(description="MPJPE / PA-MPJPE for skeleton.json v2.")
    ap.add_argument("--pred", required=True, help="skeleton.json v2")
    ap.add_argument("--gt", required=True, help="v2 json OR .npz (joints3d + joint_names)")
    ap.add_argument("--per-joint", action="store_true")
    args = ap.parse_args(argv)

    pred, pnames = load_skeleton_joints(args.pred)
    gt, gnames = load_gt(args.gt)
    pi, gi = match_joints(pnames, gnames)
    if len(pi) == 0:
        raise SystemExit("no shared joints between pred and gt")
    T = min(pred.shape[0], gt.shape[0])
    p, g = pred[:T][:, pi], gt[:T][:, gi]

    print(f"frames={T} shared_joints={len(pi)}")
    print(f"MPJPE    = {mpjpe(p, g) * 1000:.1f} mm")
    print(f"PA-MPJPE = {pa_mpjpe(p, g) * 1000:.1f} mm")
    if args.per_joint:
        pj = per_joint_error(p, g) * 1000
        for name_i, err in zip((pnames[i] for i in pi), pj):
            print(f"  {name_i:<16} {err:6.1f} mm")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify pass**

```bash
cd "<repo>" && ./tools/.venv/Scripts/python.exe -m pytest tools/tests/test_eval_pose.py -v
```
Expected: PASS (4 tests).

- [ ] **Step 5: Commit (local)**

```bash
cd "<repo>" && git add tools/eval_pose.py tools/tests/test_eval_pose.py && git commit -m "feat(pose): MPJPE/PA-MPJPE accuracy harness for skeleton.json v2"
```

---

### Task 4: WHAM Colab notebook (produces the .npz)

**Files:**
- Create: `tools/colab/wham_extract.ipynb`
- Create: `tools/colab/README.md`

**Interfaces:**
- Produces: `<video_id>.wham.npz` with keys `joints3d (T,24,3)`, `pose (T,72)`, `betas (10,)`, `transl (T,3)`, `fps` — the exact contract `load_wham_output` (Task 2) consumes.

> This task needs a Colab GPU and cannot be unit-tested locally. Verification is a manual smoke test with explicit expected shapes.

- [ ] **Step 1: Write `tools/colab/README.md`**

```markdown
# WHAM → skeleton.json v2 (Colab)

Runs WHAM (world-grounded SMPL) on one monocular clip and writes a normalized
`<video_id>.wham.npz` that `tools/smpl_to_skeleton.py --wham-output` turns into
`skeleton.json v2`. This laptop has no NVIDIA GPU, so inference runs on Colab.

## One-time
1. Register at https://smpl.is.tue.mpg.de and download the **neutral SMPL** model
   (`SMPL_NEUTRAL.pkl`). Upload it to the Colab session (or your Drive).
2. Open `wham_extract.ipynb` in Colab, set Runtime → GPU.

## Run
1. Upload a clip (e.g. a Pexels clip renamed `test_N.mp4`), set `VIDEO_ID`.
2. Run all cells → downloads `test_N.wham.npz`.
3. Locally: `./tools/.venv/Scripts/python.exe tools/smpl_to_skeleton.py --wham-output test_N.wham.npz --video-id test_N --out data/skeleton/test_N.skeleton.json`

## Output contract (what the npz must contain)
- `joints3d` (T,24,3) — SMPL joints, world meters
- `pose` (T,72), `betas` (10,), `transl` (T,3), `fps` (scalar)
```

- [ ] **Step 2: Author `tools/colab/wham_extract.ipynb` with these cells**

Create the notebook (valid `.ipynb` JSON) with the following cells in order.

Cell 1 (markdown): title + link back to this plan and the spec.

Cell 2 (code) — install WHAM + deps:
```python
!git clone https://github.com/yohanshin/WHAM.git
%cd WHAM
!bash install.sh          # WHAM's own setup (torch, deps, checkpoints)
!pip install smplx
```

Cell 3 (code) — place the SMPL model where WHAM/smplx expect it:
```python
from google.colab import files
print("Upload SMPL_NEUTRAL.pkl (from smpl.is.tue.mpg.de)")
up = files.upload()
import os, shutil
os.makedirs("body_models/smpl", exist_ok=True)
shutil.copy(next(iter(up)), "body_models/smpl/SMPL_NEUTRAL.pkl")
```

Cell 4 (code) — upload the clip and run WHAM's demo:
```python
VIDEO_ID = "test_N"
up = files.upload()                     # the .mp4
clip = next(iter(up))
!python demo.py --video "{clip}" --output_pth output/{VIDEO_ID} --save_pkl --visualize
```

Cell 5 (code) — normalize WHAM output → 24 SMPL joints via smplx, save npz:
```python
import numpy as np, torch, joblib, glob, smplx

res = joblib.load(sorted(glob.glob(f"output/{VIDEO_ID}/*.pkl"))[0])
track = res[sorted(res.keys())[0]]     # first tracked person

# WHAM stores world-grounded params when available.
pose  = np.asarray(track.get("pose_world", track["pose"]), dtype=np.float32)   # (T,72)
transl = np.asarray(track.get("trans_world", track["trans"]), dtype=np.float32) # (T,3)
betas = np.asarray(track["betas"], dtype=np.float32)
if betas.ndim == 2:
    betas = betas.mean(0)              # (10,)

body = smplx.create("body_models", model_type="smpl", gender="neutral", batch_size=pose.shape[0])
out = body(global_orient=torch.tensor(pose[:, :3]),
           body_pose=torch.tensor(pose[:, 3:72]),
           betas=torch.tensor(betas[None].repeat(pose.shape[0], 0)),
           transl=torch.tensor(transl))
joints3d = out.joints.detach().cpu().numpy()[:, :24, :]   # (T,24,3)

# fps from the source video
import cv2
fps = cv2.VideoCapture(clip).get(cv2.CAP_PROP_FPS) or 30.0

np.savez(f"{VIDEO_ID}.wham.npz", joints3d=joints3d, pose=pose,
         betas=betas, transl=transl, fps=np.array(fps))
print("shapes:", joints3d.shape, pose.shape, betas.shape, transl.shape, "fps", fps)
files.download(f"{VIDEO_ID}.wham.npz")
```

- [ ] **Step 3: Manual smoke test (Colab)**

Run all cells on a short (2–5 s) Pexels clip. Expected: Cell 5 prints `shapes: (T, 24, 3) (T, 72) (10,) (T, 3) fps 30.0` (T ≈ frames), and downloads `test_N.wham.npz`.

- [ ] **Step 4: Verify the npz feeds the converter (local, no GPU)**

```bash
cd "<repo>" && ./tools/.venv/Scripts/python.exe tools/smpl_to_skeleton.py --wham-output /path/to/test_N.wham.npz --video-id test_N --out data/skeleton/test_N.skeleton.json
```
Expected: `wrote data/skeleton/... : <T> frames, 24 joints`.

- [ ] **Step 5: Commit (local, notebook + README only — never the clip or npz)**

```bash
cd "<repo>" && git add tools/colab/wham_extract.ipynb tools/colab/README.md && git commit -m "feat(pose): WHAM Colab notebook -> normalized SMPL .npz"
```

---

### Task 5: Unity procedural SMPL-tree twin

**Files:**
- Create: `Assets/Scripts/SkeletonPlayer/SmplSkeletonData.cs`
- Create: `Assets/Scripts/SkeletonPlayer/SmplSkeletonDriver.cs`
- Asset: `Assets/StreamingAssets/skeleton/demo.skeleton.json` (generated, not hand-written)

**Interfaces:**
- Consumes: `skeleton.json v2` (Task 1/2 schema): `joint_names[24]`, `parents[24]`, `frames[].joints_flat[96]`.
- Produces: a scene-root twin GameObject with 24 joint spheres + 23 bone capsules including the spine chain.

> Unity has no local automated test runner in this setup (MCP bridge is flaky; user runs the editor). Verification is a `[ContextMenu]` self-check (no Play mode) plus a manual Play-mode check.

- [ ] **Step 1: Generate the demo JSON into StreamingAssets**

```bash
cd "<repo>" && ./tools/.venv/Scripts/python.exe tools/smpl_to_skeleton.py --synthetic --frames 60 --video-id demo --out Assets/StreamingAssets/skeleton/demo.skeleton.json && echo OK
```
Expected: `wrote Assets/StreamingAssets/skeleton/demo.skeleton.json: 60 frames, 24 joints`.

- [ ] **Step 2: Create `SmplSkeletonData.cs`**

```csharp
using System;
using System.IO;
using UnityEngine;

namespace BadmintonVR.SkeletonPlayer
{
    // Mirrors skeleton.json v2 (SMPL-24). JsonUtility ignores fields we don't
    // declare (betas, per-frame smpl block). Joints are a flat float array
    // (96 = 24 x 4). Bone connectivity comes from `parents`, not a hard-coded table.
    [Serializable]
    public class SmplSource { public string type; public float fps; }

    [Serializable]
    public class SmplFrame
    {
        public int frame_id;
        public float time;
        public float[] joints_flat;   // 24 * [x, y, z, confidence]
        public float[] root_world;    // [x, y, z]
    }

    [Serializable]
    public class SmplSkeletonDoc
    {
        public string schema_version;
        public string video_id;
        public SmplSource source;
        public string skeleton;       // "smpl-24"
        public string[] joint_names;  // 24
        public int[] parents;         // 24, parent index or -1 for root
        public SmplFrame[] frames;

        public const int NumJoints = 24;
        public const int Stride = 4;

        public int FrameCount => frames != null ? frames.Length : 0;
        public float Fps => (source != null && source.fps > 1f) ? source.fps : 30f;

        public Vector3 JointPos(int frame, int joint)
        {
            int b = joint * Stride;
            var f = frames[frame].joints_flat;
            return new Vector3(f[b], f[b + 1], f[b + 2]);
        }

        public float JointConf(int frame, int joint) => frames[frame].joints_flat[joint * Stride + 3];

        public float MinY()
        {
            float min = float.MaxValue;
            for (int i = 0; i < FrameCount; i++)
                for (int j = 0; j < NumJoints; j++)
                    min = Mathf.Min(min, frames[i].joints_flat[j * Stride + 1]);
            return min == float.MaxValue ? 0f : min;
        }

        public static SmplSkeletonDoc Load(string streamingAssetsRelativePath)
        {
            string path = Path.Combine(Application.streamingAssetsPath, streamingAssetsRelativePath);
            if (!File.Exists(path))
            {
                Debug.LogError($"[SmplSkeleton] file not found: {path}");
                return null;
            }
            var doc = JsonUtility.FromJson<SmplSkeletonDoc>(File.ReadAllText(path));
            if (doc == null || doc.FrameCount == 0 || doc.parents == null || doc.parents.Length != NumJoints)
            {
                Debug.LogError($"[SmplSkeleton] failed to parse / wrong topology: {path}");
                return null;
            }
            return doc;
        }
    }
}
```

- [ ] **Step 3: Create `SmplSkeletonDriver.cs`**

```csharp
using UnityEngine;

namespace BadmintonVR.SkeletonPlayer
{
    /// <summary>
    /// Loads skeleton.json v2 (SMPL-24) and renders a procedural twin: a sphere
    /// per joint and a capsule per bone (bone = joint -> its parent, so the spine
    /// chain pelvis->spine1->spine2->spine3->neck->head is drawn). Plays back by
    /// advancing a frame cursor with time. Helper objects are children of THIS
    /// object; Clear() destroys them on reload (keep this object at scene root).
    /// </summary>
    public class SmplSkeletonDriver : MonoBehaviour
    {
        [Tooltip("Path under StreamingAssets, e.g. skeleton/demo.skeleton.json")]
        public string skeletonFile = "skeleton/demo.skeleton.json";
        public bool play = true;
        [Range(0.01f, 0.12f)] public float jointRadius = 0.045f;
        [Range(0.01f, 0.08f)] public float boneRadius = 0.028f;
        public Color jointColor = new Color(0.95f, 0.85f, 0.2f);
        public Color boneColor = new Color(0.2f, 0.7f, 1f);
        [Range(0f, 1f)] public float confidenceCutoff = 0.3f;

        SmplSkeletonDoc _doc;
        Transform[] _joints;
        Transform[] _bones;      // one per non-root joint (index j -> bone to parents[j])
        Material _jointMat, _boneMat;
        float _groundOffset;
        float _t;
        int _frame;

        void Start()
        {
            _doc = SmplSkeletonDoc.Load(skeletonFile);
            if (_doc != null) Build();
        }

        void Build()
        {
            Clear();
            _groundOffset = -_doc.MinY();
            _jointMat = MakeMat(jointColor);
            _boneMat = MakeMat(boneColor);

            _joints = new Transform[SmplSkeletonDoc.NumJoints];
            for (int j = 0; j < SmplSkeletonDoc.NumJoints; j++)
            {
                var s = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                s.name = $"joint_{j}_{_doc.joint_names[j]}";
                s.transform.SetParent(transform, false);
                s.transform.localScale = Vector3.one * (jointRadius * 2f);
                s.GetComponent<Renderer>().sharedMaterial = _jointMat;
                DestroyCollider(s);
                _joints[j] = s.transform;
            }

            _bones = new Transform[SmplSkeletonDoc.NumJoints];   // index 0 (root) unused
            for (int j = 1; j < SmplSkeletonDoc.NumJoints; j++)
            {
                var c = GameObject.CreatePrimitive(PrimitiveType.Capsule);
                c.name = $"bone_{j}";
                c.transform.SetParent(transform, false);
                c.GetComponent<Renderer>().sharedMaterial = _boneMat;
                DestroyCollider(c);
                _bones[j] = c.transform;
            }
            ShowFrame(0);
        }

        void Update()
        {
            if (_doc == null || _joints == null) return;
            if (play)
            {
                _t += Time.deltaTime;
                _frame = Mathf.FloorToInt(_t * _doc.Fps) % _doc.FrameCount;
            }
            ShowFrame(_frame);
        }

        void ShowFrame(int frame)
        {
            Vector3 lift = new Vector3(0, _groundOffset, 0);
            for (int j = 0; j < SmplSkeletonDoc.NumJoints; j++)
            {
                bool ok = _doc.JointConf(frame, j) >= confidenceCutoff;
                _joints[j].gameObject.SetActive(ok);
                if (ok) _joints[j].localPosition = _doc.JointPos(frame, j) + lift;
            }
            for (int j = 1; j < SmplSkeletonDoc.NumJoints; j++)
            {
                int p = _doc.parents[j];
                bool ok = _doc.JointConf(frame, j) >= confidenceCutoff &&
                          _doc.JointConf(frame, p) >= confidenceCutoff;
                _bones[j].gameObject.SetActive(ok);
                if (ok) PlaceBone(_bones[j], _doc.JointPos(frame, j) + lift, _doc.JointPos(frame, p) + lift);
            }
        }

        void PlaceBone(Transform bone, Vector3 p0, Vector3 p1)
        {
            Vector3 dir = p1 - p0;
            float len = dir.magnitude;
            bone.localPosition = (p0 + p1) * 0.5f;
            bone.localScale = new Vector3(boneRadius * 2f, Mathf.Max(len * 0.5f, 0.001f), boneRadius * 2f);
            bone.localRotation = len > 1e-5f ? Quaternion.FromToRotation(Vector3.up, dir) : Quaternion.identity;
        }

        [ContextMenu("Validate JSON (no Play)")]
        void Validate()
        {
            var d = SmplSkeletonDoc.Load(skeletonFile);
            if (d == null) { Debug.LogError("[SmplSkeleton] validate: load failed"); return; }
            Debug.Log($"[SmplSkeleton] OK: {d.FrameCount} frames, {d.joint_names.Length} joints, " +
                      $"skeleton={d.skeleton}, spine1 parent={d.parents[3]}, neck parent={d.parents[12]}");
        }

        void Clear()
        {
            for (int i = transform.childCount - 1; i >= 0; i--)
            {
                var go = transform.GetChild(i).gameObject;
                if (Application.isPlaying) Destroy(go); else DestroyImmediate(go);
            }
            _joints = null; _bones = null;
        }

        static Material MakeMat(Color col)
        {
            var shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
            var m = new Material(shader);
            if (m.HasProperty("_BaseColor")) m.SetColor("_BaseColor", col); else m.color = col;
            return m;
        }

        static void DestroyCollider(GameObject go)
        {
            var col = go.GetComponent<Collider>();
            if (col != null) { if (Application.isPlaying) Destroy(col); else DestroyImmediate(col); }
        }
    }
}
```

- [ ] **Step 4: Manual verification in the editor**

1. Let Unity recompile (no errors in the Console).
2. Create an empty GameObject at scene root named `SmplTwin`, add the `SmplSkeletonDriver` component (leave `skeletonFile = skeleton/demo.skeleton.json`).
3. Right-click the component → **Validate JSON (no Play)**. Expected Console line: `OK: 60 frames, 24 joints, skeleton=smpl-24, spine1 parent=0, neck parent=9`.
4. Press **Play**. Expected: a 24-sphere figure **with a visible vertical spine chain** (pelvis→spine1→spine2→spine3→neck→head) standing on the floor, **sliding along +X** (the synthetic clip travels). No missing-bone gaps through the torso.

- [ ] **Step 5: Commit (local — scripts + generated demo JSON only)**

```bash
cd "<repo>" && git add Assets/Scripts/SkeletonPlayer/SmplSkeletonData.cs Assets/Scripts/SkeletonPlayer/SmplSkeletonDriver.cs Assets/StreamingAssets/skeleton/demo.skeleton.json && git commit -m "feat(unity): procedural SMPL-24 twin driver with spine (skeleton.json v2)"
```

---

### Task 6: Docs + progress ledger

**Files:**
- Modify: `tools/README.md` (append a v2 section)
- Modify: `docs/for-claude/PROGRESS.md` (append a dated entry)
- Modify: `docs/for-me/DECEMBER-PLAN.md` (mark the v2 schema as specced/built)

- [ ] **Step 1: Append to `tools/README.md`**

Add a section documenting the new pipeline:

```markdown
## Monocular SMPL skeleton (skeleton.json v2)

`smpl_to_skeleton.py` — convert WHAM SMPL output (from `colab/wham_extract.ipynb`)
into `skeleton.json v2` (SMPL-24 tree with a real spine). GPU-free.
- Demo: `python tools/smpl_to_skeleton.py --synthetic --out data/skeleton/demo.skeleton.json`
- Real: `python tools/smpl_to_skeleton.py --wham-output test_N.wham.npz --video-id test_N --out data/skeleton/test_N.skeleton.json`

`eval_pose.py` — accuracy vs SMPL ground truth (EMDB/3DPW):
`python tools/eval_pose.py --pred data/skeleton/test_N.skeleton.json --gt gt.npz --per-joint`

Unity: add `SmplSkeletonDriver` to a scene-root object; point `skeletonFile` at a
v2 file under `StreamingAssets/skeleton/`.
```

- [ ] **Step 2: Append a dated entry to `docs/for-claude/PROGRESS.md`**

Add (append-only) at the end:

```markdown
## 2026-07-23 — Monocular SMPL skeleton (skeleton.json v2)

Built the SMPL-24 pose path (spec: `docs/superpowers/specs/2026-07-23-monocular-smpl-skeleton-design.md`,
plan: `docs/superpowers/plans/2026-07-23-monocular-smpl-skeleton.md`).
- `tools/smpl_to_skeleton.py` — WHAM SMPL → `skeleton.json v2` (SMPL-24 + spine, `parents`, `betas`, `smpl` block). GPU-free; `--synthetic` demo generator. Tests in `tools/tests/`.
- `tools/eval_pose.py` — MPJPE / PA-MPJPE vs SMPL GT (EMDB/3DPW).
- `tools/colab/wham_extract.ipynb` — WHAM on Colab → normalized `.npz`.
- `Assets/Scripts/SkeletonPlayer/SmplSkeletonData.cs` + `SmplSkeletonDriver.cs` — procedural 24-joint twin with the spine chain; reads v2 from StreamingAssets.
- Schema v2 is producer-agnostic → multi-view triangulation can write the same file later.
Run tests: `./tools/.venv/Scripts/python.exe -m pytest tools/tests -v`.
```

- [ ] **Step 3: Update the v2 line in `docs/for-me/DECEMBER-PLAN.md`**

Find the "skeleton.json v2 design intent" reference and change it to point at the spec + plan as **specced + built**, e.g.:

```markdown
- **skeleton.json v2** — SMPL-24 (real spine) — SPECCED + BUILT.
  Spec: `docs/superpowers/specs/2026-07-23-monocular-smpl-skeleton-design.md`;
  plan: `docs/superpowers/plans/2026-07-23-monocular-smpl-skeleton.md`.
```

- [ ] **Step 4: Commit (local)**

```bash
cd "<repo>" && git add tools/README.md docs/for-claude/PROGRESS.md docs/for-me/DECEMBER-PLAN.md && git commit -m "docs(pose): document skeleton.json v2 pipeline + progress ledger"
```

---

## Self-Review

**Spec coverage:**
- §4 pipeline (WHAM → v2 → Unity → eval) → Tasks 4, 1/2, 5, 3. ✓
- §5 schema (flat `joints_flat`, `parents`, `betas`, `root_world`, `smpl` block, SMPL-24 order) → Task 1 (`build_v2_document`) + tests. ✓
- §5.1 joint order + spine chain → Task 1 constants test. ✓
- §6 five components → Tasks 1–6 (component 2 split across Tasks 1–2). ✓
- §6 multi-view seam (producer-agnostic schema) → schema has no producer-specific fields; `load_wham_output` is the only WHAM-specific surface, isolated from Unity/eval. ✓
- §7 accuracy (MPJPE/PA-MPJPE on EMDB/3DPW) → Task 3. ✓
- §8 risks: SMPL license (Task 4 README + Global Constraints), coordinate frame (single `apply_transform`, verified in Task 5 Step 4), JsonUtility nesting (Unity ignores `smpl`/`betas`; declares only flat fields). ✓
- §9 success criteria: travelling twin with spine (Task 5 Step 4), printed MPJPE/PA-MPJPE (Task 3 CLI), swap-producer-no-change (schema design). ✓

**Placeholder scan:** no TBD/TODO; every code step has complete code. Task 4's "adjust key names" risk is removed by computing joints via `smplx` from documented params rather than trusting WHAM's internal joint key. ✓

**Type consistency:** `joints_flat` is 24×4 everywhere; `parents` length 24 in Python (`SMPL_PARENTS`), JSON, and C# (`SmplSkeletonDoc.NumJoints`/parse check); `load_wham_output` keys (`joints3d/pose/betas/transl/fps`) match the npz written in Task 4 Cell 5 and consumed in Task 2 CLI; `mpjpe`/`pa_mpjpe`/`match_joints` signatures used in Task 3 tests match the implementation. ✓
