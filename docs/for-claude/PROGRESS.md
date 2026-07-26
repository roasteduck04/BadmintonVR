# BadmintonVR — progress log

What has actually been built, how to run it, and what was decided along the
way. For humans AND for Claude sessions: read this before touching the
pipeline. The approved design lives in
`docs/superpowers/specs/2026-07-12-video-to-unity-twin-design.md`; the phase
list lives in `CLAUDE.md`. This file is the "what's done" ledger — append a
dated entry when something lands, don't rewrite history.

**Pipeline in one line:** phone video → MediaPipe pose (Python, CPU) →
`skeleton.json` (schema v1, the Python↔Unity contract) → Unity replays a
humanoid twin on a regulation court.

**Conventions (everything depends on these):** meters, Y-up, origin at court
center; X = court width (6.10 m doubles), Z = court length (13.40 m); the
camera side of the court is −Z. All coordinate conversion happens in Python —
Unity just reads the json.

---

## 2026-07-16 — Phase 2.2: source-video compare overlay in Unity

Picture-in-picture of the source phone video, on-screen and **time-synced to the
twin**, so you can compare the real footage against the twin's court position.

- **`Assets/Scripts/SkeletonPlayer/VideoCompareOverlay.cs`** — a component on the
  `SkeletonTwin` object. A `UnityEngine.Video.VideoPlayer` renders
  `data/raw/<clip-stem>.mp4` to a RenderTexture shown on a ScreenSpace-Overlay
  canvas. **Default layout = SplitScreen:** the video fills one half (letterboxed
  on black) and the **game camera's viewport rect is shrunk to the other half**
  (`Camera.main.rect`, restored on hide/remove) so the real footage and the twin
  sit side by side, not overlapping. `CornerPiP` layout is still available.
  Each frame it locks the video to the twin: matches speed and play/pause, and
  re-seeks only when it drifts >0.15 s (`resyncThreshold`). It **follows the Clip
  Switcher** — when the twin's `streamingAssetsPath` changes it auto-loads the
  matching source video (by stem). Resolves the video by absolute path (no need to
  import the 37 MB clips into Assets). Inspector: `layout`, `videoSide`
  (Right/Left), `gameCamera` (defaults to Camera.main), `sizeFraction`/`corner`
  (PiP mode), `toggleKey` (default **V** to show/hide at runtime). Missing source
  video → overlay hides + warns (e.g. clips with no `data/raw/*.mp4`).
- **`Assets/Editor/VideoCompareSetup.cs`** — **Tools ▸ Badminton ▸ Video Compare ▸
  Add Overlay To Scene / Remove Overlay**. Add attaches the component to every
  SkeletonPlayback (Undo-friendly, marks scene dirty). The PiP only draws in Play
  mode (that's when the twin animates); its UI is built at runtime, not saved.
- **Use:** Add Overlay once → press Play → left half = twin on court, right half =
  source video, in step → use the Clip Switcher to flip clips (video follows) →
  press V to toggle (restores full game view). Requires `com.unity.ugui` +
  `com.unity.modules.video` (both already in the manifest).
- **Input:** the project uses the new Input System package, so the V-toggle reads
  `Keyboard.current` under `#if ENABLE_INPUT_SYSTEM` (legacy `Input.GetKeyDown`
  fallback otherwise) — never call `UnityEngine.Input` directly in this project or
  it throws InvalidOperationException.

---

## 2026-07-16 — Phase 2.2: off-frame clicks + clip switcher; position_front & test_3 recalibrated (10 keyframes)

Extended the moving-camera workflow and re-did the two earlier position clips
with it, then made all clips switchable in Unity.

- **Off-frame corner clicking (`--pad FRAC`)** in `calibrate_court.py`. When the
  camera pans a corner off-screen you couldn't click it. Now `--pad 0.4` frames
  the video on a gray canvas with a **green rectangle marking the real frame
  edge**; click in the margin to estimate an off-screen corner. Returned pixel
  coords may be negative / exceed the image — the homography is fine with that;
  the auto-snap `refine` step skips any point outside the frame. It works:
  `position_front`'s `ssl_fr` corner was **off-frame in 7/10 keyframes** (y up to
  1154 > 1080) and still calibrated cleanly.
- **Re-calibrated both with `--multi 10 --pad 0.4 --scale 0.5 --half far`**
  (labels ssl_fl,ssl_fr,corner_fr,corner_fl):
  - **position_front** (1920×1080, 60 fps, 23.6 s — the old 0.6× ground-level
    clip): extract 100% pose / 100% grounded; check_position **100% inside box,
    NO clamp hits**, conf 0.92; foot-dot rides the feet through heavy panning in
    all 6 panels. The 10-keyframe moving homography rescued a clip whose single
    static calibration had failed back in Phase 2.1.
  - **test_3** re-extracted with 10 keyframes: 94.7% pose/grounded, **92% inside
    box**, conf 0.85. Still grazes the ±4.55 X / 8.20 Z clamps on a few far-
    baseline frames — that residual is inherent perspective blow-up at the far
    line (low camera, feet near the baseline), NOT camera drift, so keyframes
    don't remove it. Dot still rides the feet in every panel (extraction correct;
    the clamp spikes are brief noise, visible as a red excursion in the top-down
    inset).
- **Clip Switcher** — new `Assets/Editor/ClipSwitcher.cs`,
  **Tools ▸ Badminton ▸ Clip Switcher**. Scans `StreamingAssets/skeleton/*.json`
  and lists each as a button (current one marked ●). Edit mode: sets
  `SkeletonPlayback.streamingAssetsPath` + marks scene dirty. Play mode: calls
  `Load()` to swap the twin live. Handles >1 playback object (dropdown). No more
  hand-editing `badminton.unity` to compare clips.
- **In Unity:** copied `position_front.json` + `test_3.json` (10-keyframe
  versions) to `StreamingAssets/skeleton/`. Scene still defaults to `test_4.json`;
  use the Clip Switcher to flip between test_3 / test_4 / position_front.
- **Capture-angle note (asked):** position tracking (feet→court XZ) is
  orientation-independent — front, back (test_4), or side all track equally.
  Only limb/facing pose fidelity weakens from behind (mislabeled L/R, use
  `--flip-z` if the twin faces wrong). We're on stock MediaPipe; the Phase-4
  fine-tune data is rear/side broadcast footage, so non-front views aren't a
  problem for it either. Side-on is the best all-round capture angle.

---

## 2026-07-16 — Phase 2.2: moving-camera calibration (multi-keyframe), test_4.mp4

Second position clip: `test_4.mp4` (1920×1080, 60 fps, 16.2 s). The camera was
**panning/tilting the whole time** (handheld), so a single static homography —
the drift problem flagged on test_3 — would smear the far-baseline positions.
Fixed it by making the calibration **time-varying**.

- **New calibration mode: `--multi N`** in `tools/calibrate_court.py`. You click
  the same 4 corners at **N timestamps** (here N=5: ~0.3, 4.2, 8.1, 12.0, 15.9 s).
  It writes a **schema-2.0** json with a `keyframes: [...]` list (each keyframe =
  time + clicked corner pixels + its own homography) instead of one top-level
  homography. One overlay per keyframe in `data/calib/test_4_multi_overlays/`.
  Run: `calibrate_court.py data/raw/test_4.mp4 --multi 5 --half far
  --labels ssl_fl,ssl_fr,corner_fr,corner_fl`.
- **How the moving mapping works:** the court coords are fixed; only the pixels
  move as the camera pans. So `extract_skeleton.py` (and `check_position.py`)
  **linearly interpolate each corner's pixel position between the bracketing
  keyframes for every frame** and solve a fresh homography per frame (clamped to
  the end keyframes outside the bracket). `build_homography_series()` in both
  tools. A v1 (static) calib still works unchanged — detected by absence of
  `keyframes`.
- **The pixels really did drift:** e.g. `ssl_fl` y went 492→480→464→450→408 and
  `corner_fr` y 1077→1075→1068→1050→1036 across the 5 keyframes.
- **Extraction:** `extract_skeleton.py --court data/calib/test_4_court.json` →
  **100% pose, 100% grounded foot**, 971 frames → `data/skeleton/test_4.json`.
  `court.multi_keyframe=true`, `num_keyframes=5` recorded in the skeleton json.
- **Validation (`check_position.py`, now v2-aware — per-frame Hinv):** trajectory
  X∈[−1.85,+2.30], Z∈[+1.39,+5.82], conf 0.94, **82% inside the tracked box and
  NO clamp hits** (test_3's static calib was slamming the ±4.55/8.20 clamps). In
  the check sheet the **red foot-dot rides the feet in all 6 panels even as the
  court visibly rotates in-frame** — the per-frame homography is following the
  camera. `data/calib/test_4_check_sheet.png`, `_check_topdown.png`.
- **Into Unity:** copied to `Assets/StreamingAssets/skeleton/test_4.json`; scene
  `badminton.unity` points at `skeleton/test_4.json` (was test_3). Press Play →
  twin walks test_4's path; `Tools ▸ Badminton ▸ Debug ▸ Draw Clip Path` to
  cross-check against the top-down.
- **Takeaway:** multi-keyframe calibration removes the need for a tripod for
  slow handheld drift — clicking 5 keyframes is cheaper than a static clamp-
  fighting pass. For fast/large camera moves, add more keyframes.

---

## 2026-07-16 — Phase 2.2: test_3.mp4 player walks the court in Unity

First end-to-end position clip: `test_3.mp4` (1920×1080, 60 fps, 24.5 s) →
`data/skeleton/test_3.json` → the Unity twin walks `root_court_xz`.

- **New capture, new viewpoint.** test_3 is NOT court_2's position (despite the
  plan): higher/front-on, camera behind the **−X baseline corner** looking across;
  the lines are **freshly re-painted, high-contrast** (the grey-on-grey problem is
  gone). Different resolution + viewpoint than court_2, so the court_2 calibration
  does **not** transfer — re-calibrated on a test_3 frame.
- **Calibrated on a clean frame (t=14 s)**, user clicked the 4 box corners
  (`--half far`, order ssl_fl,ssl_fr,corner_fr,corner_fl) →
  `data/calib/test_3_court.json`. Validated: overlay's un-clicked internal lines
  (singles sidelines, centre line, LSL, the SSL+centre cross) ride the paint on
  the left and bottom; a little looser at the top baseline.
- **Orientation gotcha (again, opposite way):** in THIS view **top of frame =
  baseline, bottom = short service line** (camera behind the baseline). My read
  was backwards; the user's court knowledge settled it. Clicked px:
  `corner_fl`(28,302), `corner_fr`(1056,184), `ssl_fr`(1742,495), `ssl_fl`(628,1044).
- **Camera DRIFT ~50–60 px over the clip** (handheld, not a tripod — measured by
  ORB-tracking a fixed court point; it also smeared a median clean-plate). A single
  homography bakes this in as ~30–50 cm of far-end wobble. We accepted it for a
  first pass; positions are noisy near the baseline (a few frames overshoot Z and
  hit the ±1.5 m clamp; 91 % of frames land inside the painted box). **For tight
  results, next capture wants a locked-off/tripod camera** (or add per-frame
  drift-correction).
- **Extraction:** `extract_skeleton.py --court` → 94.7 % pose + grounded-foot.
  `check_position.py` confirms the back-projected foot dot rides the feet in every
  panel (extraction correct) and the top-down path is coherent.
- **Into Unity:** copied `test_3.json` → `Assets/StreamingAssets/skeleton/`, set
  `badminton.unity` SkeletonPlayback `streamingAssetsPath: skeleton/test_3.json`
  (driveRootPosition already on). Open the **badminton** scene, press Play → twin
  walks the court. `Tools ▸ Badminton ▸ Debug ▸ Draw Clip Path` draws the same
  path on the Unity floor to compare against `test_3_check_topdown.png`.

## 2026-07-16 — Phase 2.1: first VALID calibration (court_2.jpg, re-shot from a corner)

