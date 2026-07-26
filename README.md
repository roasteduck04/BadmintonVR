# BadmintonVR

Turn ordinary video of a badminton player into a **3D digital twin** — body, court
position, and racket — accurate enough to feed biomechanics downstream.

```
phone video ─┬─► MediaPipe Pose (CPU)  ──► skeleton.json v1  ─┐
             │   + court homography       (33 kp, court xz)   │
             │                                                ├─► Unity twin
             └─► SMPL pass (Colab GPU) ──► skeleton.json v2  ─┤   Blender twin
                 + RacketVision 2D        (24 joints + spine, │   MP4 render
                   → 3D racket lift        27 with the racket)┘
```

Nothing here needs a local GPU: the CPU route (MediaPipe, calibration, lifting,
smoothing, Unity playback) runs on a laptop, and the two GPU passes — SMPL pose
and racket keypoints — run as Colab notebooks that hand back a `.npz`/`.json`.

## What works today

**Pose — two routes, one output contract.**

- **v1 (MediaPipe, local CPU)** — `tools/extract_skeleton.py` writes `skeleton.json`:
  33 joints × `[x, y, z, confidence]` per frame, hip-centered, Unity conventions baked
  in on the Python side.
- **v2 (SMPL, Colab GPU)** — `tools/colab/wham_extract.ipynb` runs a monocular SMPL pass
  (ROMP today; WHAM / 4D-Humans are drop-in upgrades) and `tools/smpl_to_skeleton.py`
  converts the `.npz` into **`skeleton.json v2`** — the SMPL-24 tree with a real spine,
  a superset of v1. Read `joint_names`/`parents`; never assume a joint count.
- **Accuracy** — `tools/eval_pose.py` reports MPJPE and PA-MPJPE in millimetres against
  SMPL ground truth (EMDB/3DPW or any v2 file), per-joint on request.

**Court position.** `tools/calibrate_court.py` solves a ground-plane homography
(image px → court metres) from four clicked corners. It handles stills or video,
**handheld/moving cameras** (`--multi N` interpolates corner pixels between keyframes and
re-solves per frame), and corners that pan **off-screen** (`--pad 0.4`).
`tools/check_position.py` back-projects the result onto the clip — the dot has to ride the
player's feet — and draws a top-down map.

