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

`smpl_to_skeleton.py` — convert a monocular SMPL pass into `skeleton.json v2`
(SMPL-24 tree with a real spine). GPU-free, no SMPL model needed.
- Demo: `python tools/smpl_to_skeleton.py --synthetic --out data/skeleton/demo.skeleton.json`
- Real: `python tools/smpl_to_skeleton.py --wham-output test_N.smpl.npz --video-id test_N --out data/skeleton/test_N.skeleton.json`

The engine is **ROMP** (`colab/wham_extract.ipynb` — the filename is historical, see
`colab/README.md`); `--wham-output` is likewise historical and reads any `.npz` on the
contract `joints3d (T,24,3)` [+ optional `pose`/`betas`/`transl`/`fps`]. WHAM / 4D-Humans
stay as later quality upgrades — nothing downstream changes when the engine is swapped.

`eval_pose.py` — accuracy vs SMPL ground truth (EMDB/3DPW):
`python tools/eval_pose.py --pred data/skeleton/test_N.skeleton.json --gt gt.npz --per-joint`

Unity: add `SmplSkeletonDriver` to a scene-root object; point `skeletonFile` at a
v2 file under `StreamingAssets/skeleton/`.

## Blender twin (Route A — the current viewer)

Route A authors the body in **Blender** (SMPL add-on animated from the same npz) and
exports FBX to Unity, instead of drawing a procedural stick figure in Unity.

`blender/racket_viewer.py` — **Stage 3**: puts the lifted racket on both twins. Open
`test_6_compare.blend` → Scripting → Alt+P (same as below). Idempotent.

Two things make this non-trivial, and both are handled inside the script:
- **Undo the Unity Y-flip before fitting.** `skeleton.json` has been through
  `WORLD_TO_UNITY = diag(1,-1,1)`, a *reflection* — it mirrors the body, swapping left and
  right. Matching labelled joint to labelled joint without undoing it makes Procrustes solve
  for a mirror: measured residual **0.21 m vs 0.026 m** once corrected.
- **Fit per frame, not once.** The twins play *in place* (pelvis pinned at the origin) while
  the JSON carries the real root translation, so no single world transform exists. A
  per-frame Procrustes of the 24 SMPL joints onto the 24 bone heads absorbs that, and its
  residual is a live quality read-out: **2.6 cm** (raw body) / 3.0 cm median (smooth).
  That remainder is the add-on's template body vs ROMP's regressed joints — limb lengths
  agree to 3–7% — so the racket sits within a few cm of truth. That is this viewer's honest
  precision.

The racket draws as a shaft plus a **filled elliptical bed**, so its orientation reads at a
glance. Colour encodes confidence, because most frames are not measured: **green** = position
and roll both measured, **amber** = position measured but roll guessed, **red** = position is
the forearm prior. On test_6 that is 33% / 11% / 56% — a single uniform colour would imply
several times more real data than exists.

Panel (**N ▸ "Racket"**), per body, matching `twin_compare`'s layout: **Style** raw⟷smooth,
**Racket** on/off, **Joints** on/off (grip = blue, head = green, side = magenta; parented to
the racket, so they need no keyframes). The racket joints live in their own
`*_racket_joints` collections — `twin_compare.build_joints()` wipes the body's `*_joints`
collection on every run and would delete them.

`racket_smoothing.py` — the smooth Style. Smoothing the three racket points independently
would let a **rigid** object stretch and shear every frame, so the racket is decomposed into
what is actually free (grip position, shaft direction, width direction), each filtered, then
recomposed at the median length and width — rigid by construction. Width vectors are
sign-aligned first, since `left`/`right` are interchangeable and one meaningless relabelling
would otherwise swing the vector through zero and collapse the racket's plane.