Re-shot the court as two stills from a higher, oblique corner angle (`court_1.jpg`,
`court_2.jpg` in `data/raw/`), 1.0x lens. The lens/height fix worked: lines are
dead straight (no barrel distortion), far corners have real pixels. Calibrating
**court_2** (both photos are the same half from different corners; the Phase 2.2
video will be shot from court_2's position).

- **Added still-photo support to `calibrate_court.py`** — `grab_frame` now
  `imread`s image files directly (`.jpg/.png/...`), so a one-off corner photo can
  be calibrated without wrapping it in a video. `--frame-time` is ignored for images.
- **Automatic corner-labeling does NOT work in this hall** and I burned a lot of
  effort proving it: the floor tiles run nearly parallel to the court lines, and
  grey paint on grey tile is low-contrast, so Hough/threshold lock onto tile seams
  and the lengthwise-vs-widthwise call is ambiguous. Every automated/eyeballed
  guess self-contradicted. **The reliable method here is the interactive click**
  (`--labels ssl_fl,ssl_fr,corner_fr,corner_fl`, user clicks the 4 box corners,
  auto-snap does the rest).
- **The court is oriented DIAGONALLY in frame** — this is the gotcha. `corner_fr`
  (far-right baseline corner) is at pixel ~(635,324), i.e. top-CENTER, not the top
  right edge. Assuming it was at the right edge is what skewed every pre-click
  attempt. The 4 clicked corners: `corner_fl`(47,424), `corner_fr`(635,324),
  `ssl_fr`(1063,445), `ssl_fl`(427,795).
- **Validated** via the overlay: the reprojected internal lines that were NOT
  clicked — centre line, both singles sidelines, LSL, and the near SSL edge — all
  ride the actual paint across the full court (few-px offsets at the far baseline,
  within click precision). This is the first calibration that holds up.

Output: `data/calib/court_2_court.json` (+ `court_2_overlay.png`). Ready to feed
Phase 2.2 once the video (same camera position as court_2) lands.

---

## 2026-07-15 — position mystery SOLVED: right-side corners were clicked on the neighboring paint set

User ran `--probe` and confirmed the crosses are NOT on the intersections he
walked to. Forensics (no user clicks needed — the walk itself is ground truth):

- **Rectified check** (warp the frame top-down with the calibrated H): the
  paint does NOT rectify — the far line reads z=6.6 on the left but z=6.0 on
  the right (should be 6.70 everywhere), there is an extra paint line ~0.9 m
  PAST the calibrated baseline, and FOUR vertical lines on the right where our
  court has two. A homography from correct correspondences would map the paint
  to a straight regulation grid; a tilted/unrectifiable result = wrong labels,
  not noise.
- **Stance frames are the ground truth**: at t=12.4 s he stands on the true
  `lsl_sing_fl` — the clicked left-side points sit AT his feet ✔. At t=19.6 s
  he stands on the true `lsl_sing_fr` — the clicked `lsl_sing_fr` / `lsl_fr` /
  `sing_bl_fr` / `corner_fr` are ~100–130 px away, on the SECOND painted box to
  the right of frame (the hall has two marking sets side by side). The right
  side of the calibration is another court's paint. That one wrong cluster
  drags the least-squares homography → the whole court tilts → near points off
  by +0.8 m, far region balloons to z=8.2.
- Likely secondary issue (check while re-clicking): on the far side the LSL
  and baseline are only ~30 px apart; some "baseline" clicks may have landed on
  the LSL. The unexplained paint line found at z≈7.6 in the rectified view is
  where the REAL baseline probably lives.

Evidence: `data/calib/position_front_recalib_guide.png` (side-by-side stance
frames, wrong clicks in red, true point circled green) and
`data/calib/position_front_rectified.png` (top-down warp vs expected grid).
(Both also archived under `docs/img/` for the personal journal `docs/for-me/DOCUMENTARY.md`.)

**Phase renumber:** because calibration turned out to be its own load-bearing
problem, Phase 2 is now split (see `CLAUDE.md`) — **2.1 = corner tracking &
calibration** (IN PROGRESS, this attempt failed, awaiting a re-shot video) and
**2.2 = position → Unity twin** (the old Phase 2 pipeline, already built, blocked
on a valid 2.1 calibration).

**Fix = recalibrate, no code changes:** re-run `calibrate_court.py`, click only
intersections of the box HE walked (left cluster + center + the true right
sideline = the vertical line ending under his feet in the guide image; ignore
the second box entirely). Tip that makes this repeatable: **stand on a named
intersection during recording, then calibrate on that frame**
(`--frame-time 19.6`) — your own feet disambiguate the paint sets.

## 2026-07-14 (later 3) — mismatch diagnostic toolkit (no hardcoding)

User suspected the video-detected corners don't match Unity's court corners
("area of movement starts at a greater Z"). Instead of guessing a fix, built a
layer-by-layer diagnostic toolkit; each check isolates one pipeline layer:

- **`tools/check_position.py <clip>`** — video side. Back-projects the
  extracted trajectory onto the video (contact sheet: red dot must ride the
  FEET) + renders a to-scale top-down map (`_check_topdown.png`, drawn from
  `court_geometry.json`). `--video` writes a per-frame mp4.
- **`tools/check_position.py <clip> --probe`** — ground truth. Click any floor
  spot → court XZ through the homography; consecutive clicks print distances.
  Regulation checks: SSL→baseline 4.72 m, doubles width 6.10 m, singles
  5.18 m, LSL→baseline 0.76 m. Wrong distances = the void-deck paint is not
  regulation-sized (or a corner is mislabeled) — shifts every position.
- **Unity: Tools ▸ Badminton ▸ Debug ▸ Show Court Corner Markers / Draw Clip
  Path / Clear Debug Markers** (`Assets/Editor/CourtDebugTools.cs`) — markers
  at every `court_geometry.json` point (must sit on the drawn lines; near-half
  points skipped on a tracked-half build) and the clip's root path on the
  floor (green start, red end, 5 s ticks) for comparison with the top-down PNG.

**Results on position_front (all checks run, Unity via MCP):**
- Contact sheet: dot rides the feet in all 6 panels → extraction ✔
- Corner markers sit exactly on the floor-line intersections → Unity floor ✔
- Unity path stats byte-identical to Python's (start (+0.17,+4.92),
  Z [2.55..8.20], 69% in box) → Unity playback ✔
- Signed calibration residuals ±0.2 m, mixed sign — no systematic Z bias at
  the calibrated points.

**Remaining unverified layer: is the paint regulation-sized?** Only the user
can test this → run `--probe` and click the painted box ends. If SSL→baseline
≠ 4.72 m, the corner labels/paint assumption is wrong and every Z is scaled.

**Route check (user ground truth: he walked ssl_sing_fl → lsl_sing_fl →
lsl_sing_fr).** Added `check_position.py --route NAME,NAME,...` — for each
named point it renders the closest-approach frame (court-space AND image-space)
with the extracted dot + the back-projected true point. Findings:
- The dot rides the FEET in every frame → extraction reads the video correctly.
- NOT a scale error: dZ is +0.82 m at the NEAR point (z=1.98) but only +0.17 m
  at the far ones (z=5.94) — a Z-scale error would grow with z, this shrinks.
- Turn-apex misses (0.4–0.9 m) point back along the approach direction each
  time → consistent with the root being the MEAN of both feet (mid-stride the
  mean lags the planted foot) + smoothing rounding the apex.
- Perspective leverage measured from the calibration pixels: **2.0 cm/px at
  the SSL–LSL span, 5.4 cm/px at LSL→baseline, 12.7 cm/px far-left** — near
  the baseline a ~20 px foot wobble is already >1 m of Z. (t=19.1 s frame:
  feet 134 px from the true point in the image = 1.98 m in court space.) The
  low camera is the amplifier, as documented in the capture protocol above.
