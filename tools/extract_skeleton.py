"""
extract_skeleton.py — Phases 1+2 of the BadmintonVR video->twin pipeline.

Video (phone clip) -> MediaPipe Pose -> smoothed, Unity-space skeleton.json.

Phase 1: pose only, hip-centered (the twin plays in place).
Phase 2: pass --court <calib.json> (from tools/calibrate_court.py) and the
player's foot pixel is projected through the ground-plane homography every
frame, filling `root_court_xz` (court X,Z in meters, origin at court center)
and `root_confidence` so Unity can move the twin around the court.

Usage:
    python tools/extract_skeleton.py data/raw/clip.mp4
    python tools/extract_skeleton.py data/raw/clip.mp4 --court data/calib/clip_court.json

Output: data/skeleton/<clip>.json (schema v1) + optional debug PNG.
"""

import argparse
import json
import os
import sys

import cv2
import numpy as np
from scipy.signal import medfilt, savgol_filter

import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

# MediaPipe Pose 33-landmark names, in index order (fixed contract for the schema).
LANDMARK_NAMES = [
    "nose", "left_eye_inner", "left_eye", "left_eye_outer",
    "right_eye_inner", "right_eye", "right_eye_outer",
    "left_ear", "right_ear", "mouth_left", "mouth_right",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_pinky", "right_pinky",
    "left_index", "right_index", "left_thumb", "right_thumb",
    "left_hip", "right_hip", "left_knee", "right_knee",
    "left_ankle", "right_ankle", "left_heel", "right_heel",
    "left_foot_index", "right_foot_index",
]
NUM_JOINTS = len(LANDMARK_NAMES)  # 33

DEFAULT_MODEL = os.path.join(os.path.dirname(__file__), "models", "pose_landmarker_full.task")


def rotate_frame(frame, degrees):
    if degrees == 90:
        return cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    if degrees == 180:
        return cv2.rotate(frame, cv2.ROTATE_180)
    if degrees == 270:
        return cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return frame


