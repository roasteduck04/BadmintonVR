"""Recover the camera ROMP's 3D body was seen through, by fitting it to MediaPipe 2D.

Why this exists
---------------
Stage 2 fuses two views of the same clip: the racket in **2D pixels**
(`<id>.rackettrack.json`) and the body in **3D metres** (from ROMP). That needs the
projection between them — and `test_6.smpl.npz` carries `joints3d/pose/betas/transl/fps`
but **no camera**; ROMP's was never exported. Rather than re-run ROMP, recover it locally:
MediaPipe gives 2D landmarks on the same clip (CPU, already wired up in
`extract_skeleton.py`) and ROMP gives the matching 3D joints. Twelve limb joints
correspond between the two skeletons, so every frame is over-determined.

Which model — measured, not assumed
-----------------------------------
Fitting one global pinhole `u = fx*X/Z + cx` to test_6 gave fx/fy split by 2.6x and 60 px
rms: the model was absorbing error, not describing the camera. Per frame, on the same data:

    per-frame weak perspective   median 22.7 px rms  (at 3840x2160)
    per-frame pinhole (f,cx,cy)  median 34.0 px rms

Weak perspective wins because that is what ROMP actually optimises — its depth is a
per-frame scale, not a metric distance, so the *internal* 3D structure is meaningful while
the absolute Z is not. This module therefore fits a **weak-perspective camera per frame**:

    u = s*X + tx        v = s*Y + ty

which is all Stage 2 needs, because the racket and the body are only ever related *within*
one frame. It also makes the lift almost trivial: inverting the projection recovers the
racket's 3D X and Y outright, leaving only Z ambiguous.

Coordinates: image points are normalized by frame **width** on both axes (`u/W`, `v/W`),
so `s`, `tx`, `ty` are resolution-independent — the racket pass ran at 1080p, the SMPL pass
at 720p, the source is 4K. `joints3d` is ROMP camera-space metres, vision-convention Y-down,
which matches image v-down, so no axis flip belongs here; the Unity Y-flip happens later in
`smpl_to_skeleton.WORLD_TO_UNITY`.

Usage
-----
    python tools/fit_camera.py data/raw/test_6.mp4 models/smpl/test_6.smpl.npz \
        --out data/calib/test_6_camera.json
"""

import argparse
import json
import os

import numpy as np

import extract_skeleton as es

# MediaPipe landmark index -> SMPL joint index, for joints both skeletons agree on.
# Limbs only: MediaPipe's torso/face landmarks sit on the skin surface and its "hips" are a
# different construction from SMPL's, so including them would bias the fit.
MP_TO_SMPL = {
    11: 16,  # left shoulder
    12: 17,  # right shoulder
    13: 18,  # left elbow
    14: 19,  # right elbow
    15: 20,  # left wrist
    16: 21,  # right wrist
    23: 1,   # left hip
    24: 2,   # right hip
    25: 4,   # left knee
    26: 5,   # right knee
    27: 7,   # left ankle
    28: 8,   # right ankle
}

MIN_VISIBILITY = 0.5
MIN_POINTS = 4          # 3 unknowns; 4 pairs keeps the fit over-determined


def fit_frame(p3, uv):
    """Weak-perspective (s, tx, ty) for one frame: u = s*X + tx, v = s*Y + ty.

    One shared scale across both axes — the isotropy is the point, an independent per-axis
    scale would silently fit away real error. Returns None if the system is underdetermined.
    """
    p3, uv = np.asarray(p3, float), np.asarray(uv, float)
    if len(p3) < MIN_POINTS:
        return None
    n = len(p3)
    a = np.zeros((2 * n, 3))
    b = np.empty(2 * n)
    a[0::2, 0], a[0::2, 1], b[0::2] = p3[:, 0], 1.0, uv[:, 0]
    a[1::2, 0], a[1::2, 2], b[1::2] = p3[:, 1], 1.0, uv[:, 1]
    sol, *_ = np.linalg.lstsq(a, b, rcond=None)
    s, tx, ty = (float(v) for v in sol)
    if s <= 0:
        return None                      # a non-positive scale is a degenerate fit
    r = (a @ sol - b).reshape(n, 2)
    return {"s": s, "tx": tx, "ty": ty, "n_points": n,
            "rms": float(np.sqrt((r ** 2).sum(axis=1).mean()))}


