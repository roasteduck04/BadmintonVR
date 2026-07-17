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
(Both also archived under `docs/img/` for the personal journal `docs/DOCUMENTARY.md`.)

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
- Research .md notes moved from the outer folder into `docs/research/`.
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
- **AI roadmap** written to `docs/ai-smoothing-plan.md`: measure → One-Euro +
  gap fill → Kalman + physics gating → temporal 3D lifting (Colab) → better
  backbone; racket detection path (zero-shot COCO → Roboflow/auto-label
  fine-tune → fuse with arm prior).

## 2026-07-17 — Track B: persistent twin driver (springs + IK + foot lock + lookahead)

Architecture shift (plan: `docs/ai-smoothing-plan.md` Track B): the twin is no
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
`docs/ai-smoothing-plan.md`: duplicate boxes on the same racket (~half of
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

**`docs/muscle-analysis-plan.md` (NEW, plan only)** — un-parks the injury
thread narrowly: kinematics + stroke segmentation → rule-based muscle
involvement highlight on the avatar → OpenSim inverse dynamics (Colab) → EMG
validation against MultiSenseBadminton (GIST/MIT, *Scientific Data* 2024:
23 h, 25 players, EMG + IMU + foot pressure). Staged by what each stage can
honestly claim; explicitly does NOT claim injury prediction. Three open
questions for the user at the end of that doc.