**Racket.** `tools/colab/racketvision_extract.ipynb` (RacketVision, AAAI'26) detects five
2D racket keypoints; `tools/select_racket_track.py` picks one racket per frame, labelling
every frame `detected` / `interpolated` / `missing`; `tools/fit_camera.py` recovers the
weak-perspective camera the SMPL body was seen through; `tools/lift_racket_3d.py` lifts the
racket onto the body as joints 24–26 (`racket_grip` / `racket_head` / `racket_side`).
Position and roll carry **separate** status and confidence — roll is the weaker of the two,
so check it before trusting the face normal.

**Move labels.** `tools/label_moves.py` tiles a clip into stroke / moving / idle segments
and labels strokes with transparent rules (smash, clear, drop, lift, net shot, drive),
writing a `moves` block into the json (schema 1.1) that Unity renders as a subtitle track.

**Viewers.**

- **Blender** — `tools/blender/twin_compare.py` and `racket_viewer.py` drive the twin and
  its racket in a live scene; colour encodes racket confidence.
- **Video** — `tools/side_by_side_video.py test_6` renders the source clip beside the
  smoothed twin with a colour key, headless, in about a minute.
- **Unity** — a stick-figure or skinned twin replays the clip and walks the court.
  Editor menus under `Tools ▸ Badminton`: Build Court, Clip Switcher, Video Compare
  (split-screen source vs twin, `V` toggles), Racket, Debug HUD (per-joint confidence,
  trajectory with clamp markers, live stats).

## Repo layout

| Path | What |
|---|---|
| `tools/` | Python pipeline — extract, calibrate, validate, lift, label, render. [`tools/README.md`](tools/README.md) has full usage. |
| `tools/colab/` | The two GPU notebooks (SMPL pose, racket keypoints) + setup notes |
| `tools/blender/` | Blender twin viewers and the headless renderer |
| `Assets/Scripts/SkeletonPlayer/` | Unity runtime: playback, renderers, SMPL driver, racket, video compare, HUDs |
| `Assets/Editor/` | Unity editor menus (court builder, clip switcher, setup tools) |
| `data/raw/` | source videos — **gitignored** (large, and they show people and places) |
| `data/calib/` | per-clip court calibrations and cameras (`*_court.json`, `*_camera.json`) |
| `data/skeleton/` | extracted `skeleton.json` per clip (`.skeleton.json` = v2, `.skeleton_racket.json` = v2 + racket) |
| `docs/for-claude/` | working context: progress ledger, technical plans, research notes |
| `docs/superpowers/` | design specs and implementation plans |

Clips are named `test_N.mp4` and every derived file keeps the stem
(`test_6_court.json`, `test_6.skeleton.json`, …) — that convention is how the Unity and
Blender tools find the video and calibration that belong to a clip.

## Quickstart

```bash
python -m venv tools/.venv
tools/.venv/Scripts/pip install -r tools/requirements.txt
```

**Route v1 — pose + court position, entirely local:**

```bash
# calibrate the court once per camera setup (click 4 corners; --multi if handheld)
tools/.venv/Scripts/python tools/calibrate_court.py data/raw/test_5.mp4 --half far --multi 10 --pad 0.4

# extract pose + court position, then sanity-check that the dot rides the feet
tools/.venv/Scripts/python tools/extract_skeleton.py data/raw/test_5.mp4 --court
tools/.venv/Scripts/python tools/check_position.py data/raw/test_5.mp4
```

**Route v2 — SMPL body, and the racket on it:**

```bash
# 1. run tools/colab/wham_extract.ipynb on Colab -> test_6.smpl.npz
tools/.venv/Scripts/python tools/smpl_to_skeleton.py --wham-output test_6.smpl.npz \
    --video-id test_6 --out data/skeleton/test_6.skeleton.json

# 2. run tools/colab/racketvision_extract.ipynb -> test_6.racket2d.json
tools/.venv/Scripts/python tools/select_racket_track.py data/racket/test_6.racket2d.json \
    --out data/racket/test_6.rackettrack.json
tools/.venv/Scripts/python tools/fit_camera.py data/raw/test_6.mp4 models/smpl/test_6.smpl.npz \
    --out data/calib/test_6_camera.json
tools/.venv/Scripts/python tools/lift_racket_3d.py --skeleton data/skeleton/test_6.skeleton.json \
    --track data/racket/test_6.rackettrack.json --camera data/calib/test_6_camera.json \
    --out data/skeleton/test_6.skeleton_racket.json

# 3. see it
tools/.venv/Scripts/python tools/side_by_side_video.py test_6
```

No SMPL body model is needed for any local step — try the v2 path without one via
`python tools/smpl_to_skeleton.py --synthetic --out data/skeleton/demo.skeleton.json`.

For Unity, copy the json into `Assets/StreamingAssets/skeleton/`, point
`SmplSkeletonDriver.skeletonFile` at it (v2) or use `Tools ▸ Badminton ▸ Clip Switcher`
(v1), and press Play. Unity 6000.1, URP.

## Roadmap

| Phase | Status | What |
|---|---|---|
| 1. Pose-only twin | ✅ | clip → stick figure in Unity, plays in place |
| 2. Single-phone court position | ✅ | homography → twin walks the court, moving camera supported |
| 2.5 Racket | ✅ | RacketVision 2D → 3D racket on the twin, with per-frame confidence |
| Move recognition | ✅ v1 | transparent rules → `moves` block + Unity subtitle track |
| Monocular SMPL (v2) | ✅ | SMPL-24 skeleton + MPJPE/PA-MPJPE harness |
| Two-camera capture | 🔨 | **OpenCap** (2 iPhones → OpenSim) for biomechanics-grade 3D |
| Accuracy vs ground truth | 🔨 | per-joint error against MultiSenseBadminton / sensor GT |
| 2D shuttle tracking | 📝 | TrackNetV3 prototype on rally clips |
| Badminton-specific pose model | 🔜 | fine-tune on Colab, export ONNX |
| Near-live | 🔜 | inference server → in-Unity ONNX (Sentis) |

VR is a downstream demo, not the research. Muscle activation, joint loads, and injury
indicators are deliberately out of scope here.

## Privacy note

Raw videos, every image containing a video frame, and every rendered overlay are
deliberately excluded from this repo — only code, JSON data, and docs are published.
The licensed SMPL body models are excluded too; register at
[smpl.is.tue.mpg.de](https://smpl.is.tue.mpg.de) and supply your own.

## License

[MIT](LICENSE)