def project(cam, p3):
    """Project (...,3) camera-space points to (...,2) width-normalized image coords."""
    p3 = np.asarray(p3, float)
    return np.stack([cam["s"] * p3[..., 0] + cam["tx"],
                     cam["s"] * p3[..., 1] + cam["ty"]], axis=-1)


def unproject_xy(cam, uv):
    """Invert the projection: recover world X and Y from an image point.

    Weak perspective drops depth entirely, so this is exact for X and Y and says nothing
    about Z — which is precisely the ambiguity the racket-length constraint resolves.
    """
    u, v = uv
    return np.array([(u - cam["tx"]) / cam["s"], (v - cam["ty"]) / cam["s"]], dtype=np.float64)


def fit_series(img_pts, vis, joints3d, min_visibility=MIN_VISIBILITY):
    """Fit one weak-perspective camera per frame. Returns a list, None where unfittable.

    `img_pts` must already be width-normalized. Frames where MediaPipe found too few
    confident landmarks get None rather than a guess — Stage 2 treats those as no-camera.
    """
    mp_idx = list(MP_TO_SMPL)
    smpl_idx = [MP_TO_SMPL[i] for i in mp_idx]
    n = min(len(img_pts), len(joints3d))
    out = []
    for t in range(n):
        v = np.asarray(vis[t], float)[mp_idx]
        uv = np.asarray(img_pts[t], float)[mp_idx]
        keep = (v >= min_visibility) & np.isfinite(uv).all(axis=1)
        cam = fit_frame(joints3d[t][smpl_idx][keep], uv[keep])
        if cam is not None:
            cam["frame"] = t
        out.append(cam)
    return out


def normalize_by_width(img_pts, width, height):
    """MediaPipe returns 0..1 per axis; rescale to isotropic width-normalized coords."""
    p = np.asarray(img_pts, float).copy()
    p[..., 1] *= height / width          # x already is u/W; y was v/H, make it v/W
    return p


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Fit a per-frame weak-perspective camera from MediaPipe 2D + SMPL 3D.")
    ap.add_argument("video", help="the source clip (the same one the SMPL pass ran on)")
    ap.add_argument("smpl_npz", help="<id>.smpl.npz with joints3d")
    ap.add_argument("--out", required=True, help="output camera json")
    ap.add_argument("--model", default=es.DEFAULT_MODEL)
    ap.add_argument("--rotate", type=int, default=0, choices=[0, 90, 180, 270])
    ap.add_argument("--min-confidence", type=float, default=0.3)
    ap.add_argument("--min-visibility", type=float, default=MIN_VISIBILITY)
    args = ap.parse_args(argv)

    joints3d = np.asarray(np.load(args.smpl_npz)["joints3d"], dtype=np.float64)

    print(f"MediaPipe over {args.video} ...")
    _, vis, img_pts, _, size, n_frames = es.extract_raw(
        args.video, args.model, args.rotate, args.min_confidence)
    width, height = size
    if n_frames != len(joints3d):
        print(f"  WARNING: video has {n_frames} frames but joints3d has {len(joints3d)}; "
              f"pairing the first {min(n_frames, len(joints3d))}")

    cams = fit_series(normalize_by_width(img_pts, width, height), vis, joints3d,
                      args.min_visibility)
    good = [c for c in cams if c]
    if not good:
        raise SystemExit("no frame could be fitted -- check --rotate and the clip")

    doc = {
        "video_id": os.path.splitext(os.path.basename(args.video))[0],
        "source": "fit_camera.py (MediaPipe 2D <-> ROMP SMPL 3D)",
        "model": "weak_perspective_per_frame: u = s*X + tx, v = s*Y + ty",
        "image_coords": "normalized by frame WIDTH on both axes (u/W, v/W)",
        "coordinate_system": "ROMP camera space, metres, Y-down (pre-WORLD_TO_UNITY)",
        "video_size": size,
        "num_frames": len(cams),
        "frames": cams,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)

    rms = np.array([c["rms"] for c in good])
    scales = np.array([c["s"] for c in good])
    print(f"wrote {args.out}")
    print(f"  fitted {len(good)}/{len(cams)} frames")
    print(f"  reprojection rms: median {np.median(rms) * width:.1f} px "
          f"(p90 {np.percentile(rms, 90) * width:.1f}) at {width}x{height}")
    print(f"  scale s: min {scales.min():.4f} median {np.median(scales):.4f} "
          f"max {scales.max():.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
