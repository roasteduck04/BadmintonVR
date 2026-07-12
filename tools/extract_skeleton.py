"""
extract_skeleton.py — Phase 1 of the BadmintonVR video->twin pipeline.

Video (phone clip) -> MediaPipe Pose -> smoothed, Unity-space skeleton.json.

Phase 1 scope: pose only, hip-centered (the twin plays in place at court
center). No court homography / root translation yet (that is Phase 2).

Usage:
    python tools/extract_skeleton.py data/raw/clip.mp4
    python tools/extract_skeleton.py data/raw/clip.mp4 --rotate 90 --debug-frame

Output: data/skeleton/<clip>.json (schema v1) + optional debug PNG.
"""

import argparse
import json
import os
import sys

import cv2
import numpy as np
from scipy.signal import savgol_filter

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
    """Run MediaPipe over the video. Returns (positions[T,33,3], vis[T,33], fps, size, n_frames)."""
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

    positions, vis = [], []
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
            detected += 1
        else:
            positions.append([[np.nan] * 3 for _ in range(NUM_JOINTS)])
            vis.append([0.0] * NUM_JOINTS)

        frame_idx += 1

    cap.release()
    landmarker.close()

    print(f"  frames read: {frame_idx}, pose detected: {detected} "
          f"({100.0 * detected / max(frame_idx, 1):.1f}%)")
    if detected == 0:
        sys.exit("ERROR: no pose detected in any frame. Try --rotate 90/180/270 "
                 "(portrait phone video is often stored sideways).")

    return (np.array(positions, dtype=np.float64),
            np.array(vis, dtype=np.float64), fps, out_size, frame_idx)


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
    args = ap.parse_args()

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
    pos, vis, fps, size, n_frames = extract_raw(args.video, args.model, args.rotate, args.min_confidence)
    pos = clean_and_smooth(pos, vis, args.min_confidence, args.smooth_window)
    pos = to_unity(pos, args.flip_z)

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
        frames.append({
            "frame_id": i,
            "time": round(i / fps, 4),
            "root_court_xz": None,      # Phase 2
            "root_confidence": None,    # Phase 2
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
        "court": None,                  # Phase 2
        "frames": frames,
    }

    with open(out_path, "w") as f:
        json.dump(doc, f)
    print(f"  wrote {len(frames)} frames -> {out_path}")

    if args.debug_frame:
        save_debug_frame(args.video, args.rotate, os.path.splitext(out_path)[0] + "_debug.png")


if __name__ == "__main__":
    main()
