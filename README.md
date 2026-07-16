# BadmintonVR

Turn a single phone video of a badminton player into a **moving digital twin on a
regulation court in Unity** — pose, court position, and (next) the racket.

```
phone video ──► MediaPipe Pose (Python, CPU) ──► skeleton.json ──► Unity twin
                court homography (clicked corners)      │
                └── court position (meters) ────────────┘
```

No GPU required for capture or playback: pose extraction runs on CPU
(MediaPipe), Unity replays the result. Model training (later phases) happens on
Colab/cloud.

## What works today

- **Pose extraction** — `tools/extract_skeleton.py` runs MediaPipe Pose over a
  clip and writes `skeleton.json` (schema v1: 33 joints × [x,y,z,confidence]
  per frame, Unity coordinate conventions baked in on the Python side).
- **Court calibration** — `tools/calibrate_court.py` builds a ground-plane
  homography (image px → court meters) from 4 clicked corners. Handles:
  - still images or videos;
  - **moving/handheld cameras** via multi-keyframe calibration (`--multi N`,
    schema v2: corner pixels are interpolated between keyframes and a fresh
    homography is solved per frame);
  - corners that panned **off-screen** (`--pad 0.4` adds a clickable margin).
- **Position validation** — `tools/check_position.py` back-projects the
  extracted trajectory onto the video (the dot must ride the player's feet) and
  draws a top-down court map.
- **Unity playback** — a stick-figure twin (or skinned avatar) replays the clip
  and *walks the court* using the extracted positions. Editor tooling:
  - `Tools ▸ Badminton ▸ Build Court` — regulation court from code;
  - `Tools ▸ Badminton ▸ Clip Switcher` — swap clips live;
  - `Tools ▸ Badminton ▸ Video Compare` — split-screen source video vs twin,
    time-synced (V to toggle);
  - `Tools ▸ Badminton ▸ Racket` — arm-estimated racket on clips that have one;
  - `Tools ▸ Badminton ▸ Debug HUD` — see what the pipeline sees: per-joint
    confidence coloring, court trajectory with clamp-hit markers, live stats.

## Repo layout

| Path | What |
|---|---|
| `tools/` | Python pipeline (extract, calibrate, validate). `tools/README.md` has full usage. |
| `Assets/Scripts/SkeletonPlayer/` | Unity runtime: playback, renderer, racket, video compare, debug HUD |
| `Assets/Editor/` | Unity editor menus (court builder, clip switcher, setup tools) |
| `data/raw/` | source videos — **gitignored** (large, and they show people/places) |
| `data/calib/` | per-clip court calibrations (`*_court.json`; check images gitignored) |
| `data/skeleton/` | extracted `skeleton.json` per clip |
| `docs/` | progress ledger, research notes, design specs |

Clips are named `test_N.mp4`; every derived file keeps the stem
(`test_5_court.json`, `test_5.json`, …), which is how the Unity tools find the
matching video/calibration for a clip.

## Quickstart

```bash
# 1) Python env (3.12)
python -m venv tools/.venv
tools/.venv/Scripts/pip install -r tools/requirements.txt

# 2) Calibrate the court for your clip (click 4 corners; --multi if handheld)
tools/.venv/Scripts/python tools/calibrate_court.py data/raw/test_5.mp4 --half far --multi 10 --pad 0.4

# 3) Extract pose + court position
tools/.venv/Scripts/python tools/extract_skeleton.py data/raw/test_5.mp4 --court

# 4) Sanity-check (dot must ride the feet)
tools/.venv/Scripts/python tools/check_position.py data/raw/test_5.mp4

# 5) Copy data/skeleton/test_5.json to Assets/StreamingAssets/skeleton/ and
#    press Play in Unity (6000.1, URP). Use Tools ▸ Badminton ▸ Clip Switcher.
```

## Roadmap

| Phase | Status | What |
|---|---|---|
| 1. Pose-only twin | ✅ | clip → stick figure in Unity, plays in place |
| 2. Single-phone court position | ✅ | homography → twin walks the court (moving camera supported) |
| 2.5 Racket | 🔨 | arm-estimated racket now; detector (YOLO / RacketVision-style keypoints) next |
| AI smoothing | 📝 | confidence-weighted filtering → Kalman → temporal lifting ([plan](docs/ai-smoothing-plan.md)) |
| 3. Two-camera capture | 🔜 | OpenCap-style triangulation for true 3D (plan not concrete yet) |
| 4. Badminton-specific pose model | 🔜 | fine-tune on Colab, export ONNX |
| 5. Near-live | 🔜 | inference server → in-Unity ONNX (Sentis) |

## Privacy note

Raw videos and every image containing a video frame are deliberately excluded
from the repo — only code, JSON data, and docs are published.

## License

[MIT](LICENSE)
