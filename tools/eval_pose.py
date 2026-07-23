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
