# tools/ — Python extraction (Phases 1+2)

Turns a phone video into a Unity-space `skeleton.json` (schema v1), including
the player's position on the court (Phase 2) when a court calibration exists.

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

## Run (batch — "just put it in")

Drop clips into `data/raw/`, then:

```bash
tools/.venv/Scripts/python tools/process_videos.py            # all videos in data/raw
tools/.venv/Scripts/python tools/process_videos.py test_1 test_2   # just these
```

This extracts each skeleton AND copies it into
`Assets/StreamingAssets/skeleton/` automatically, so Unity sees it with no
manual copy. Any flag (`--flip-z`, `--rotate 90`, `--min-confidence 0.4`) is
forwarded to every clip.

Then in Unity: **Tools ▸ Badminton ▸ Build Two-Player Scene** (front = test_1,
back = test_2) or **Choose Avatar** for a single player.

## Court position (Phase 2) — calibrate once per camera setup

**Scope: we track ONE half-court** (the void-deck paint IS only one half:
a box from the short service line to the baseline, with center line, long
service line and singles/doubles alleys — there is no net-to-SSL strip and
no other half). In court coordinates that half is the +Z side: net z=0,
SSL z=1.98, LSL z=5.94, baseline z=6.70.

**How to shoot for good position accuracy** (see docs/for-claude/PROGRESS.md 2026-07-14
for why): phone at the NET position facing the half, centered on the center
line, and as HIGH as possible (2.5 m+ — height is the #1 accuracy lever);
1.0x lens (NOT 0.6x — the ultrawide's barrel distortion bends the court
lines), 4K, tripod, stabilization off if possible; the half + ~1 m margin
fills the frame; nobody else in view. A low, corner-placed camera gets only
a few pixels per meter at the far side — position there is unmeasurable no
matter the software.

**Court corners are shared with Unity.** Building the court in Unity
(**Tools ▸ Badminton ▸ Build Court** / **Build Court (Tracked Half)**) writes
`data/calib/court_geometry.json` — the dimensions and every named corner, origin
at court center. `calibrate_court.py` loads that file automatically, so the
corner coordinates it calibrates against are exactly the ones the Unity floor is
drawn from (they can't drift apart). Delete the file to fall back to the
built-in constants (identical values). The tracked half's four corners are
`ssl_fl`, `ssl_fr`, `corner_fr`, `corner_fl`.

The camera must be STATIC (tripod / propped phone) and see the court lines.
Calibrate once per placement; every clip shot from that same placement reuses
the same calibration file:

```bash
tools/.venv/Scripts/python tools/calibrate_court.py data/raw/<clip>.mp4 \
    --half far --labels ssl_fl,ssl_fr,corner_fr,corner_fl
```

A window shows a frame: click the 4 corners of the half's painted box in the
prompted order (SSL-left, SSL-right, baseline-right, baseline-left; left/right
as seen FROM the camera). More points = better: any named line intersection
works (`--list-points` shows all names — e.g. `ssl_ctr_f`, `lsl_ctr_f`,
`ctr_bl_f` on the center line, `lsl_fl/fr` on the long service line;
`--point NAME=PX,PY` supplies them without the click UI). Clicks are
auto-snapped to the painted line corners. **Identify the lines carefully in a
multi-marking hall** — mislabeling the box (e.g. treating the half as a full
court, or clicking the neighboring paint set's lines for one side) was exactly
the position_front (now test_5) bug — twice. If two marking sets sit side by side, the
cheapest disambiguation is physical: **stand on a named intersection while
recording, then calibrate on that frame** (`--frame-time <sec>`) — your feet
mark the true point, so you can't click the wrong box.

It writes `data/calib/<clip>_court.json` + `..._overlay.png`. **Open the
overlay PNG and check the yellow grid sits on the real court lines** — if it
doesn't, a click was wrong (per-point errors are printed; >0.15 m = warning).
With `--half far/near` the overlay draws only that half of the grid.

**Position looks off? Diagnose it, don't guess** — the mismatch can live in
any layer (paint → clicks → homography → foot pixel → Unity floor), and each
layer has a check:

```bash
# 1) video side: red dot must ride the FEET in every panel of the sheet;
#    the top-down map shows the same path Unity will draw
tools/.venv/Scripts/python tools/check_position.py data/raw/<clip>.mp4

# 2) ground truth: click floor spots -> court XZ + distances between clicks.
#    Click the painted box ends: SSL->baseline must be 4.72 m, doubles width
#    6.10 m. Wrong distances = the paint is NOT regulation (or a corner was
#    mislabeled) — that shifts every extracted position.
tools/.venv/Scripts/python tools/check_position.py data/raw/<clip>.mp4 --probe
```

In Unity: **Tools ▸ Badminton ▸ Debug ▸ Show Court Corner Markers** (each
labeled marker must sit on its floor-line intersection) and **Draw Clip Path**
(draws the clip's path on the floor; compare with the `_check_topdown.png`
from step 1 — same path = Unity is faithful, offset is upstream). **Clear
Debug Markers** removes them.

Then extract as usual — `process_videos.py` picks up the calibration
automatically by name, or pass it by hand:

```bash
tools/.venv/Scripts/python tools/extract_skeleton.py data/raw/<clip>.mp4 \
    --court data/calib/<clip>_court.json
```

Frames then carry `root_court_xz` [X, Z court meters, origin center, camera
side = -Z] + `root_confidence`, and the Unity `HumanoidPoseDriver` walks the
twin around the court (Root position fields in its inspector).

How it works: the 4+ known court points give a ground-plane homography
(image -> court XZ). Each frame, the player's foot pixel (mean of visible
heel/foot-tip landmarks) is pushed through it, median-filtered (kills
single-frame glitches), Savitzky-Golay smoothed, and clamped to court+1.5 m.
Limits: position is only right while a foot is on the floor (fine for
walking tests; jumps land where the feet are, which is still roughly right),
and accuracy degrades outside the calibrated court rectangle.

## Move labels (what is the player DOING)

```bash
# print the move timeline (strokes + moving/idle, with the deciding features)
tools/.venv/Scripts/python tools/label_moves.py data/skeleton/<clip>.json --report

# write the labels into the json (and the StreamingAssets copy) for Unity
tools/.venv/Scripts/python tools/label_moves.py data/skeleton/<clip>.json --write

# debug video with the label burned in -> data/moves/ (gitignored)
tools/.venv/Scripts/python tools/label_moves.py data/skeleton/<clip>.json --overlay data/raw/<clip>.mp4
```

In Unity: **Tools ▸ Badminton ▸ Move Label ▸ Add To Twin**, Play — banner
top-center, segment timeline bottom, M toggles. Heuristic v1 (Approach A);
spec: `docs/superpowers/specs/2026-07-17-move-recognition-design.md`.

## Racket detection probe

```bash
# zero-shot COCO "tennis racket" over sampled frames -> data/racket/
tools/.venv/Scripts/python tools/detect_racket.py
```

## Run (single video, manual)

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

## Monocular SMPL skeleton (skeleton.json v2)

`smpl_to_skeleton.py` — convert WHAM SMPL output (from `colab/wham_extract.ipynb`)
into `skeleton.json v2` (SMPL-24 tree with a real spine). GPU-free.
- Demo: `python tools/smpl_to_skeleton.py --synthetic --out data/skeleton/demo.skeleton.json`
- Real: `python tools/smpl_to_skeleton.py --wham-output test_N.wham.npz --video-id test_N --out data/skeleton/test_N.skeleton.json`

`eval_pose.py` — accuracy vs SMPL ground truth (EMDB/3DPW):
`python tools/eval_pose.py --pred data/skeleton/test_N.skeleton.json --gt gt.npz --per-joint`

Unity: add `SmplSkeletonDriver` to a scene-root object; point `skeletonFile` at a
v2 file under `StreamingAssets/skeleton/`.
