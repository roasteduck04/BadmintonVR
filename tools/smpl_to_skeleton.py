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