- OPEN QUESTION for the user: in the `_route_*.png` frames the magenta cross
  is sometimes one paint line away from the intersection under his feet — in
  this multi-marking hall the calibration may have labeled a neighboring line
  (the old full-court bug's little sibling). User must confirm the crosses sit
  on the intersections he aimed at; `--probe` clicks settle it in a minute.

## 2026-07-14 (later 2) — stick-figure twin walks the court + shared court corners

Two changes after the recalibration, both from user feedback ("revert the skin
back to joints and lines"; "the court doesn't match the flooring — note the
corner coordinates so the video/model script uses them"):

1. **Stick figure carries the court position now.** `SkeletonPlayback.cs` gained
   the same Phase-2 root translation `HumanoidPoseDriver` had
   (`driveRootPosition` / `rootConfidenceCutoff` / `rootSmoothing`): when the
   clip has `root_court_xz`, the whole joints-and-lines figure is moved to the
   player's court XZ each frame; clips without it still play in place. So you get
   the walking twin **without** a skinned model. **Tools ▸ Badminton ▸ Build
   Skeleton Player** now defaults to `position_front.json`, builds the tracked
   half, places the preview at the clip's start position, and frames the camera
   above the net looking down the half (the capture vantage).

2. **One source of truth for court corners.** `CourtBuilder.cs` now writes
   `data/calib/court_geometry.json` (dimensions + every named line-intersection,
   origin court center) on *every* court build, and `tools/calibrate_court.py`
   loads that file at import to source `COURT_POINTS` (falls back to its own
   constants if absent). The Unity floor and the calibration corners can no
   longer drift apart — regenerate the court and the calibrator picks up the
   same numbers. The four tracked-half corners are `ssl_fl (-3.05, 1.98)`,
   `ssl_fr (3.05, 1.98)`, `corner_fr (3.05, 6.70)`, `corner_fl (-3.05, 6.70)`.

3. **Tracked-half court build.** New **Tools ▸ Badminton ▸ Build Court (Tracked
   Half)** draws only the +Z half (net z=0 → baseline z=6.70) so the floor
   matches the recorded box instead of a full court whose near half is never
   used. Origin/coordinates are unchanged, so `position_front` still lands in the
   same place — it just sits on a floor that represents what was actually filmed.
   (The full-court build is unchanged under **Build Court**.)

Note on the `position_front` clip specifically: the person walked *around the
outside of the baseline* (Z up to ~8.2 m, past the 6.70 m baseline), so the twin
correctly walks off the back edge of the half — that is faithful to the video,
not a calibration error. Future clips that stay inside the box sit fully on it.

---

## Phase 1 — pose-only twin (DONE, 2026-07-12)

Clip → 33 MediaPipe world landmarks per frame → confidence-gated, gap-
interpolated, Savitzky-Golay smoothed → Unity axes → `data/skeleton/<name>.json`.

- `tools/extract_skeleton.py` — the extractor (CPU, ~4 min for a 24 s 1080p60 clip).
- `tools/process_videos.py` — batch: every clip in `data/raw/` → json → auto-copy
  into `Assets/StreamingAssets/skeleton/`.
- `Assets/Scripts/SkeletonPlayer/HumanoidPoseDriver.cs` — rotation-only Mecanim
  retarget (avatar keeps its own proportions; pelvis basis orients the body,
  each limb segment aligned absolutely). Works on any Humanoid rig.
- Editor menus: **Tools ▸ Badminton ▸ Build Court / Build Two-Player Scene /
  Choose Avatar**.
- Scene `Assets/badminton.unity`: court + one mannequin (`Player_Back`, cobalt
  body / amber joints, materials `Assets/Materials/Player_*.mat` — URP, color
  lives in `_BaseColor`).

Known quirk: **Build Two-Player Scene re-creates two default grey players** —
re-running it will undo the single-player cleanup (fix pending if it annoys).

## Phase 2 — single-phone court position (DONE 2026-07-13, awaiting in-Unity eyeball check)

Goal: with ONE static phone, know WHERE the player is on the court and move
the twin there. Method: **ground-plane homography** — the court's line
intersections have exactly known coordinates, so 4+ of them in one frame give
a 3×3 map from image pixels to court XZ; the player's foot pixel goes through
it every frame.

### New pieces

| Piece | What it does |
|---|---|
| `tools/calibrate_court.py` | Click (or pass) 4+ named court points on a frame → solves the homography → `data/calib/<clip>_court.json` + a **verification overlay PNG** (reprojected full court grid — must sit on the painted lines). Clicks auto-snap to detected line corners. `--list-points` names every usable intersection. |
| `extract_skeleton.py --court <calib.json>` | Also captures MediaPipe *image-space* landmarks; foot ground point = mean of visible heel/foot-tip landmarks (ankle fallback); projected through the homography → median filter (kills 1-frame glitches, e.g. a brief lock onto a bystander) → savgol smooth (~0.25 s) → clamp to court+1.5 m → writes `root_court_xz` [x,z] + `root_confidence` per frame, and a `court` block in the header. Without `--court` nothing changes (Phase 1 behavior). |
| `process_videos.py` | Auto-passes `data/calib/<name>_court.json` when it exists. |
| `SkeletonData.cs` | `SkeletonFrame.root_court_xz` / `root_confidence`; `doc.HasRoot`, `RootXZ(frame)`, `RootConf(frame)`. Old Phase-1 jsons (null root) still load fine. |
| `HumanoidPoseDriver.cs` | New "Root position (Phase 2)" inspector block: `driveRootPosition` (default on), `rootConfidenceCutoff` (0.2), `rootSmoothing` (0.2). If the clip has root data the avatar starts at the clip's first position and follows XZ each frame (spawn height preserved); low-confidence frames hold the last position. Clips without root data play in place exactly as before. |

### First real clip: `position_front.mp4` (23.6 s, 1080p60, static camera)

- Calibration: camera stands near the court's near-left corner (−X,−Z), whole
  court in view. 6 points used (`corner_fl/fr/nr`, `lsl_nl/nr`, `ssl_nl` —
  near-left corner is just off-frame, that's where the camera is). Worst
  reprojection residual **9 cm**, most ≤6 cm. Verified: overlay grid sits on
  the painted lines; predicted positions of *unused* junctions land within
  ~15 px of the real paint.
- Extraction: 1418/1418 frames pose detected, 1418 with a grounded foot;
  mean root confidence 0.92.
- Sanity checks that passed: back-projecting `root_court_xz` onto the video at
  t=1/6/12/18/22.5 s puts the marker on the player's feet; the walked path
  (`data/skeleton/position_front_path.png`) matches the video story (mid-court
  wander → behind the far baseline past the stage → back down the side
  corridor → ends 2–3 m in front of the camera). Frame-0 had a 1-frame wrong
  lock (bystander behind the glass doors) — that's why the median filter exists.
- `Assets/badminton.unity` now points `Player_Back`'s driver at
  `skeleton/position_front.json` with root driving on. **Next Unity open:
  press Play and watch the twin walk the court.**

### How to run Phase 2 on a new clip (static camera!)

```bash
# once per camera placement:
tools/.venv/Scripts/python tools/calibrate_court.py data/raw/<clip>.mp4
#   -> click the 4 corners, then CHECK data/calib/<clip>_overlay.png

# every clip from that placement:
tools/.venv/Scripts/python tools/process_videos.py <clip>
```

### Decisions & limits (why it is the way it is)

- "Distance to the corners" became a **homography**: with a flat floor and 4
  known points, one matrix does the whole job — no per-corner distances, no
  camera intrinsics, no depth model. Same idea scales to Phase 3 (PnP is the
  3D version of this calibration).
- **Feet, not hips:** one camera can only place points that are ON the floor.
  Heel/foot-tip landmarks are the ground contact; hips would project ~1 m off.
  Consequence: position is only exact while a foot is grounded — walking = fine,
  mid-jump = lands where the feet are (acceptable), dives/occluded feet = noise
  (confidence gate + clamp catch the worst).
- Lens is wide-FOV (visible barrel distortion at frame edges): handled by
  least-squares over 6 spread-out points, not by undistorting. Off-court
  positions (outside the calibrated rectangle) extrapolate and drift — hence
  the ±1.5 m clamp. Good enough for Phase 2; Phase 3's PnP + intrinsics will
  do it properly.
- Naming: calibration is looked up by clip name (`<clip>_court.json`). Shoot
  several clips from one placement → calibrate the first, copy/rename the
  calib file for the others (or pass `--court` explicitly).

## Phase 3+ (not started)

3. Two-camera OpenCap-style triangulation (accurate 3D pose+position; also the
   training-data rig) — cameras behind one baseline, ~6–7 m apart, ~65°
   crossing; court-corner PnP calibration; clap/flash time sync.
4. Fine-tune a badminton pose model (Colab/cloud GPU — this laptop has NO
   NVIDIA GPU) → ONNX.
5. Near-live: Python inference server → Unity Sentis.

---

## Append new entries below (newest first)

### 2026-07-14 (later) — REAL root cause found: the paint is a HALF court; recalibrated

User ground truth resolved it: the visible painted box is **one half of a
court only — the box between the short service line and the baseline** (plus
center line, long service line, singles/doubles alleys). There is no
net-to-SSL strip and no second half. The original calibration had stretched
the full 13.4 m court model over this ~4.7 m box, **rotated 90°** (what was
clicked as the "far baseline pair" is actually a doubles+singles SIDELINE
pair; the "right sideline corridor" is actually the LSL+baseline band). That
is why the walked path looked like a full-court loop when the player never
left one half.

How it was proven (all scripted, no clicking):
- Rectified the frame top-down through the old homography → the line pattern
  reads pair/single/pair across one axis (= sidelines + center line) and
  SSL / LSL+BL along the other — a half court on its side.
- Predicted all 17 half-court junctions from the measured lines, snapped 13
  in-frame ones to the paint (≤6 px moves), fit the homography **13-point
  overdetermined** (vs the old near-minimal 6): mean residual 13 cm, worst
  22 cm (motion-blurred far corner; wide-lens barrel distortion unmodeled).
- Discriminating test between "edge line = SSL" vs "= net": rendered where
  the SSL would fall under the net hypothesis — bare tile, no paint. The
  user's "between the short service line and baseline" is exactly right.
- The old "verified" near half was luck: 6 points ≈ minimal fit, residuals
  meaningless; the body-size check was fooled into a self-consistent
  wrong-scale solution near the camera.

New convention for half-court work: the tracked half is the **+Z half**
(net z=0 → baseline z=6.70); calibration uses the `_f`-named points
(`ssl_fl/fr`, `lsl_fl/fr`, `corner_fl/fr`, center-line junctions).
`calibrate_court.py --half far` draws a half-only overlay grid and records
`"half"` in the json. Old full-court calib kept as
`data/calib/position_front_court.WRONG-fullcourt.json.bak`.

Re-extracted `position_front.json` (auto-copied to StreamingAssets): the twin
now walks the +Z half of the Unity court. Verification (all passed):
- Apparent-body-size model refit over all 1418 frames: **median residual
  5.1%** and uniform across the box (old calib: far half +30–40%
  systematic). Camera ground position fits at (+5.5, −0.2) — off the box
  corner at net level, matching where the phone stood.
- Implied focal ≈1650 px → HFOV ≈61° → the clip was shot at **~1.0x with
  stabilization crop** (not 0.6x). Lens was never the problem; still use
  1.0x + high placement for future clips.
- Back-projection montage (`data/calib/position_front_backproj_check.png`):
  marker on the feet at t=1/5/9/13/17/21.5 s.
- Corrected path (`data/skeleton/position_front_path.png`): start mid-box →
  stage side → around the OUTSIDE of the baseline → back along the other
  sideline → ends near the SSL. X −3.6..+1.8, Z +2.6..+8.2 (a few frames
  clamped where he walked >1.5 m outside the calibrated box — extrapolated,
  expected).

### 2026-07-14 — position accuracy audit of position_front.mp4 (SUPERSEDED by the entry above — kept for the method)

User ground truth: the player only moved around ONE side of the court, but the
extracted path showed a loop over the FULL court (z up to +8.2). Forensics:

- **Near half (z < 0, camera side): verified accurate.** Three independent
  checks agree — overlay grid on the paint, back-projection lands on the feet,
  and an apparent-body-size model (camera ground position fitted at
  (−5.9, −7.6), i.e. off the near-left corner diagonal) predicts sizes within
  ±10%.
- **Far half: unreliable, systematically over-distanced ~30–40%.** The size
  model says the player was ~8.7–12 m away when the track claimed 12–15.7 m.
  MediaPipe IMAGE-mode can't even detect him there (person ~180 px tall);
  video-mode coasted. A 3× crop re-detection reproduced the same foot pixels,
  so the pose was consistent — the error is geometric, not landmark noise.
- **Root causes:** (1) camera too LOW (~1.6 m) and at a corner → at the far
  end 1 m of court ≈ 9 px of image; nothing measured there can be accurate.
  (2) The far-end anchor lines used in calibration (a dashed parallel pair)
  are plausibly NOT this court's baseline+long-service-line — the hall has
  multiple line sets, and from a low corner view a 0.46 m sideline pair of
  another marking ~9 m away is nearly indistinguishable from a 0.76 m back
  alley ~15 m away. `data/calib/position_front_check.png` (green = verified,
  red = suspect) was sent to the user for confirmation. An X-crossing at the
  assumed far-right corner (corners must be L-shaped) supports the suspicion.
- **NOT the cause:** training data (nothing is trained — MediaPipe is
  pretrained + pure geometry), line clarity (near-half residuals ≤9 cm), lens
  choice (effective FOV ≈ 50°, i.e. ~1.0x with stabilization crop — not 0.6x).

**Capture protocol for the next Phase-2 clip** (fixes both causes; matches
sports-vision practice — broadcast padel/tennis rigs are ~7.6 m high for
exactly this reason):

1. Scope = ONE half-court. Put the phone behind THAT half's baseline, centered
   on the center line, 2–4 m back.
2. As HIGH as possible: 2.5–3 m+ (balcony/stage/stand; even a 2 m shelf beats
   chest height). Height is the #1 accuracy lever.
3. 1.0x lens (never 0.6x), 4K if available, steady tripod/prop, EIS ideally
   off/locked. Whole half + ~1 m margin in frame; feet always visible.
4. Nobody else in frame (bystander caused the frame-0 glitch).
5. USER clicks the 4 corners of the half being used in calibrate_court.py
   (they know which paint belongs to the court — auto-guessing line identity
   in a multi-marking hall is what went wrong here). For a half-court, click
   corner_nl/corner_nr + the two net-line×sideline points (`net_l`, `net_r`).
6. Keep clips within the calibrated area; positions outside it extrapolate.

Software follow-ups identified (not yet integrated): crop-zoom second pose
pass at long range (validated, reproduces landmarks), body-size consistency
gate, court-ROI masking against bystanders.

*(2026-07-13 — Phase 2 built end-to-end on position_front.mp4; this file created.)*

## 2026-07-16 (later) — tidy-up, racket visual, debug HUD, repo goes public

- **`position_front` renamed `test_5` everywhere** (raw video, calib json +
  overlays + check images, skeleton json incl. internal `video_id`/`video`
  fields, StreamingAssets + .meta, code defaults). All clips now follow the
  `test_N` convention. Stale WRONG-fullcourt backups → `data/calib/archive/`.
- Research .md notes moved from the outer folder into `docs/for-claude/research-notes/`.
- **Video Compare fixed** (was invisible + MissingReferenceException):
  `SkeletonRenderer.Clear()` destroys all twin children on clip load, and the
  overlay canvas was parented under the twin. Canvas now lives at the scene
  root. Lesson generalized: **runtime helper objects must never be children of
  the twin.**
- **`RacketVisual`** (`Tools ▸ Badminton ▸ Racket ▸ Add To Twin`): orange
  arm-estimated racket (grip at right wrist, blade along elbow→wrist) on clips
  listed in `clipsWithRacket` (test_3/4/5). Baseline for the future detector.
- **`PipelineDebugHUD`** (`Tools ▸ Badminton ▸ Debug HUD ▸ Add To Twin`):
  joints tinted green→red by MediaPipe confidence, cyan court trail with red
  clamp-entry markers + magenta current-position puck, stats box (frame, root
  XZ, confidences, % in box, clamp count). H toggles at runtime.
- **Go-public prep**: README.md + MIT LICENSE added; `.gitignore` now excludes
  every frame-bearing image (`data/**/*.png`, `data/**/*.jpg`, `docs/img/`,
  `data/calib/archive/`) — code/JSON/docs only in the public repo.
- **AI roadmap** written to `docs/for-claude/ai-smoothing-plan.md`: measure → One-Euro +
  gap fill → Kalman + physics gating → temporal 3D lifting (Colab) → better
  backbone; racket detection path (zero-shot COCO → Roboflow/auto-label
  fine-tune → fuse with arm prior).

## 2026-07-17 — Track B: persistent twin driver (springs + IK + foot lock + lookahead)

Architecture shift (plan: `docs/for-claude/ai-smoothing-plan.md` Track B): the twin is no
longer teleported to raw MediaPipe data each frame — one persistent body moves
TOWARD each capture target.

- **`TwinDriver`** (`Tools ▸ Badminton ▸ Twin Driver ▸ Add To Twin`, on the
  SkeletonPlayback object): critically-damped springs on root + all 33 joints
  (halflife-tunable), analytic two-bone IK re-places elbows/knees so limb
  segments keep the clip's MEDIAN bone lengths (measured once per clip — no
  breathing limbs), foot locking pins a slow low foot until the captured foot
  moves `unlockDistance` away (kills ice-skating), and `lookaheadSeconds`
  peeks ahead in the recording to cancel spring lag (0 = causal, the Phase-5
  preview). Low-confidence frames stop moving the target and the spring holds
  — joints never pop in/out. **T toggles RAW vs DRIVEN live.**
- `SkeletonRenderer.ShowPoseWorld()` — world-space pose override for the
  stick figure (driver runs at execution order −10, after playback, before
  `RacketVisual`, which now follows the DRIVEN wrist when the driver is on).
- `HumanoidPoseDriver.poseSource` — the skinned avatar can follow the same
  driven pose (Add To Twin wires it automatically); its own Slerp smoothing
  is bypassed when driven. Both bodies switchable, per the design decision.
- VERIFIED 2026-07-17: Unity console clean (0 errors, 0 warnings) after the
  user opened the editor; user's verdict on the driven twin: "overall, from
  what i can see, it looks good."

## 2026-07-17 — Racket: wrist articulation + zero-shot detection works

**Racket no longer parallel to the arm** (user: "the racket shouldnt be force
to be parallel to the arm since the wrist can move it"). `RacketVisual` now
blends the forearm line toward the **wrist→knuckle-midpoint** direction using
MediaPipe hand landmarks 18/20 (right) or 17/19 (left) — they were already in
`skeleton.json`, just unused — and rolls the string bed with the palm normal
(cross product of the knuckle rays). `handInfluence` (0..1, default 0.85)
trades articulation against hand-landmark jitter; falls back to the forearm
line when hand confidence < cutoff. Validated in Unity (`Unity_ValidateScript`
standard: 0 errors).

**Zero-shot racket detection WORKS on our footage** — `tools/detect_racket.py`
(new). COCO "tennis racket" class 38, yolov8s, imgsz 1280, conf 0.10, every
15th frame, CPU:

| clip | sampled | with detection | hit rate | best conf |
|---|---|---|---|---|
| test_3 | 99 | 90 | **90.9%** | 0.91 |
| test_4 | 65 | 31 | 47.7% | 0.86 |
| test_5 | 95 | 61 | 64.2% | 0.92 |

Boxes verified by eye on the overlays: on the real racket, including a raised
mid-swing racket at 0.86 conf. Two caveats recorded in
`docs/for-claude/ai-smoothing-plan.md`: duplicate boxes on the same racket (~half of
hits — keep the best box nearest the wrist), and test_4's misses cluster on
the fast/blurred swing frames we care about most. **No own-data gathering or
fine-tune needed to start.** Outputs in `data/racket/` — detection JSON is
committed (boxes only), overlay frames gitignored per the privacy rule; model
weights (`*.pt`) gitignored.

**Research answer to "is there a study on this already?"** — yes:
[RacketVision](https://github.com/OrcustD/RacketVision) (AAAI 2026 Oral, MIT
licence): 1,672 clips / 435k frames of badminton+tennis+table-tennis with
**5 racket keypoints** (top/bottom/handle/left/right), pretrained checkpoints,
badminton configs, dataset on HF `linfeng302/RacketVision`. Queued as racket
Step D (Colab) — real racket orientation + roll, not just a box.

**`docs/for-claude/muscle-analysis-plan.md` (NEW, plan only)** — un-parks the injury
thread narrowly: kinematics + stroke segmentation → rule-based muscle
involvement highlight on the avatar → OpenSim inverse dynamics (Colab) → EMG
validation against MultiSenseBadminton (GIST/MIT, *Scientific Data* 2024:
23 h, 25 players, EMG + IMU + foot pressure). Staged by what each stage can
honestly claim; explicitly does NOT claim injury prediction. Three open
questions for the user at the end of that doc.

## 2026-07-17 — Move recognition v1: the twin now says WHAT it's doing

Spec `docs/superpowers/specs/2026-07-17-move-recognition-design.md` (PR #1),
Approach A landed end-to-end, TDD (19 pytest tests, `tools/tests/`):

- **`tools/label_moves.py`** — racket-wrist speed peaks (hip-centered
  landmarks → body-relative, locomotion can't fake a swing) mark strokes;
  segments tile every frame into stroke/moving/idle; transparent rules label
  strokes (`overhead_smash/overhead_clear/drop/underarm_lift/net_shot/drive`)
  with margin-based confidence. `--report` explains every label with its
  feature values; `--overlay` burns labels into a debug video
  (`data/moves/`, gitignored); `--write` bumps `schema_version` to **1.1**
  and inserts the `moves` block into BOTH json copies.
- **All five clips labeled + committed**: test_1 3 strokes, test_2 5,
  test_3 7, test_4 8, test_5 0 (correct — that's the walking/position clip;
  its only speed spike is the clip starting mid-motion at frame 0).
  Eyeball checks: test_3's strokes cluster in the 16–24 s swinging section
  (smashes on the fast overheads); overlay frame at 18.0 s shows
  `overhead_smash 0.60` with the racket in hand. smash↔clear / drop↔net
  confusion is allowed by spec — Approach B (classifier trained on
  VideoBadminton skeletons, Colab) is the designed fix behind the same
  contract.
- **Unity**: `SkeletonDoc` parses the optional `moves` block
  (`HasMoves`/`MoveAt` binary search; old files unaffected);
  **`MoveLabelHUD`** (`Tools ▸ Badminton ▸ Move Label ▸ Add To Twin`) shows
  the current label + confidence top-center and a colored segment timeline
  with playhead at the bottom. M toggles. Zero in-engine inference.
- Console clean after recompile (one unrelated transient WindowsVideoMedia
  flush error from VideoPlayer on test_5.mp4 during an earlier Play session).
- Plan-vs-reality notes: the plan's synthetic test helpers teleported the
  wrist (phantom 60 m/s spikes) — fixed to hold position; gentle-stroke
  tests use 3.8 m/s because 5-frame smoothing pulls 3.5 under the 3.0
  detection threshold. `data/moves/` added to .gitignore (was NOT covered).

## 2026-07-18 — Racket Step D prep: RacketVision run recipe (runner NOT built — user deferred)

User call: don't build the Colab runner yet; record the recipe so building it
is a one-session job later. From the [RacketVision repo](https://github.com/OrcustD/RacketVision)
README (verified 2026-07-18):

- **Environment** (pin-sensitive — expect the usual mm-stack friction on
  Colab): Python 3.10, torch 2.1.2 + cu121, `openmim`; then
  `mmcv >=2.0.0rc4,<2.2.0`, `mmdet >=3.0.0,<3.3.0`,
  `mmpose >=1.1.0 --no-deps`, `numpy >=1.23,<2`,
  `opencv-python <=4.10.0.84`, plus
  `albumentations json_tricks munkres xtcocotools pandas tqdm scikit-learn parse`.
- **Checkpoints**: from `source/`: `python download_checkpoints.py --module
  RacketPose` → weights land in `source/RacketPose/checkpoints/`.
- **Inference**: from `source/RacketPose/`: `python tools/inference.py
  --sport badminton --split test --device cuda`. Two-stage: RTMDet-M racket
  boxes → RTMPose-M **5 keypoints** (top/bottom/handle/left/right).
- **Input layout**: extracted JPG frames in their dataset structure
  (`source/data/badminton/<match>/<rally>/`, see
  `source/DataPreprocess/extract_frames.py`). **Output**:
  `source/data/badminton/pred_racket/<match>/<rally>/result.json`.
- **Adaptation the runner will need**: our clip → fake `<match>/<rally>`
  frame dir → their inference → convert `result.json` →
  `data/racket/<clip>_rvision.json` (per-frame 5 keypoints in pixels +
  conf, same folder convention as the zero-shot probe). Clips reach Colab
  via Drive — never through the public repo (privacy rule). When this
  lands, Step C fusion consumes these keypoints instead of the COCO box
  (real orientation + roll, per `docs/for-claude/ai-smoothing-plan.md` Step D).

## 2026-07-23 — December re-plan + docs reorg

Project reframed into a collaborative deliverable with an early-Dec-2026 target.
Forward plan now lives in `docs/for-me/DECEMBER-PLAN.md` (this session).
Delivered: research brief (`docs/for-me/RESEARCH-BRIEF.pdf`), reframed roadmap board
+ weekly timeline (`docs/for-me/ROADMAP-BOARD.html`, `docs/for-me/TIMELINE-DEC.html`),
`docs/for-me/TODO.md`. **Pose-engine pivot to OpenCap** (biomech-grade video→OpenSim
kinematics); this lane owns skeleton + twin + accuracy, other lanes own the stroke AI
and muscle/injury. Validation = MultiSenseBadminton (public) → prof's 16 sensors later.

**docs/ reorganized by audience** (remap for older entries above):
`docs/PROGRESS.md`→`docs/for-claude/PROGRESS.md`; `docs/DOCUMENTARY.md`→`docs/for-me/`;
`docs/{ai-smoothing,muscle-analysis}-plan.md`→`docs/for-claude/`; `docs/research/*.md`
→`docs/for-claude/research-notes/` (badminton_camera_research.md→camera-research.md);
explainer/roadmap/etc PDFs→`docs/for-me/guides/`; ARCHITECTURE/ROADMAP-BOARD/TIMELINE
→`docs/for-me/`. `docs/superpowers/` unchanged (skill convention). `docs/img/` unchanged.

## 2026-07-23 — Monocular SMPL skeleton (skeleton.json v2)

Built the SMPL-24 pose path (spec: `docs/superpowers/specs/2026-07-23-monocular-smpl-skeleton-design.md`,
plan: `docs/superpowers/plans/2026-07-23-monocular-smpl-skeleton.md`).
- `tools/smpl_to_skeleton.py` — WHAM SMPL → `skeleton.json v2` (SMPL-24 + spine, `parents`, `betas`, `smpl` block). GPU-free; `--synthetic` demo generator. Tests in `tools/tests/`.
- `tools/eval_pose.py` — MPJPE / PA-MPJPE vs SMPL GT (EMDB/3DPW).
- `tools/colab/wham_extract.ipynb` — WHAM on Colab → normalized `.npz`.
- `Assets/Scripts/SkeletonPlayer/SmplSkeletonData.cs` + `SmplSkeletonDriver.cs` — procedural 24-joint twin with the spine chain; reads v2 from StreamingAssets.
- Schema v2 is producer-agnostic → multi-view triangulation can write the same file later.
Run tests: `./tools/.venv/Scripts/python.exe -m pytest tools/tests -v`.

## 2026-07-24 — SMPL models staged; pose-engine pivot WHAM→ROMP; Route A (Blender mesh)

- **SMPL models organized** (gitignored — license-gated, public repo): `models/smpl/`
  holds `SMPL_NEUTRAL.pkl` (+ MALE/FEMALE), renamed to the `smplx` convention;
  reference/archives in `models/smpl-reference/`. `.gitignore` now ignores `models/` +
  `downloads/`. Test clip = `data/raw/test_6.mp4` (Pexels person, general pose — not badminton).
- **Architecture pivot (Route A):** Blender authors the model, Unity views it. Video →
  SMPL params → **SMPL Blender add-on animates a body mesh** → **FBX** → Unity court.
  This replaces the procedural Unity stick-skeleton (`SmplSkeletonDriver`) with a real mesh;
  keeps `eval_pose`. Blender↔Unity link = FBX/glTF asset pipeline (auto-reimport).
- **Pose engine WHAM → ROMP.** WHAM's repo has no `install.sh` and its real Colab setup
  (conda + compiled SLAM + checkpoint scripts) is unworkable there. Switched
  `tools/colab/wham_extract.ipynb` to **ROMP** (`simple_romp`, pip): same SMPL-param npz
  contract (`joints3d`/`pose`/`betas`/`transl`/`fps`), so `smpl_to_skeleton.py` + Blender
  + eval are unchanged. WHAM / 4D-Humans kept as later quality upgrades. Notebook downscales
  4K→720p. **chumpy gotcha:** the official SMPL pkl is chumpy-pickled and chumpy is broken on
  Colab Py3.12 — the notebook patches `np` aliases + `inspect.getargspec`, de-chumpifies to a
  clean pkl (also downloaded for reuse), then converts. Notebook still named `wham_extract.ipynb`
  (historical) — rename + commit pending a confirmed green run.

## 2026-07-24 (cont.) — Route A PROVEN end-to-end + Blender comparison viewer

**Pipeline works:** `test_6.mp4` → ROMP on Colab → `test_6.smpl.npz` (189 frames, 25 fps) →
`smpl_to_skeleton.py` → `data/skeleton/test_6.skeleton.json` → Blender animated body →
`models/smpl/test_6_twin.fbx` (Unity-ready) + `test_6_twin.blend`.

- **Colab (ROMP):** the notebook now works; ROMP writes SMPL params (θ/betas/cam_trans) but NO
  3D joints and saves a combined `out_romp/video_results.npz` keyed by frame — Cell 4 rewritten
  to read that and **regress the 24 joints via `smplx`** from the de-chumpified clean pkl.
- **Coordinate fix:** real data showed the twin **upside-down** — `WORLD_TO_UNITY` was flipping Z;
  corrected to a **Y-flip `diag(1,-1,1)`** (ROMP is vision-camera Y-down → Unity Y-up; single flip
  also fixes handedness). Verified upright (+1.38 m stature). Two tests updated; **36/36 pass**.
- **Blender (Route A):** SMPL add-on (`smpl_blender_addon`) installs+enables on **Blender 5.2**;
  `scene.smpl_add_gender` (male; no neutral, θ is gender-agnostic), betas → mesh `Shape000..009`,
  24 bones Pelvis…R_Hand. **Pose convention solved:** body-pose joints applied directly; **pelvis =
  `Rx(180°) @ quat(global_orient)`** (verified upright/natural frames 0/60/120/188). Baked 189
  frames, exported via `bpy.ops.object.smpl_export_unity_fbx` (writes the FBX then throws a cosmetic
  `skinned_mesh_original removed` error on 5.2 + renames objects `.001` — ignore).
- **Comparison viewer BUILT in Blender** (platform switched Unity→Blender): `models/smpl/test_6_compare.blend`.
  Two bodies side by side (raw | smooth), custom N-panel **"Twin Compare"** (persisted as text-block
  `twin_compare.py`, re-run on reopen) with per-body toggles: Style raw⟷smooth (swaps Action) +
  Skeleton + Mesh (= 3 modes × 2 styles). Smoothing = critically-damped **SmoothDamp spring (0.12 s) →
  −85% angular jitter**, baked as `act_smooth`. Skeleton = armature `display_type='STICK'` +
  `show_in_front` (bones are viewport-only — never in a camera render; verify with `render.opengl`).
- **Artifacts gitignored** (`models/**`): `test_6.smpl.npz`, `SMPL_NEUTRAL_clean.pkl`, `test_6_twin.fbx`,
  `test_6_twin.blend`, `test_6_compare.blend`.
- **⚠ Uncommitted** on branch `feat/smpl-skeleton-v2` (local): the ROMP notebook, `WORLD_TO_UNITY`
  fix + tests, and doc syncs (this file, README, design §10/§11, ARCHITECTURE). Deferred refactors to
  fold into the batch commit: rename `wham_extract.ipynb`→`pose_extract.ipynb`, add `--smpl-npz` flag
  alias to `smpl_to_skeleton.py`. Commit when asked.

## 2026-07-24 (cont.) — Joint spheres + vision-racket (RacketVision) kickoff

- **Fact correction:** `data/raw/test_6.mp4` is a **badminton** clip (female player on a red court,
  **racket in right hand** pointing down at rest, **shuttlecock in left hand** + another on court, net;
  4K 3840×2160 @25fps). Earlier notes calling it a generic person clip were wrong. So test_6 supports
  vision-racket + shuttle work, not just body pose. (Verified by extracting a frame with ffmpeg.)
- **Joint spheres DONE (renderable skeleton):** the stick armature is viewport-only (never renders), so
  added **24 icospheres per body** in the compare scene — one per SMPL bone, positioned by a
  `COPY_LOCATION` constraint (`head_tail=0` → posed bone head = joint), so they follow the animation AND
  appear in a camera render. Collections `A_joints_left` (orange = raw) / `B_joints_right` (green = smooth),
  hidden by default, wired to a new per-body **Joints** toggle (panel now Skeleton + Mesh + Joints).
  Verified in a real render (spheres show; bones don't). Radius 0.032 m, icosphere subdiv 2, smooth-shaded.
- **Viewer script is now a durable repo file** `tools/blender/twin_compare.py` (was trapped only in the
  `.blend` text-block). Idempotent: run in Blender → rebuilds spheres + registers the panel. `.blend` saved.
- **Vision racket — decided: full RacketVision pipeline (Colab, 5-keypoint).** RacketVision (AAAI'26, MIT):
  two-stage RTMDet→RTMPose, **2D** keypoints `top`/`bottom`/`handle`/`left`/`right`, pretrained checkpoints
  on HF `linfeng302/RacketVision-Models`. Per-keypoint acc (badminton): top 99.4 / bottom 99.7 / handle 97.3 /
  left 74.6 / right 75.5 (sides occluded by hand) → the long axis is reliable, face-roll is noisy.
- **Stage-1 notebook built:** `tools/colab/racketvision_extract.ipynb` (10 cells). Runs a standalone
  top-down loop (their configs + checkpoints — NOT their match/rally/split dataset pipeline), self-discovers
  config/ckpt paths, prints the real keypoint order, downscales test_6 4K→1080p, emits `test_6.racket2d.json`
  + overlay video. OpenMMLab install (mmcv/mmdet/mmpose, py3.10/torch2.1.2 pins vs Colab) is the expected
  iterate point. **Stage 2** (lift 2D→3D at SMPL hand → grip idx24/head idx25 → append skeleton.json) and
  **Stage 3** (racket on the twin) come after we see real 2D output. detect_racket.py (COCO) left as the fallback.
- **Not committed** (add to the pending batch): `tools/blender/twin_compare.py`,
  `tools/colab/racketvision_extract.ipynb`, this entry, TODO update.
- **Colab debug round 1 (notebook v2):** first run surfaced the real facts —
  (a) **keypoint order confirmed** from repo `configs/_base_/datasets/racket_pose.py`:
  `0=top, 1=bottom, 2=handle, 3=left, 4=right` (long axis = handle→top; sigmas show left/right are the
  hard ones); (b) real inference configs are `RacketPose/configs/{detection/rtmdet_m_racket_infer.py,
  pose/rtmpose_m_racket_infer.py}` (my glob wrongly grabbed `_base_/models/*`); (c) the RTMDet detector is
  **3-class, badminton = label 0** (must filter, plus their bbox-area<0.5 guard) — from repo `tools/inference.py`,
  which uses `init_detector`+`init_model`+`inference_topdown`; (d) checkpoints download fine via
  `download_checkpoints.py --module RacketPose` (epoch_300.pth = det, best_PCK_epoch_90.pth = pose).
  **Env is the pain:** Colab = Python 3.12 + torch 2.11 (no OpenMMLab wheels); `mim` breaks on 3.12
  (stale setuptools → `pkgutil.ImpImporter`). v2 recipe: modern setuptools → **pin torch 2.3.1+cu121** →
  mmcv 2.2.0 from the openmmlab torch2.3.0 wheel index → **mmdet 3.3.0 + mmpose 1.3.2 `--no-deps`** (+ only the
  top-down runtime deps) so they don't fight over mmcv. GPU runtime required. detect_racket.py (COCO) is the fallback.
- **Colab debug round 2 (notebook v3, 11 cells):** GPU T4 up, Cell 3/4 clean (configs OK, 189 frames = test_6 is
  189f @25fps). New blocker: `mmdet`/`mmpose` **hard-assert `mmcv < 2.2.0`**, but py3.12 has NO prebuilt mmcv<2.2
  (those stop at cp311/torch2.1). Fix = **Cell 2b patch**: `importlib.util.find_spec(name).origin` to locate
  mmdet/mmpose `__init__.py` WITHOUT importing, then regex-bump `mmcv_maximum_version 2.2.0→2.3.0` (+ mmpose
  `mmdet_maximum_version 3.3.0→3.4.0`). mmcv 2.2.0 runs fine with mmdet 3.3.0 for inference; the assert is just
  conservative. After the patch, Cell 5 builds both models.
- **Colab debug round 3 (numpy):** Cell 5 then hit `cannot import name '_center' from numpy._core.umath` —
  a later `pip install` had bounced numpy back to 2.x, but mmcv 2.2.0's compiled ops need **numpy<2** and
  Colab's default scipy/opencv are built for numpy 2. Fix: end Cell 2 with
  `pip install --no-deps --force-reinstall numpy==1.26.4 scipy==1.12.0 opencv-python==4.10.0.84` (LAST, so
  nothing re-upgrades numpy), then **Runtime>Restart session** to clear the half-loaded numpy, then run Cells 3–8
  (installs + /content + the on-disk mmdet patch all persist across a session restart).
- **Colab debug round 4 (xtcocotools):** numpy fix worked (torch 2.3.1 confirmed, mmdet imports clean), then
  `ModuleNotFoundError: xtcocotools` — mmpose imports its COCO dataset classes at load time. Fix (Cell 2 step 6):
  `pip install cython>=0.29` then `pip install --no-deps --no-build-isolation xtcocotools` (build against the
  pinned numpy 1.26 so it doesn't drag numpy 2 back). munkres also added preemptively. Env recipe now complete
  in the notebook; expected next: Cell 5 prints keypoint order, Cell 6 the hit-rate.
- **Colab debug round 5 (xtcocotools STUB):** xtcocotools 1.14.3 sdist **won't build on py3.12**
  (`metadata-generation-failed`). Solution: **don't install it — stub it.** mmpose imports
  `from xtcocotools.coco import COCO` at load time (via BaseCocoStyleDataset), but top-down inference never
  builds a COCO dataset, so only the importable NAME is needed. Cell 5 now registers a fake `xtcocotools`
  (coco.COCO, cocoeval.COCOeval, mask.*) in `sys.modules` before importing mmpose. Keypoint order/meta comes
  from the pose config's inline `dataset_info` (parse_pose_metainfo), NOT xtcocotools, so inference is unaffected.
  **This should be the final env fix — the whole import chain is now satisfied.**
- **Colab debug round 6 (registry scope):** stub worked, then `AssertionError: scope mmpose exists in runner
  registry` — the interactive stub snippet I handed over purged `mmpose` from `sys.modules` but NOT `mmengine`,
  so Cell 5 re-registered the `mmpose` scope in mmengine's still-alive global registry. **Not a code bug** —
  fix is a clean **Runtime>Restart session**, then run Cells 3–8 once in order (mmpose imports exactly once).
  The **repo notebook's baked-in Cell 5 stub has NO purge loop**, so a fresh run never hits this. Env recipe
  is fully settled; awaiting the first real 2D output (keypoint order + hit-rate + overlay).
- **Colab debug rounds 7–8 (munkres + pkgutil):** after restart, `No module named 'munkres'` (mmpose imports
  it in codecs/associative_embedding at load) → `pip install munkres` (pure-python, was in Cell 2 but got
  aborted alongside the failed xtcocotools line). Then `AttributeError: module 'pkgutil' has no attribute
  'ImpImporter'` — mmpose.apis pulls in an old `pkg_resources` (via MMPoseInferencer→get_installed_path) that
  references `pkgutil.ImpImporter`, removed in py3.12. Fix (baked into Cell 5, before the mmpose import):
  `if not hasattr(pkgutil,'ImpImporter'): pkgutil.ImpImporter = type('ImpImporter',(),{})` (dummy class, only
  used as a finder dict-key that never runs). **The full env recipe is now: torch2.3.1 + mmcv2.2.0 +
  mmdet/mmpose --no-deps + mmcv-ceiling patch + numpy1.26/scipy1.12/opencv4.10 pin + munkres + xtcocotools
  stub + pkgutil.ImpImporter shim.** All baked into the notebook (Cell 2/2b/5). Awaiting first 2D output.
- **Colab debug round 9 (numpy ABI):** Colab VM recycled overnight (all installs + /content wiped — re-run
  needed). Fresh top-to-bottom run got past ALL import fixes, then `ValueError: numpy.dtype size changed,
  Expected 96 from C header, got 88 from PyObject` during torch import → **mixed numpy install**: an in-place
  downgrade to 1.26.4 left orphaned numpy-2.0 `.so` files (numpy 2.0 reorganized `core`→`_core`), so the py
  side is 1.x (88) but a compiled `.so` is 2.0 (96). Fix (Cell 2 step 5, hardened): `pip uninstall -y numpy` +
  `rm -rf .../dist-packages/numpy*` + `pip install --no-cache-dir numpy==1.26.4 scipy==1.12.0 opencv-python==4.10.0.84`.
  **Lesson: the whole OpenMMLab-on-Colab stack is fragile enough that once we get one clean 2D output, cache the
  built env / frames to Drive so we don't re-run this gauntlet after every VM recycle.**
- **Colab debug round 10 (FileFinder.find_module — likely the LAST env fix):** numpy ABI fix confirmed working
  — a clean run got *all the way through* torch + mmdet + the xtcocotools stub, then failed on the mmpose import
  with `AttributeError: 'FileFinder' object has no attribute 'find_module'`. Cause: `mmpose.apis` builds its
  inferencer registry, which calls `mmengine ... get_installed_path('mmpose')`, which imports **setuptools'
  `pkg_resources`**; on first import pkg_resources scans installed dists and runs `declare_namespace('google')`
  (Colab's `google` is a namespace pkg), whose legacy `_handle_ns` falls back to `importer.find_module(...)` —
  a method **py3.12 removed from `FileFinder`**. So it's setuptools' ancient namespace shim dying on 3.12, not
  mmpose's pose code. Fix (baked into Cell 5, before the mmpose import): restore a compatible method —
  `if not hasattr(importlib.machinery.FileFinder,'find_module'): FileFinder.find_module = lambda self,name,path=None: (s.loader if (s:=self.find_spec(name)) else None)`.
  Also added **Cell 2c "DEBUG PROBE"** (per user request for a pinpoint cell): self-contained, applies the same
  shims, then imports numpy/torch/mmcv/mmengine/mmdet/mmpose one at a time printing PASS/FAIL + a 2-line trace,
  so the exact culprit is named without a full Cell-3→5 re-run. **Full env recipe now: torch2.3.1 + mmcv2.2.0 +
  mmdet/mmpose --no-deps + mmcv-ceiling patch + numpy-nuke→1.26.4/scipy1.12/opencv4.10 + munkres + xtcocotools
  stub + pkgutil.ImpImporter shim + FileFinder.find_module shim.**
- **Colab debug round 11 (numpy pin wasn't STICKING — the debug probe paid off):** the FileFinder shim worked;
  a clean run got past every import shim, and **Cell 2c pinpointed the real culprit exactly**: `numpy 2.0.2`
  loaded at model-build time even though Cell 2 ended with "Successfully installed numpy-1.26.4". So numpy was
  being **bounced back to 2.x** between the pin and the import (a re-pull and/or a mixed/shadow install), and
  mmcv/mmdet's numpy-1.x-compiled ops then died on `numpy.dtype size changed, Expected 96 got 88`. Root cause of
  the whole multi-round numpy saga: downgrading numpy **last, in the same kernel, with no hard restart** — fragile.
  **Real fix (Cell 2 rebuilt):** (1) a pip **constraints file** `numpy==1.26.4` passed via `{C}` to EVERY install
  so nothing can bounce numpy; (2) install a **clean numpy 1.26.4 FIRST** (`--force-reinstall --no-deps` + rm incl.
  `numpy.libs`) so every compiled pkg agrees on it; (3) **auto-restart the kernel** at the end of Cell 2
  (`IPython...kernel.do_shutdown(True)`) so the clean numpy actually loads. Also **folded the mmcv-ceiling patch
  into Cell 2** (removed standalone Cell 2b) and **hardened Cell 2c**: it now prints `numpy.__version__ @ __file__`
  and hard-asserts 1.26.4 (a wrong path ⇒ shadow install). Added a numpy-version **guard at the top of Cell 5**
  (fail-fast with a clear "run Cell 2 + restart" message instead of a cryptic ABI crash). New run order:
  **1 → 2 (installs+patch+auto-restart) → 2c (verify) → 3-8**. **Lesson: for a numpy downgrade on Colab, a
  constraints file + a kernel restart are mandatory — an in-kernel last-step pin does not hold.**

## 2026-07-25 — Colab round 12: numpy was a FALSE ALARM; the real blocker was `transformers`

**The import gauntlet is over — every module now imports and both models are one cell away.**

- **Correction to round 11.** Round 11 concluded numpy was "being bounced back to 2.x" and I
  hypothesised Colab was *restoring* its preinstalled numpy at kernel start. **Both were wrong.**
  A forensics cell settled it: the on-disk numpy dir was written at 00:03:28 (Cell 2's install)
  and **never touched again** — `numpy-1.26.4.dist-info`, one copy, no shadow install, mtime
  well *before* the 00:07:38 restart. What actually happened: the `numpy: 2.0.2` line came from a
  kernel that had **already imported numpy 2.x at startup** (Colab does, before Cell 2 replaces it
  on disk) — i.e. a stale pre-restart execution, not a disk state. The constraints file + numpy-first
  + auto-restart from round 11 were correct and are kept; the *diagnosis* of why they were needed
  was not. **Lesson: `numpy.__version__` in a kernel that ran the installer is not evidence about
  the disk — check on-disk state from a fresh subprocess, and check the dir mtime before blaming
  the platform.**
- **Cell 2c rewritten to REPAIR, not abort.** It now pip-force-reinstalls 1.26.4, drops
  `numpy*` from `sys.modules`, and re-imports — so a stale kernel fixes itself with no second
  restart (safe because mmcv/mmdet/mmpose have not been imported yet at that point). It also
  reports in-kernel vs on-disk numpy, flags a second `dist-info`, and warns if `transformers`
  is still installed. The old `raise SystemExit` version just dead-ended the run.
- **REAL blocker found — `transformers`.** With numpy correct, all three probes PASS, Cell 3
  (checkpoints) and Cell 4 (189 frames) are clean, and Cell 5 reaches `torch: 2.3.1+cu121 | cuda? True`
  — then `init_detector` dies with **`NameError: name 'nn' is not defined`** raised from
  `transformers/integrations/accelerate.py`. Chain: `MODELS.build` → `mmdet.models` → its
  GLIP/Grounding-DINO **language models** → `import transformers`; Colab's transformers requires
  **torch >= 2.4**, so on our pinned torch 2.3.1 it prints "Disabling PyTorch ... found 2.3.1" and
  then a module annotated with `nn.Module` explodes. It is a `NameError`, so mmdet's
  `except ImportError` around that import **cannot catch it**. **Fix (Cell 2 step 4b):
  `pip uninstall -y transformers`** — RTMDet is pure CNN and needs none of it; absent, mmdet just
  warns. Documented fallback if something else ever needs it: `transformers==4.44.2` (last
  torch-2.3-compatible line).
- **Notebook v3 (`tools/colab/racketvision_extract.ipynb`, 11 cells)** — validated, all checks pass:
  - Cell 2: `+ pip uninstall -y transformers`; restart comment now states the real reason (the
    kernel imported numpy 2.x at startup, so only a fresh kernel can load 1.26.4).
  - Cell 2c: verify → **auto-repair** → probe (above).
  - **Cell 4: `ffprobe`s the source** for real fps + resolution instead of the hardcoded `FPS = 25`,
    exports `SRC_W`/`SRC_H`, and asserts frames were actually extracted.
  - **Cell 6: geometry is now part of the JSON contract** — `frame_size` (the 1080p frame the model
    ran on) + `source_size` + the `det` settings. Without these, Stage 2 cannot line 1080p racket
    pixels up with an SMPL body that came from a **720p** pass of the same clip. This was a real gap.
  - **Cell 7: cast keypoints to python `int`** — OpenCV ≥4.6 rejects `np.int64` in point tuples
    (`Can't parse 'pt1'`), so the overlay would have crashed on the first detected frame. Also
    stamps the detection score on the frame.
- **Docs synced:** `tools/colab/README.md` now covers **both** notebooks (table + a full RacketVision
  section: keypoint order/reliability, run order, output contract, the whole env recipe and its two
  traps); `tools/README.md` gained the Blender Route-A viewer and racket sections and stopped
  claiming WHAM; `CLAUDE.md` Phase 2.5 marks Step C shelved and Step D active; `TODO.md` Stage 1
  status + a code-review follow-up block.

### Code review of the video-to-twin work so far (2026-07-25)

Scope: `tools/smpl_to_skeleton.py`, `tools/blender/twin_compare.py`, both Colab notebooks, tests.
**Tests: 36/36 pass.** No blocking defects. Fixed in this pass: the Cell 7 `np.int64` crash, the
missing frame/source geometry in `racket2d.json`, the hardcoded 25 fps, and the dead-end Cell 2c.
Open findings, none blocking (also mirrored into `TODO.md`):

1. **Mixed coordinate frames inside one document (highest-value finding).** `build_v2_document`
   applies `WORLD_TO_UNITY` to `joints3d` and to `transl`, but writes `smpl.global_orient`
   **unchanged** — so within a single frame object, `joints_flat` / `root_world` / `smpl.transl`
   are Unity-frame while `smpl.global_orient` is still ROMP camera-frame. Nothing is broken today
   only because the Blender path re-derives the pelvis as `Rx(180°) @ quat(global_orient)` and
   ignores the joints. A future consumer that trusts the `smpl` block as a unit will be wrong.
   Fix = transform it or state the split loudly in the schema doc.
2. **Silent data loss.** `betas` is truncated to the first 10 values with no warning, and a missing
   `fps` key silently becomes 30.0 — which would quietly desync every `time` field. Both should warn.
3. **Test gap.** `load_wham_output` is tested in isolation, but no test drives `main()` through
   `--wham-output` to a written file, so an argparse/wiring regression would ship green.
4. **Naming drift, accepted.** `wham_extract.ipynb` runs ROMP and `--wham-output` reads any
   conforming npz. Renaming is still open, but the READMEs now say so explicitly, so this is
   cosmetic rather than misleading.
5. **`twin_compare.py` — clean.** Idempotent, documents its scene contract, degrades safely
   (`_joint_objs` handles a missing collection). Two notes: `_bodies()` will `StopIteration` if a
   body collection loses its armature/mesh, and `register()` swallows every exception, so a genuine
   registration error looks like success. Acceptable for a Blender-side tool; worth knowing.
6. **Operational.** The Colab env takes ~5 min to rebuild and Colab wipes the VM after a few idle
   hours — cache the built env + extracted frames to Drive before the next VM recycle.

---

## 2026-07-25 — Stage 1 RUNS: first real racket 2D output (and the detector is the weak link)

The RacketVision notebook completed end to end for the first time. Artifacts landed in
`data/racket/`: **`test_6.racket2d.json`** (189 frames) + `test_6_racket_overlay.mp4`.
The v3 contract held — `frame_size [1920,1080]`, `source_size [3840,2160]`, `fps 25.0`
(ffprobed from the 4K source), `keypoint_names ['top','bottom','handle','left','right']`.

### The number: 16/189 frames = 8.5% hit rate

Detections clustered in four short bursts (frame 4; 65–68; 92–94; 101–117) with `det_score`
between 0.31 and 0.85 — everything else `keypoints: null`.

### But the pose head is excellent — it's RTMDet recall that fails

Pulled frames out of the overlay and looked at them. This is the finding that shapes Stage 1b:

- **frame 105, `det = 0.31`** — overhead smash, racket up and slightly behind the head. The
  five keypoints are *dead on*: `top` at the tip, `left`/`right` across the head rim, `handle`
  at the grip in her hand. A 0.31-score box gave a textbook fit.
- **frame 66, `det = 0.74`** — racket held out horizontally against a bright wall. Shaft line
  runs exactly along the shaft.
- **frame 30 — missed.** Racket plainly visible, hanging down-left from her hand, dark shaft
  against the dark red court.
- **frame 150 — missed.** Racket head face-on, overlapping her torso.

So the misses are ordinary badminton poses (low contrast against the floor, or head-on over
the body), and the model *when it fires* is accurate even at the threshold floor. Conclusion:
**the useful detector signal lives below `DET_THR = 0.30`**, and we were throwing it away.

### Notebook v4 — recall first, decide later

1. **`DET_THR` 0.30 → 0.05.** Be permissive at inference; filter on `det_score` /
   `keypoint_scores` downstream where it's free to re-tune.
2. **Keep the top 3 boxes per frame, with keypoints for each** (`frames[i].cands`, best first).
   RTMPose is cheap; a second Colab round-trip is not. Picking the right box is a temporal-
   continuity problem, and now it can be solved by a local script instead of a re-run.
   The flat `bbox`/`det_score`/`keypoints`/`keypoint_scores` stay = `cands[0]` (v3-compatible).
3. **Cell 6 prints a `det >= x` table** (0.05/0.10/0.20/0.30/0.50) so the next run tells us
   empirically where to cut instead of guessing again.
4. **Overlay draws the runner-up boxes** in thin gray with their scores, and stamps
   `no racket` on empty frames — a wrong pick is now visible rather than silently authoritative.

Re-running only needs Cells 6–8 on a warm VM; the models are already built.

### Privacy-rule gap found and closed

`.gitignore` covered `data/**/*.png|jpg` but **not video**, so the new
`data/racket/test_6_racket_overlay.mp4` — 3.8 MB of frames of a person — was committable on a
public repo. Added `data/**/*.mp4` + `data/**/*.mov`. (`data/raw/` and `data/moves/` were
already covered wholesale; this catches debug renders in any other `data/<tool>/` dir.)
`test_6.racket2d.json` stays tracked — it's coordinates, not imagery.

---

## 2026-07-25 — v4 run: 8.5% → 44%, and the lesson that detector score is not confidence

The v4 notebook (`DET_THR=0.05`, top-3 boxes per frame with keypoints for each) re-ran on
the warm VM. `data/racket/test_6.racket2d.json` is now 186 KB with a `cands` list per frame.

### The raw numbers

| gate | frames with a top-1 pick |
|---|---|
| `det >= 0.05` | 138/189 (73%) |
| `det >= 0.10` |  64/189 (34%) |
| `det >= 0.20` |  27/189 (14%) |
| `det >= 0.30` |  16/189 (8%)  ← v3 |

Candidates per frame: 0 → 51 frames, 1 → 62, 2 → 38, 3 → 38.

But 73% was not real coverage: 16 of 123 adjacent-frame pairs jumped >250 px, nearly all at
`det < 0.10`. Frame 30 at `det = 0.06` put the box on the far right edge — a net-post
artifact — while the racket in her hand went unfound.

### The finding: rank by KEYPOINT score, not detector score

Comparing candidates on known-good frames made it obvious:

| | det_score | mean kp score |
|---|---|---|
| fr66 real racket | 0.74 | **0.68** |
| fr105 real racket (overhead) | 0.31 | **0.70** |
| fr60 real racket, **rank 1** | **0.08** | **0.73** |
| fr126 real racket | 0.17 | **0.71** |
| fr30 net-post artifact | 0.06 | 0.11 |
| fr66 rank-1 artifact | 0.07 | 0.13 |

RTMPose cannot find a shaft and a head in something that is not a racket, so its scores
separate cleanly at ~0.5 where the detector's do not separate at all. Rendered fr60 and
fr126 from the source to confirm by eye: both are textbook fits the detector score would
have discarded. **Re-ranking changes the pick in 22 frames**, and 9 of the final picks are
runner-up boxes — exactly what keeping top-K was for.

### `tools/select_racket_track.py` (new)

Turns the candidate soup into one series, `<id>.rackettrack.json`, per frame labelled
`detected` / `interpolated` / `missing`:

1. **Anchors** — best-by-keypoint-score if `>= 0.50`. No neighbour dependence, so a bad
   frame cannot drag the track.
2. **Outlier rejection** — drop a pick >250 px from *every* anchor within ±2 frames. Anchors
   with no neighbours at all survive: absence of corroboration is not evidence against.
3. **Continuity recovery** — for empty frames, accept down to `0.35` if near an accepted
   neighbour **and** the grip-to-tip length is within 2× of it. That length guard came
   straight from a bug: frames 57–58 were admitted at kp 0.45 with the keypoints bunched on
   the grip and the head never found, giving a 68 px shaft beside a 200 px one. Rendering
   fr58 showed it; the guard removed both and lifted min shaft length to a plausible 129 px.
4. **Interpolation** — linear fill of bracketed gaps ≤4 frames. Never extrapolates past the
   end of a run: there is no evidence out there, and invented points would be
   indistinguishable from measured ones downstream.

Result on test_6: **76 detected + 7 interpolated = 83/189 (44%)**, zero >250 px jumps,
shaft length min 129 / median 222 / max 336 px. Covered runs 0–18, 57–84, 92–95, 101–131,
144–146 — i.e. **the two swings**, which is the part Stage 2 actually needs.

`--overlay` renders the track over the source clip with interpolated frames dimmed.
17 new tests (56 total, all passing), including the end-to-end CLI path that the
2026-07-25 code review flagged as missing for `smpl_to_skeleton.py`.

### What is still missing, and the one idea worth a Colab run

Of the 106 uncovered frames, **50 produced no candidate at all** even at 0.05, and the rest
peaked at a median kp score of 0.16 — so the gate is not being over-strict, the detector
genuinely does not see these. The two failure modes are the racket hanging down against the
dark red floor, and the head face-on overlapping the torso.

The promising fix is **crop-and-upscale around the hand**: `test_6.skeleton.json` gives the
SMPL hand position for every frame, so we can crop a box around it, upscale, and run RTMDet
on that — this is a small-object recall problem. Worth doing only if 44% proves insufficient
once the racket is on the twin.

### Privacy

`data/racket/test_6.rackettrack_overlay.mp4` is covered by the `data/**/*.mp4` rule added
earlier today. `.racket2d.json` and `.rackettrack.json` are coordinates and stay tracked.

---

## 2026-07-25 — Stage 2 DONE: the racket is 3D and on the skeleton

`data/skeleton/test_6.skeleton_racket.json` now carries **26 joints** — the SMPL 24 plus
**24 `racket_grip`** (parent: the holding wrist) and **25 `racket_head`** (parent: 24).
Two new tools, 84/84 tests green.

### The blocker: ROMP never exported its camera

`test_6.smpl.npz` has `joints3d/pose/betas/transl/fps` and no camera, so there was no way to
relate racket pixels to body metres. Rather than re-run ROMP, `tools/fit_camera.py` recovers
it locally: MediaPipe supplies 2D landmarks on the same clip (CPU, reusing
`extract_skeleton.extract_raw`), ROMP supplies the 3D joints, and 12 limb joints correspond
between the two skeletons — 2268 pairs over 189 frames.

**Which model, measured rather than assumed.** One global pinhole `u = fx·X/Z + cx` fit
badly: fx/fy split by 2.6x, 60 px rms. That is a model absorbing error. Per frame:

| model | median rms (at 3840x2160) |
|---|---|
| weak perspective `u = s·X + tx` | **22.7 px** |
| pinhole `(f, cx, cy)` | 34.0 px |

Weak perspective wins because it is what ROMP optimises — its depth is a per-frame scale,
not a metric distance, so internal 3D structure is meaningful while absolute Z is not. And a
per-frame camera is *sufficient*: the racket and the body only ever need relating within one
frame. Final fit: **189/189 frames, median 25.5 px rms at 4K** (~12.7 px at 1080p).
Image coords are normalized by frame **width** on both axes, which dissolves the
1080p-racket / 720p-SMPL / 4K-source mismatch without any bookkeeping.

### The lift: weak perspective makes the geometry almost trivial

Inverting `u = s·X + tx` recovers the racket's world **X and Y outright**. Only `dZ` is
unknown, and the rigid racket gives it:

    dZ = +/- sqrt(L^2 - dX^2 - dY^2)

so each frame has exactly two candidates — tip toward the camera or away. The sign is
resolved per *run* of measured frames: seed from the forearm (a racket extends away from the
elbow far more often than back over it), then propagate by continuity. Runs are seeded
independently so a stale sign cannot cross a gap. When apparent length exceeds `L`, `dZ`
clamps to 0 rather than going imaginary.

`L` is **measured, not assumed**: apparent length peaks when the racket lies in the image
plane, so the 90th percentile of observed apparent lengths is the true length. This avoids
guessing where RacketVision's `handle` keypoint sits along the grip.

### Three independent validations, none of them designed in

1. **Racket length came out at 0.693 m.** A badminton racket's regulation maximum is
   **0.680 m**. That number was derived from MediaPipe 2D, ROMP 3D and RacketVision keypoints
   with no physical prior anywhere in the chain — agreeing to 2% says the camera scale is right.
2. **The grip lands 4.5 cm from the SMPL right hand** (vs 69 cm for the left). That is how
   handedness is auto-detected, and 4.5 cm is about where a grip sits relative to a hand joint.
3. **Zero >90° flips** across 78 consecutive measured pairs; median frame-to-frame direction
   change 6.5°, p90 16.6°. The sign resolution is stable without any smoothing.

Reprojecting the lifted 3D racket back through the camera lands it on the real racket in the
video (checked on fr126). On fr30 — a frame with **no detection at all**, filled by the
forearm prior — the reprojection still lands within a few degrees of the true shaft, which is
the reassuring answer to "what happens in the 56% of frames the detector misses".

### Coverage and honesty about it

    measured   83/189  (44%)   from vision
    prior     106/189  (56%)   forearm direction at the hand, confidence 0
    none        0/189  (0%)

Every frame carries `racket_status`, and prior frames are written with **confidence 0**, so a
posed racket can never be read as a measured one downstream.

### Caveat for Stage 3

`joints_flat` is now **26** joints, not 24. Consumers must read `joint_names`/`parents`;
anything with a hardcoded 24 will break. The output is a new file — `test_6.skeleton.json`
is untouched.

---

## 2026-07-25 — Stage 2b: the racket has ROLL (it was a line)

wenzhen spotted the real limitation: grip + tip is only a **line**. Nothing in the long axis
says whether the face is edge-on or flat-on — and face angle is the whole point for stroke
and injury analysis. (The framing was "MediaPipe can't give rotation", but MediaPipe was only
ever used to recover the camera; the line came from using 2 of the 5 keypoints.)

### The roll was already in the data

`left`/`right` straddle the head rim: perpendicular to the shaft, *in* the racket plane —
exactly the missing DOF. The solve mirrors the shaft's: inverting weak perspective gives the
width vector's X and Y, the head width gives |dZ|, and perpendicularity to the shaft picks
its sign. (First attempt derived dZ *from* perpendicularity alone — wrong: it collapses to
zero exactly when the face goes edge-on, which is when you most need it.)

**Measured head width: 0.209 m**, against a real badminton head of 0.20-0.23 m. Third
independent scale check to fall out of this pipeline, after the 0.693 m length and the 4.5 cm
grip-to-hand distance.

New joint **26 `racket_side`** (parent 25), half a head-width off the tip in the racket plane.
Consumers build the frame as `shaft = head-grip`, `across = side-head`,
`normal = shaft x across`. Joint count is now **27**.

### Roll is held as an angle, and it is pi-periodic

Stored as a scalar angle about the shaft rather than a vector, because that is what can be
smoothed and interpolated honestly. Critically it is **pi-periodic**: `left` and `right` are
interchangeable on a symmetric head, so a 180-degree jump is a relabelling, not motion, and
ordinary 2*pi unwrapping would read it as half a turn of real rotation.

### Rejected after testing: SMPL's wrist rotation

The obvious universal fallback — the racket is rigidly gripped, so drive roll from the hand,
which SMPL has every frame. Tested by expressing the measured shaft direction in the SMPL
right-wrist frame; if the grip were rigid and the wrist accurate it would be constant.
It is not: **median 32 deg deviation, p90 75 deg**. ROMP's wrist orientation is unreliable
(the hand is a few pixels and monocular SMPL barely constrains it). Dead end, documented.

### Honest coverage, and a bug caught on the way

First run reported roll at **78%** — higher than the 44% position coverage, which is
impossible. Cause: the roll smoother interpolated between measurements with no gap limit, so
it bridged the 42-frame holes and labelled the result "measured". Fixed twice over: gaps
longer than 4 frames are no longer bridged (matching the 2D track's own limit), and roll now
has its own vocabulary where bridged frames read `interpolated`, never `measured`.

    position   measured 83 (44%)  prior 106 (56%)  none 0
    roll       measured 63 (33%)  interpolated 10 (5%)  none 116 (61%)
    roll rejected because: no_racket 106, low_side_score 12, not_perpendicular 8

Roll carries a **separate confidence** from position, because the shaft can be solidly
measured in a frame where the face angle is a guess — collapsing the two would hide exactly
that. Gating (min(left,right) score >= 0.50, perpendicularity correction <= 25 deg) plus a
3-frame median cut frame-to-frame face-normal noise from p90 40 deg to **p90 31 deg**,
median 4.9 deg.

Four adjacent pairs still move >45 deg. Some is real — frame 126 sits in the smash with the
head at 8.8 m/s, where hard pronation is genuine — but near-90-degree changes are also the
signature of a width-vector sign flip, and without ground truth the two are not separable.
Recorded rather than tuned away.

### Also fixed

`select_racket_track.py` only carried the *mean* keypoint score, so the per-keypoint
`left`/`right` confidences the roll gate needs were not in the track at all (I had to reach
back into `racket2d.json` to prototype). It now carries `keypoint_scores` through.

### Verification

Reprojecting the oriented racket — shaft plus a head ellipse drawn *in the solved face
plane* — puts the ellipse on the real racket head at the correct tilt on frames 105 and 118.
103 tests pass.

### Where the monocular ceiling is

Roll is precisely what a second camera fixes cheaply, and the December plan already has the
two-camera OpenCap rig. Optional next lever if monocular roll must improve sooner: MediaPipe
**Hands** (21 landmarks -> palm normal, a dedicated hand model rather than SMPL's guess),
validated against the 63 measured-roll frames before being trusted.

---

## 2026-07-25 — Stage 3: the racket is on the Blender twin (vision-racket pipeline complete)

`tools/blender/racket_viewer.py`. Open `models/smpl/test_6_compare.blend` → Scripting →
Alt+P → the **"Racket"** tab in the N-panel. Idempotent, like `twin_compare.py`. Built and
verified live over the Blender MCP bridge (Blender 5.2 LTS).

### The trap: skeleton.json is MIRRORED relative to the scene

A first per-frame Procrustes fit of the 24 JSON joints onto the 24 armature bone heads gave
**0.21 m rms** and, tellingly, `det(R) = -1` on every single frame. That determinant is the
whole story: `skeleton.json` has been through `WORLD_TO_UNITY = diag(1,-1,1)`, which is a
**reflection**, not a rotation. It turns the body into its mirror image, where left and right
are swapped — so matching `left_hip` to `L_Hip` was asking Procrustes to fit a body to its
own mirror, and the best it could do was a 21 cm compromise.

Multiplying by `diag(1,-1,1)` again (it is its own inverse) puts the joints back in ROMP
camera space, and the fit collapses to **0.026 m rms with det = +1**. The script now excludes
reflections outright: a mirrored fit looks numerically fine while putting the racket on the
wrong arm.

Diagnosis order that got there, worth repeating: global fit (0.64 m) -> pelvis-relative
(0.25 m) -> per-frame (0.21 m) -> compare limb lengths (agree to 3-7%, so not scale, and
not shape) -> notice det = -1 everywhere. The limb-length check is what ruled out the
plausible-but-wrong "different body shape" explanation.

### The second trap: the twins play in place

Body A's pelvis is byte-identical at every frame — the SMPL add-on animates pose only, with
no root translation, while the JSON carries the real translation (X from -2.97 to -0.32 m).
So no single world transform can exist. Fitting **per frame** absorbs it automatically and
costs nothing, and the residual doubles as a live quality read-out.

Residual after both fixes: **2.6 cm** median on the raw body, 3.0 cm on the smooth one
(max 11 cm). That remainder is the add-on's template body against ROMP's regressed joints —
a shape difference, not an error — and it is the honest precision of this viewer.

### Confidence is drawn, not buried

The racket renders as a shaft plus a **filled elliptical bed** (a face, so orientation reads
at a glance — the point of Stage 2b). Object colour is keyframed with CONSTANT interpolation:

    green  position + roll measured   63 frames  (33%)
    amber  position measured, roll guessed  20   (11%)
    red    position is the forearm prior   106   (56%)

Drawing one uniform colour would imply three times more real data than exists. Constant
interpolation matters too: with the default Bezier, a red prior frame would *fade* through
orange and read as medium confidence.

### Verified

Frame 118 renders green with the bed tilted, in the raised right hand — matching the video.
Frame 30 renders red hanging down at the side — also matching. Grip-to-hand distance in the
scene is 6.6 cm, consistent with the 4.5 cm anatomical offset plus the 2.6 cm fit residual.

### Blender 5.2 API notes (cost a round each)

- `Action.fcurves` is gone; 4.4+ uses layer/strip **channelbags**. `action_fcurves()` reads
  both layouts so the script survives whichever Blender opens the .blend next.
- `Material.use_nodes` is deprecated in 6.0 and warns on assignment — only set when False.
- `BLENDER_EEVEE_NEXT` is not a valid engine id here; it is `BLENDER_EEVEE`.

### Scene state

The .blend is **gitignored** (`models/`), so the script is the durable artifact — re-run it
after any re-lift. The file was left **unsaved**; I set the render engine and moved the
camera for verification renders and restored the frame to 124.

---

## 2026-07-26 — Racket smoothing + toggles, and the pipeline timed end to end

### Smoothing a rigid body (`tools/racket_smoothing.py`, new)

The "smooth" twin was carrying a **raw** racket — the comparison was only half honest.
Fixed, but not by filtering the three racket points: they are not independent (fixed length,
fixed perpendicular half-width), so per-point filtering turns a rigid object into a wobbling
one. The racket is decomposed into what is genuinely free — grip position, shaft direction,
width direction — each smoothed, then recomposed at the median length and width. Rigidity is
preserved **by construction**; tests assert `std(length) < 1e-9`, not "approximately rigid".

Width vectors are sign-aligned first: `left`/`right` are interchangeable, so one meaningless
relabelling would make the smoother interpolate through the zero vector and collapse the
racket's plane mid-swing.

Two implementation findings, both measured rather than assumed:

1. **Explicit Euler is unusable here.** The obvious `v += a*dt; x += v*dt` spring overflows
   once `omega*dt` approaches 1 — at 25 fps that is any tau below ~0.1 s, well inside the
   range someone would dial in. Replaced with the closed-form solution of the critically
   damped ODE, which is stable at every timestep. Verified down to tau = 0.02 s.
2. **Zero-phase, not causal.** A single causal pass at tau = 0.12 s lags 2.5 frames. At the
   smash the racket head moves 8.8 m/s, so 100 ms of lag drags it most of a metre behind the
   hand holding it. This is offline data, so the filter runs forwards then backwards:
   **93% less frame-to-frame jitter, zero lag** (causal alone: 59% and 2.5 frames behind).

**Careful with that 93%.** It is a high-frequency metric (std of successive differences).
RMS error against the true trajectory falls only ~half, because tau = 0.12 s at 25 fps
averages just a few frames — and on a fast swing barely at all: a test pins the trade-off
explicitly, asserting that at 2.5 rad/s smoothing stays *between* 0.5x and 1.0x of the raw
error, i.e. the filter is blurring real motion as much as noise. Anyone raising tau for a
prettier idle pose is paying for it during the stroke. Smoothing moves the head a median
5.8 cm on test_6, ~10 cm at the smash.

### Viewer (`tools/blender/racket_viewer.py`)

Two actions per racket (`act_racket_<key>_raw` / `_smooth`) so **Style** switches exactly the
way the body's does. Panel is now N > "Racket": per body Style raw/smooth, Racket on/off,
Joints on/off. Three racket joint spheres (grip blue / head green / side magenta) **parented
to the racket**, so they need no keyframes at all.

Three bugs caught while building it, all of the same family — state that looks set but is not:

- **Action duplication.** `use_fake_user = True` (needed so both styles survive a save) means
  `users == 0` is never true, so the old cleanup never fired and `actions.new()` produced
  `act_racket_A_raw.001`, `.002`, `.003` — a fresh duplicate set every single run. Cleanup
  now clears the fake user first and sweeps everything matching the prefix. Verified
  idempotent by running twice and diffing the action list.
- **Slot binding.** On Blender 4.4+ slotted actions, assigning `ad.action` without binding
  `ad.action_slot` leaves the action assigned but driving nothing — the racket silently
  freezes on style switch.
- **Joint spheres rendered white.** They had materials, but Workbench "Object" colour mode —
  the mode that makes the confidence colours visible — reads `object.color`, which was never
  set. Both channels are set now.

Racket joints live in their own `*_racket_joints` collections: `twin_compare.build_joints()`
clears the body's `*_joints` collection on every run and would delete them.

### Timing, measured on test_6 (189 frames, 7.6 s of 4K @ 25 fps)

    LOCAL (this laptop, no GPU)
      fit_camera        15.3 s   <- MediaPipe over 189 4K frames; dominates
      select_racket_track 0.2 s
      lift_racket_3d      2.8 s
      Blender viewer      0.5 s
      local total       ~19 s

    COLAB (GPU, not instrumented -- estimates)
      ROMP pose pass         ~1-2 min on a warm VM
      RacketVision 2D pass   ~2-3 min on a warm VM
      env build (cold VM)    ~5 min, and it is the whole risk -- see tools/colab/README.md

So a 7.6 s clip is **a few minutes of wall-clock on a warm Colab VM, ~20 s locally**, and
roughly half an hour on a cold VM where the OpenMMLab install has to be rebuilt. The local
side scales linearly with frame count and is nowhere near the bottleneck; caching the Colab
env to Drive remains the highest-value operational fix.

---

## 2026-07-26 — headless render: source footage beside the smoothed twin
`tools/blender/render_compare.py`. Same scene the N-panels drive
(`models/smpl/test_6_compare.blend`), now rendered to
`data/render/test_6_raw_vs_smooth.mp4` — 1280×720 H.264, 189 frames @ 25 fps, ~1 min.

Three things were worth getting right, and each was found by looking at the output:

- **The saved .blend has no racket.** `Racket_A/B` only ever lived in the running session.
  The render script calls `racket_viewer.build()` on load, which also means the video always
  reflects the current lift instead of the state of the last manual save.
- **The camera is computed, not authored.** Bone heads plus racket bounds are sampled every
  frame, and the camera backs off along the players' measured facing direction until every
  sample projects inside the frame. First attempt framed the bodies and *then* added the
  "RAW"/"SMOOTH" text, which put the text off-screen — where it was invisible but still cast
  a shadow, so the floor grew a smear of unreadable letters. Labels are now created first and
  their extent goes into the framing cloud.
- **Workbench, "Object" colour mode.** The racket's confidence colours are keyframed onto
  `object.color`; any other shading mode renders them uniform and silently implies three
  times more measured data than exists. Shadows are off — with two bodies, two rackets and
  floating text they overlap into what reads as extra limbs. Cavity carries the depth.

Blender 5.x API note: `image_settings.file_format = "FFMPEG"` now raises
`enum "FFMPEG" not found` unless `image_settings.media_type` is set to `"VIDEO"` first. The
error names the codec, so it reads like a build without ffmpeg support; it is not.

**Reframed the same day, on request.** The deliverable is now the **source clip beside the
smoothed twin**, not raw twin vs smooth twin: `tools/side_by_side_video.py test_6` →
`data/render/test_6_video_vs_twin.mp4` (2560×720, ~1 min). `render_compare.py` renders only
the twin panel (`--bodies B` by default, `A,B` still gives the old pair) and ffmpeg stacks it
against `data/raw/test_6.mp4`.

- **All text moved out of the 3D scene** into the ffmpeg composite. Text in Blender has to be
  placed before the camera is framed and then re-checked against it; on the finished frame it
  is placed in pixels, cannot be occluded by a limb, and can label the video panel, which
  Blender never renders. No burn-in, no frame counter, no numbers anywhere — asked for.
- **The body is blue now.** It was green, which is also the racket's "fully measured" green,
  so a colour key would have had one colour meaning two unrelated things. Green/amber/red are
  now the racket's confidence and nothing else.
- **Colour key, bottom right panel.** Most of test_6 has no racket detection, so the racket
  is a forearm prior and shows red for long stretches; unlabelled that reads as a broken
  tracker rather than as the honest confidence signal it is.

⚠️ Blender gotcha worth keeping: hiding the unwanted body needs `layer_collection.exclude`,
not `hide_render`. `racket_viewer` **keyframes** `hide_render` on the racket (it hides itself
where there is no racket to draw), so anything set outside the action is overwritten on the
next frame — the first single-twin render had the raw twin's racket floating through the shot
with no body attached. `hide_set()` does not help either: it is the viewport eye, not the
render flag.

## 2026-07-26 — Bone vectors, the four-up showcase, and a labelled joint figure

Three things landed, plus two real bugs found on the way.

**Bone arrows (`tools/blender/twin_compare.py`).** The scene had renderable joint spheres but
nothing for the bones between them: Blender's stick armature is a viewport overlay and never
reaches a Workbench render, so every twin render to date has shown skin or loose dots and
never the topology. `build_bones(prefix)` now writes one tapered arrow per parent→child pair
— pinned to the parent joint by COPY_LOCATION, stretched to the child by STRETCH_TO with
`rest_length=1.0` and `volume='NO_VOLUME'`, so a unit-length mesh reads as metres and a long
bone gets a longer arrow, never a fatter one. No keyframes, nothing to rebuild when the
action changes. 23 arrows for 24 joints; `root` is a rig handle, not a joint, so `Pelvis`
starts the tree. New "Bones" toggle beside "Joints" in the N-panel.

**`tools/quad_video.py`** — 2×2 progress showcase → `data/render/<id>_quad.mp4`, 1920×1080.
Raw pose as nodes+vectors without mesh · raw with mesh · smoothed with mesh · source clip.

- **One camera for three panels.** Each `render_compare` run solves its own framing, and a
  body without its mesh samples a smaller volume than one with it, so three independent
  solves put the twin at three sizes. Side by side that reads as a rendering inconsistency
  rather than as the pose difference the grid exists to show. Panel 1 saves the solved
  camera; the rest inherit it. Stored **relative to the body's origin**, so body B — 1.4 m
  away in the scene — still lands centred in its own panel (camera x 0.91 → 2.31, exactly
  +1.4).
- **X-ray is the only way nodes read through skin.** Workbench has no per-object alpha, so
  the mesh panels fade *everything*, racket colours included. Read racket confidence off the
  no-mesh panel. The floor is off in all three: X-ray dissolves it anyway and the compare
  twins play in place, so it was carrying no motion information.
- Titles hug each panel's top-left, not its centre — the racket reaches the top of frame on
  the smash and a centred caption sits on it.

**`tools/joint_diagram.py`** → `data/render/smpl24_joints.png`. Rest-pose front view, all 24
joints labelled with index + `skeleton.json` name, spine chain highlighted. Positions come
from the new `render_compare --dump-joints`, which projects through the same
`world_to_camera_view` the render used, so a label cannot drift off its node. Labels relax
apart in margin columns rather than cascading downward — a one-directional pack sent the
five near-identical arm-joint y values 200 px below the limb they belong to and crossed every
leader line. Near-ties in y break on distance from the body, so collar→shoulder→elbow→wrist→
hand come out in limb order.

⚠️ **Two bugs worth remembering:**

- **`--no-racket` did not remove the racket.** It skipped the *rebuild*, but
  `test_6_compare.blend` has been saved since an interactive `racket_viewer` run and carries
  `Racket_A`/`Racket_B` — and their keyframed `hide_render` restores them on the next frame.
  The README's claim that "the saved file has no racket in it at all" was false. `--no-racket`
  now deletes the objects outright (in memory; the render process never saves the file).
- **Resolution was set after the camera solve.** `world_to_camera_view` reads the scene
  aspect ratio, so any `--res` whose aspect differed from the saved .blend framed against one
  ratio and projected against another. Now set before both the solve and the dump.

Also: Workbench "Object" colour mode reads `object.color` and **ignores materials**, so node
colours are set on the objects in `render_compare`, not left to the materials `twin_compare`
attaches. Blender on Windows occasionally exits non-zero after a render that completed fine,
so `quad_video` gates on its own `render_compare: wrote` line plus the file existing rather
than on the exit code — an exit-code check threw away three minutes of finished panels once.
