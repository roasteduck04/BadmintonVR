# tools/ — Python extraction (Phase 1)

Turns a phone video into a Unity-space `skeleton.json` (schema v1).

## Setup (once)

```bash
python -m venv tools/.venv
tools/.venv/Scripts/python -m pip install -r tools/requirements.txt
```

The MediaPipe pose model is committed at `tools/models/pose_landmarker_full.task`.
If it's ever missing, re-download:

```bash
curl -sSL -o tools/models/pose_landmarker_full.task \
  https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task
```

## Run

```bash
tools/.venv/Scripts/python tools/extract_skeleton.py data/raw/<clip>.mp4
```

Writes `data/skeleton/<clip>.json`. Copy it into
`Assets/StreamingAssets/skeleton/` for Unity to load.

Useful flags:
- `--debug-frame` — also writes a mid-clip PNG with keypoints drawn (check
  detection + orientation).
- `--rotate 90|180|270` — if a portrait phone clip is decoded sideways and no
  pose is detected.
- `--flip-z` — if the twin faces the wrong way in Unity (depth-axis flip).
- `--min-confidence 0.3`, `--smooth-window 11` — tuning.

## What it does
1. MediaPipe Pose per frame → 33 world landmarks (hip-centered, meters) +
   visibility.
2. Drop low-confidence joints, interpolate short gaps, Savitzky-Golay smooth.
3. Convert to Unity axes (Y-up, left-handed, meters).
4. Write schema v1 (`joints_flat`: 33 × [x, y, z, confidence] per frame).

Phase 1 is pose only — no court homography / root translation (that's Phase 2).
The twin plays in place at court center.