def extract_raw(video_path, model_path, rotate, min_conf):
    """Run MediaPipe over the video.
    Returns (positions[T,33,3], vis[T,33], img_pts[T,33,2], fps, size, n_frames).
    positions are hip-centered world meters; img_pts are 0..1 normalized image coords."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        sys.exit(f"ERROR: could not open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    options = mp_vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=model_path),
        running_mode=mp_vision.RunningMode.VIDEO,
        min_pose_detection_confidence=min_conf,
        min_tracking_confidence=min_conf,
        num_poses=1,
    )
    landmarker = mp_vision.PoseLandmarker.create_from_options(options)

    positions, vis, img_pts = [], [], []
    frame_idx = 0
    detected = 0
    out_size = None

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame = rotate_frame(frame, rotate)
        if out_size is None:
            out_size = [frame.shape[1], frame.shape[0]]  # [w, h]

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        timestamp_ms = int(frame_idx * 1000.0 / fps)
        result = landmarker.detect_for_video(mp_image, timestamp_ms)

        if result.pose_world_landmarks:
            lms = result.pose_world_landmarks[0]
            positions.append([[lm.x, lm.y, lm.z] for lm in lms])
            vis.append([lm.visibility for lm in lms])
            ilms = result.pose_landmarks[0]
            img_pts.append([[lm.x, lm.y] for lm in ilms])
            detected += 1
        else:
            positions.append([[np.nan] * 3 for _ in range(NUM_JOINTS)])
            vis.append([0.0] * NUM_JOINTS)
            img_pts.append([[np.nan] * 2 for _ in range(NUM_JOINTS)])

        frame_idx += 1

    cap.release()
    landmarker.close()

    print(f"  frames read: {frame_idx}, pose detected: {detected} "
          f"({100.0 * detected / max(frame_idx, 1):.1f}%)")
    if detected == 0:
        sys.exit("ERROR: no pose detected in any frame. Try --rotate 90/180/270 "
                 "(portrait phone video is often stored sideways).")

    return (np.array(positions, dtype=np.float64),
            np.array(vis, dtype=np.float64),
            np.array(img_pts, dtype=np.float64), fps, out_size, frame_idx)


def clean_and_smooth(pos, vis, min_conf, window):
    """Mask low-confidence joints, interpolate short gaps, Savitzky-Golay smooth."""
    T = pos.shape[0]
    pos = pos.copy()
    pos[vis < min_conf] = np.nan  # drop low-confidence samples

    # Linear-interpolate NaN gaps per joint/axis along time.
    for j in range(NUM_JOINTS):
        for a in range(3):
            col = pos[:, j, a]
            good = ~np.isnan(col)
            if good.sum() >= 2:
                idx = np.arange(T)
                col[~good] = np.interp(idx[~good], idx[good], col[good])
                pos[:, j, a] = col
            else:
                pos[:, j, a] = 0.0  # joint never reliably seen

    # Temporal smoothing (needs odd window <= T).
    if T >= 5:
        w = min(window, T if T % 2 == 1 else T - 1)
        if w % 2 == 0:
            w -= 1
        if w >= 5:
            pos = savgol_filter(pos, window_length=w, polyorder=2, axis=0)
    return pos


# Foot landmarks used to anchor the player to the floor (heels are the true
# ground contact; ankles are a fallback ~8cm up, close enough at this range).
HEELS = [29, 30]
FOOT_TIPS = [31, 32]
ANKLES = [27, 28]


def build_homography_series(calib, times):
    """Moving-camera calibration -> a homography for every frame.

    A schema-2.0 calibration holds the same court corners clicked at several
    timestamps. The court coords are fixed; only the pixels move as the camera
    pans. So we linearly interpolate each corner's PIXEL position across the
    keyframe times (clamped at the ends) and solve a fresh homography per frame.
    Returns H_series[T,3,3].
    """
    kfs = sorted(calib["keyframes"], key=lambda k: k["frame_time"])
    if len(kfs) < 2:
        sys.exit("ERROR: multi-keyframe calibration needs >= 2 keyframes.")
    kt = np.array([k["frame_time"] for k in kfs], dtype=np.float64)
    labels = list(kfs[0]["points"].keys())
    for k in kfs:
        if list(k["points"].keys()) != labels:
            sys.exit("ERROR: keyframes must click the SAME corners in the same order.")
    court_pts = np.array([kfs[0]["points"][lb]["court_xz"] for lb in labels],
                         dtype=np.float64)
    # px[K, L, 2]
    px = np.array([[kf["points"][lb]["px"] for lb in labels] for kf in kfs],
                  dtype=np.float64)

    T = len(times)
    L = len(labels)
    H_series = np.empty((T, 3, 3), dtype=np.float64)
    for i, t in enumerate(times):
        interp_px = np.empty((L, 2), dtype=np.float64)
        for a in range(2):
            for l in range(L):
                interp_px[l, a] = np.interp(t, kt, px[:, l, a])  # clamps at ends
        Hf, _ = cv2.findHomography(interp_px, court_pts, 0)
        if Hf is None:
            sys.exit(f"ERROR: homography solve failed at t={t:.2f}s (degenerate corners?)")
        H_series[i] = Hf
    print(f"  moving-camera calibration: {len(kfs)} keyframes "
          f"[{', '.join(f'{v:.1f}s' for v in kt)}] -> per-frame homography")
    return H_series


def court_positions(img_pts, vis, size, H, fps, min_conf, court_margin=1.5):
    """Project the player's foot point through the ground-plane homography.

    img_pts: [T,33,2] normalized image coords; H: image px -> court XZ (meters),
    either a single (3,3) matrix or a per-frame stack (T,3,3) for a moving camera.
    Returns (root_xz[T,2], root_conf[T]). Frames where no foot is reliably
    visible are interpolated from neighbors and get low confidence.
    """
    T = img_pts.shape[0]
    w, h = size
    per_frame_H = (H.ndim == 3)
    root_xz = np.full((T, 2), np.nan)
    root_conf = np.zeros(T)

    for t in range(T):
        # ground point = mean of visible heel/foot-tip landmarks (fallback: ankles)
        cand = [j for j in HEELS + FOOT_TIPS if vis[t, j] >= min_conf]
        if not cand:
            cand = [j for j in ANKLES if vis[t, j] >= min_conf]
        if not cand or np.isnan(img_pts[t, cand, 0]).any():
            continue
        px = img_pts[t, cand, 0].mean() * w
        py = img_pts[t, cand, 1].mean() * h
        Ht = H[t] if per_frame_H else H
        xz = cv2.perspectiveTransform(
            np.array([[[px, py]]], dtype=np.float64), Ht).reshape(2)
        root_xz[t] = xz
        root_conf[t] = float(vis[t, cand].mean())

    good = ~np.isnan(root_xz[:, 0])
    n_good = int(good.sum())
    print(f"  court position: {n_good}/{T} frames with a grounded foot "
          f"({100.0 * n_good / max(T, 1):.1f}%)")
    if n_good < 2:
        print("  WARNING: too few grounded frames; root_court_xz left empty.")
        return None, None

    # interpolate gaps, kill single-frame spikes (e.g. a brief lock onto a
    # bystander), then smooth (walking-scale motion)
    idx = np.arange(T)
    for a in range(2):
        root_xz[~good, a] = np.interp(idx[~good], idx[good], root_xz[good, a])
    if T >= 5:
        for a in range(2):
            root_xz[:, a] = medfilt(root_xz[:, a], kernel_size=5)
    win = int(round(fps * 0.25))  # ~0.25 s
    win = max(5, win | 1)         # odd, >= 5
    if T >= win:
        root_xz = savgol_filter(root_xz, window_length=win, polyorder=2, axis=0)

    # clamp to court + margin so a bad detection can't fling the twin away
    half_w, half_l = 3.05, 6.70
    root_xz[:, 0] = np.clip(root_xz[:, 0], -half_w - court_margin, half_w + court_margin)
    root_xz[:, 1] = np.clip(root_xz[:, 1], -half_l - court_margin, half_l + court_margin)
    return root_xz, root_conf


def to_unity(pos, flip_z):
    """MediaPipe world coords (x-right, y-down, z-into-screen, right-handed)
    -> Unity (x-right, y-up, z-forward, left-handed, meters)."""
    out = pos.copy()
    out[..., 1] = -out[..., 1]          # y down -> up
    if flip_z:
        out[..., 2] = -out[..., 2]      # optional depth flip (player facing)
    return out


def save_debug_frame(video_path, rotate, out_png):
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(cap.get(cv2.CAP_PROP_FRAME_COUNT) // 2))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return
    frame = rotate_frame(frame, rotate)
    options = mp_vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=DEFAULT_MODEL),
        running_mode=mp_vision.RunningMode.IMAGE, num_poses=1)
    lm = mp_vision.PoseLandmarker.create_from_options(options)
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    res = lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
    lm.close()
    if res.pose_landmarks:
        h, w = frame.shape[:2]
        for p in res.pose_landmarks[0]:
            cv2.circle(frame, (int(p.x * w), int(p.y * h)), 4, (0, 255, 0), -1)
    cv2.imwrite(out_png, frame)
    print(f"  debug frame -> {out_png}")


def main():
    ap = argparse.ArgumentParser(description="Extract a Unity-space skeleton from a video.")
    ap.add_argument("video")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", default=None, help="output json (default data/skeleton/<name>.json)")
    ap.add_argument("--min-confidence", type=float, default=0.3)
    ap.add_argument("--smooth-window", type=int, default=11)
    ap.add_argument("--rotate", type=int, default=0, choices=[0, 90, 180, 270])
    ap.add_argument("--flip-z", action="store_true", help="flip depth axis if the twin faces the wrong way")
    ap.add_argument("--debug-frame", action="store_true", help="also write a middle frame with keypoints drawn")
    ap.add_argument("--court", default=None, metavar="CALIB_JSON",
                    help="court calibration from tools/calibrate_court.py; "
                         "fills root_court_xz (Phase 2 position)")
    args = ap.parse_args()

    calib = None
    if args.court:
        with open(args.court) as f:
            calib = json.load(f)
        if args.rotate != calib.get("rotate", 0):
            sys.exit("ERROR: --rotate differs from the calibration frame's rotation; "
                     "recalibrate on the same orientation.")

    if not os.path.exists(args.model):
        sys.exit(f"ERROR: model not found: {args.model}\nSee tools/README.md for the download command.")

    # Handle the double-extension case (clip.mp4.mp4) cleanly for naming.
    base = os.path.basename(args.video)
    stem = base
    while os.path.splitext(stem)[1]:
        stem = os.path.splitext(stem)[0]

    out_path = args.out or os.path.join("data", "skeleton", stem + ".json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    print(f"Extracting: {args.video}")
    pos, vis, img_pts, fps, size, n_frames = extract_raw(args.video, args.model, args.rotate, args.min_confidence)
    pos = clean_and_smooth(pos, vis, args.min_confidence, args.smooth_window)
    pos = to_unity(pos, args.flip_z)

    root_xz, root_conf = None, None
    if calib is not None:
        if calib.get("image_size") and calib["image_size"] != size:
            print(f"  WARNING: calibration image size {calib['image_size']} != video {size}")
        if "keyframes" in calib:
            times = np.arange(pos.shape[0], dtype=np.float64) / fps
            H = build_homography_series(calib, times)
        else:
            H = np.array(calib["homography_img_to_court"], dtype=np.float64)
        root_xz, root_conf = court_positions(
            img_pts, vis, size, H, fps, args.min_confidence)

    frames = []
    for i in range(pos.shape[0]):
        # Flat array: 33 joints x [x, y, z, confidence] = 132 floats, in
        # joint_names order. Flat (not nested) so Unity's JsonUtility can parse
        # it with no extra packages.
        joints_flat = []
        for j in range(NUM_JOINTS):
            joints_flat.extend([round(float(pos[i, j, 0]), 5),
                                round(float(pos[i, j, 1]), 5),
                                round(float(pos[i, j, 2]), 5),
                                round(float(vis[i, j]), 3)])
        has_root = root_xz is not None
        frames.append({
            "frame_id": i,
            "time": round(i / fps, 4),
            "root_court_xz": [round(float(root_xz[i, 0]), 4),
                              round(float(root_xz[i, 1]), 4)] if has_root else None,
            "root_confidence": round(float(root_conf[i]), 3) if has_root else None,
            "joints_flat": joints_flat,
        })

    doc = {
        "schema_version": "1.0",
        "video_id": stem,
        "source": {"type": "phone_static", "fps": round(fps, 3), "resolution": size, "rotate": args.rotate},
        "extractor": {"pose": f"mediapipe-{mp.__version__}", "model": os.path.basename(args.model),
                      "notes": "world landmarks, hip-centered, confidence-gated + savgol smoothed",
                      "flip_z": args.flip_z},
        "coordinate_system": "unity",
        "joint_names": LANDMARK_NAMES,
        "court": {
            "calibration": os.path.basename(args.court),
            "convention": calib.get("convention"),
            "reprojection_error_m": calib.get("reprojection_error_m"),
            "multi_keyframe": calib.get("multi_keyframe", False),
            "num_keyframes": len(calib["keyframes"]) if "keyframes" in calib else None,
        } if calib is not None else None,
        "frames": frames,
    }

    with open(out_path, "w") as f:
        json.dump(doc, f)
    print(f"  wrote {len(frames)} frames -> {out_path}")

    if args.debug_frame:
        save_debug_frame(args.video, args.rotate, os.path.splitext(out_path)[0] + "_debug.png")


if __name__ == "__main__":
    main()