The filter is a critically damped spring at τ = 0.12 s (the body's value), integrated in
closed form — explicit Euler blows up below τ ≈ 0.1 s at 25 fps — and run **zero-phase**
(forwards then backwards). Lag is a choice we don't have to make offline: one causal pass
lags 2.5 frames, and at the smash the racket head moves 8.8 m/s, so 100 ms would drag it
most of a metre behind the hand holding it. Measured: **93% less frame-to-frame jitter, zero
lag**. Note that is a high-frequency metric — RMS error against the true trajectory falls by
only about half, and on a fast swing barely at all, because τ = 0.12 s averages just a few
frames. Smoothing moves the head a median **5.8 cm** on test_6, rising to ~10 cm at the smash.

`blender/twin_compare.py` — the raw-vs-smoothed comparison viewer for
`models/smpl/test_6_compare.blend` (gitignored — regenerate locally). Open the .blend →
Scripting → Run (Alt+P) → `N` → **"TwinCompare"** tab. Idempotent: it rebuilds the 24
renderable joint spheres per body and re-registers the panel. Per-body toggles: Style
raw⟷smooth (spring 0.12 s, −85% jitter) + Skeleton + Mesh + Joints. Stick-armature bones
are viewport-only and never appear in a render — that is what the joint spheres are for.

## Racket (Phase 2.5)

`detect_racket.py` — zero-shot COCO "tennis racket" box probe, runs locally (fallback).

`colab/racketvision_extract.ipynb` — **RacketVision** (AAAI'26, MIT) RTMDet→RTMPose,
5 2D keypoints `top/bottom/handle/left/right` → `data/racket/<id>.racket2d.json` + an
overlay video. Colab GPU; the OpenMMLab install is finicky — see `colab/README.md`.
It runs the detector wide open (`score_thr 0.05`) and keeps the **top 3 boxes per frame
with keypoints for each**, because the detector score turned out to be nearly useless as
a confidence measure.

`select_racket_track.py` — picks ONE racket per frame out of those candidates and writes
`<id>.rackettrack.json`, the single unambiguous series Stage 2 consumes:

```bash
tools/.venv/Scripts/python tools/select_racket_track.py data/racket/test_6.racket2d.json \
    --out data/racket/test_6.rackettrack.json --overlay data/raw/test_6.mp4
```

The ranking signal is the **mean RTMPose keypoint score**, not the detector score — real
rackets score 0.6–0.75 there while false positives sit at 0.1–0.3, and on test_6 a
detector score of 0.08 carried a textbook fit while 0.30 boxes were net-post artifacts.
Selection is: strict accept at `kp_score ≥ 0.50` → drop picks that jump >250 px from every
neighbour within ±2 frames → recover borderline frames (≥0.35) that sit near an accepted
neighbour *and* keep a plausible grip-to-tip length → linearly interpolate gaps ≤4 frames
(never extrapolating past the ends). Every frame is labelled `detected` /`interpolated` /
`missing`, so a filled gap can't be mistaken for a measurement. `--overlay` burns the
result over the clip (interpolated frames draw dimmed); it is frame-bearing video, so keep
it under `data/` where it's gitignored.

### Stage 2 — lift the 2D racket onto the 3D body

```bash
# 1. recover the camera the SMPL body was seen through (ROMP never exported it)
tools/.venv/Scripts/python tools/fit_camera.py data/raw/test_6.mp4 \
    models/smpl/test_6.smpl.npz --out data/calib/test_6_camera.json

# 2. lift -> skeleton with joints 24 (racket_grip) + 25 (racket_head)
tools/.venv/Scripts/python tools/lift_racket_3d.py \
    --skeleton data/skeleton/test_6.skeleton.json \
    --track    data/racket/test_6.rackettrack.json \
    --camera   data/calib/test_6_camera.json \
    --out      data/skeleton/test_6.skeleton_racket.json
```

`fit_camera.py` fits a **per-frame weak-perspective** camera (`u = s·X + tx`) by pairing
MediaPipe's 2D landmarks with ROMP's 3D joints on 12 limb joints they agree on. Weak
perspective is not a simplification — it is what ROMP actually optimises, and it measured
better than a pinhole on test_6 (22.7 px vs 34.0 px median rms at 4K). Image coords are
normalized by frame **width** on both axes, so the 1080p racket pass, the 720p SMPL pass and
the 4K source all reconcile without bookkeeping.

`lift_racket_3d.py` solves the depth. Inverting weak perspective returns the racket's world
X and Y outright, so only `dZ` is unknown, and the fixed racket length gives it:
`dZ = ±√(L² − dX² − dY²)`. That leaves a two-way sign choice per frame, resolved per run of
frames — seeded from the forearm, then propagated by continuity. `L` is *measured* from the
clip (apparent length peaks when the racket lies in the image plane, so a high percentile is
the true length) rather than assumed. Undetected frames fall back to the forearm direction
at the hand, written with confidence 0 and `racket_status: "prior"` so a posed racket can
never be mistaken for a measured one. Handedness is auto-detected.

**Roll — the third degree of freedom.** Grip and tip fix only the shaft axis, which leaves
the racket a *line*: nothing there says whether the face is edge-on or flat-on. `left`/`right`
straddle the head rim, perpendicular to the shaft and in the racket plane, so they carry
exactly that. Same solve as the shaft — head width gives the depth magnitude, perpendicularity
picks its sign — and the head width comes out at **0.209 m** against a real 0.20–0.23 m,
another free scale check. Roll is stored as a scalar angle about the shaft (so it can be
smoothed and interpolated honestly) and treated as **π-periodic**, because `left` and `right`
are interchangeable on a symmetric head: a 180° flip is a relabelling, not motion.

Roll carries its own status and confidence, separate from position, because it is
substantially less reliable — `left`/`right` are the model's weakest keypoints (74.6/75.5
published vs 97–99 for the long axis; the hand sits right on them). On test_6 the shaft is
solved in 44% of frames but the roll in **33%** (+5% bridged across gaps ≤4 frames).
Gating on the side-keypoint scores and on how far the raw solve sits off perpendicular cut
the frame-to-frame face-normal noise from p90 40° to p90 31°. Use `--no-roll` for a bare line.

Output note: `joints_flat` becomes **27** joints — `racket_grip` (24), `racket_head` (25),
`racket_side` (26). Read `joint_names`/`parents`; anything hardcoding 24 will break.
Build the racket frame as `shaft = head − grip`, `across = side − head`,
`normal = shaft × across`, and check `racket_roll_status` before trusting the normal.
