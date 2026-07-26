# BadmintonVR — project notes for Claude

## What this project actually is
NOT a VR game (yet). It is a **video → skeleton → Unity twin** research pipeline:
phone video of a badminton player → pose extraction (Python) → `skeleton.json`
(schema v1, the load-bearing contract) → Unity replays a moving twin skeleton on
a regulation court.

Read `docs/superpowers/specs/2026-07-12-video-to-unity-twin-design.md` for the
approved design (phases, schema, decisions) before making architectural changes.
**Read `docs/for-claude/PROGRESS.md` for what is already built and how to run it** — and
append a dated entry there when something new lands.

## ⚠️ Active plan (reframed 2026-07-23) — READ THIS FIRST
This is now a research deliverable with a hard **early-December-2026** target. The
current forward plan is **`docs/for-me/DECEMBER-PLAN.md`** (scope, sprints S0–S9,
OpenCap pivot, capture route, validation, decisions log). Visual views:
`docs/for-me/ROADMAP-BOARD.html` + `docs/for-me/TIMELINE-DEC.html`; actions:
`docs/for-me/TODO.md`; literature: `docs/for-me/RESEARCH-BRIEF.pdf`. This lane owns
physics + video-to-twin + skeleton accuracy; muscle/injury modelling is somebody
else's lane and out of scope here. The "Milestone phases" list below is the ORIGINAL
pipeline framing — still accurate for what is BUILT, but superseded for forward
planning by the December plan.

**docs/ layout:** `docs/for-me/` = wenzhen's plan + reading — **gitignored, local
only**; it is the ONLY place collaborator/institution names belong, and nothing that
gets published may reference them. `docs/for-claude/` = this agent's working context
(PROGRESS ledger, technical plans, research notes); `docs/superpowers/` = specs/plans
(skill convention).

## Milestone phases
1. **Phase 1 (DONE):** phone clip → stick-figure/humanoid twin in Unity, pose
   only — NO court calibration; twin plays in place at court center.
2. **Phase 2 — single-phone court position.** Split into two sub-phases after
   the 2026-07-15 calibration post-mortem (the first attempt's calibration was
   off — see `docs/for-claude/PROGRESS.md` and `docs/for-me/DOCUMENTARY.md`):
   - **Phase 2.1 (DONE) — corner tracking & calibration.** Clean, correctly-labeled
     ground-plane homography from one static phone (`tools/calibrate_court.py`).
     First attempt on `position_front.mp4` FAILED (0.6x ultrawide from the ground;
     right-side corners clicked on the neighboring paint set). Re-shot as stills
     from a higher corner angle at 1.0x (`data/raw/court_2.jpg`) and calibrated
     successfully → `data/calib/court_2_court.json` (see `docs/for-claude/PROGRESS.md`
     2026-07-16). Gotchas for this hall: floor tiles run parallel to the court so
     AUTO corner-detection fails — use the interactive click; and the box sits
     DIAGONALLY in frame (`corner_fr` is top-CENTER, not the right edge).
   - **Phase 2.2 — position → Unity twin.** With a valid 2.1 calibration,
     `extract_skeleton.py --court` maps the foot pixel → `root_court_xz` and
     `HumanoidPoseDriver` / `SkeletonPlayback` moves the twin there. The pipeline
     plumbing (old Phase 2) is already built; it just needs a correct calibration
     to feed it. Basic movement only, minimum hardware.
   **Scope: ONE half-court only** (the void-deck paint is just the
   SSL→baseline half; no net line). Tracked half = +Z (net z=0,
   baseline z=6.70); calibrate with `_f` points + `--half far`.
2.5. **Racket (current).** Locate the racket together with the skeleton.
   Step A (DONE 2026-07-17): `RacketVisual` — orange racket, grip at right
   wrist, **articulated by the hand landmarks** (wrist→knuckles, palm normal
   rolls the bed); NOT welded to the forearm. Per-clip flag: test_3/4/5 carry
   a racket. Step B (DONE 2026-07-17): zero-shot COCO "tennis racket" probe
   `tools/detect_racket.py` — **works** (test_3 90.9% hit rate, best conf
   0.92); no own-data gathering needed. Step C (box+arm-prior fusion) is
   **shelved** — superseded by Step D and off the December critical path.
   **Step D — RacketVision (ACTIVE, 2026-07-24→):** AAAI'26 MIT model, 5 2D
   racket keypoints + pretrained ckpts, on Colab —
   `tools/colab/racketvision_extract.ipynb` (Stage 1: 2D json + overlay;
   Stage 2: lift to a 3D segment at the SMPL hand, grip idx24 / head idx25;
   Stage 3: racket on the Blender twin). Setup notes + the full OpenMMLab
   recipe live in `tools/colab/README.md`; the debug log is in PROGRESS.md.
   **Stage 1 DONE 2026-07-25** — 44% clean coverage on test_6 (the two swings).
   Key fact: RTMDet's **detector score is not confidence** (a 0.08 box was a
   perfect fit, a 0.30 box a net-post artifact); rank candidates by **mean
   RTMPose keypoint score** instead. The notebook therefore runs wide open at
   `score_thr 0.05` keeping the top 3 boxes/frame, and `tools/select_racket_track.py`
   picks one per frame → `data/racket/<id>.rackettrack.json` (per-frame
   `detected`/`interpolated`/`missing`) — that file is Stage 2's input, not the
   raw `.racket2d.json`.
   **Stage 2 DONE 2026-07-25** — `tools/fit_camera.py` (ROMP never exported a
   camera; recover a **per-frame weak-perspective** one by pairing MediaPipe 2D
   with ROMP 3D) + `tools/lift_racket_3d.py` (depth from the racket-length
   constraint; sign from forearm seed + temporal continuity) →
   `data/skeleton/<id>.skeleton_racket.json`. **That file has 27 joints**
   (SMPL 24 + `racket_grip` 24 / `racket_head` 25 / `racket_side` 26) — read
   `joint_names`/`parents`, never a hardcoded 24. Racket frame:
   `shaft = head−grip`, `across = side−head`, `normal = shaft × across`.
   Roll comes from the `left`/`right` keypoints and is **much less reliable than
   position** (33% vs 44% on test_6) — it has its OWN `racket_roll_status` and
   confidence; check them before trusting the face normal. Measured length
   0.693 m (vs 0.680 m regulation max) and head width 0.209 m (vs 0.20–0.23 m
   real) are the headline sanity checks. Do NOT try to drive roll from SMPL's
   wrist rotation — tested, 32° median error, ROMP's wrist is unreliable.
   **Stage 3 DONE 2026-07-25** — `tools/blender/racket_viewer.py` draws the
   racket on both twins (Alt+P in `test_6_compare.blend`, "Racket" N-panel tab;
   colour = confidence). ⚠️ **`skeleton.json` is MIRRORED** relative to the
   Blender scene: `WORLD_TO_UNITY = diag(1,-1,1)` is a *reflection*, so undo it
   (multiply again — self-inverse) before fitting joints to bones, or Procrustes
   solves for a mirror and swaps left/right (0.21 m vs 0.026 m residual). Also
   the twins play **in place**, so fit per frame, never globally.
   Racket smoothing lives in `tools/racket_smoothing.py` (numpy-only *on
   purpose* — the Blender script imports it, and Blender has no cv2/mediapipe):
   decompose to grip/shaft-direction/width-direction, smooth, recompose rigid;
   zero-phase spring, τ=0.12 s. Timing for a 7.6 s clip: ~20 s local + a few
   minutes on a warm Colab VM (a cold VM adds ~5 min of OpenMMLab install).
   See `docs/for-claude/ai-smoothing-plan.md` (racket tie-in section).
3. **Phase 3:** **two-camera (OpenCap-style)** capture. *Plan NOT concrete
   yet — single camera is the working assumption for now.* Triangulate 2× 2D pose
   into accurate 3D position + pose using court-corner PnP calibration. Both
   cameras on one side, behind the baseline, ~6–7 m apart (~65° crossing angle).
   This fixed rig doubles as the bulk training-data capture setup.
4. **Phase 4:** fine-tune a badminton-specific pose model (RTMPose/ViTPose class)
   on existing datasets (VideoBadminton, ShuttleSet, MultiSenseBadminton) plus the
   Phase-3 captures — on Colab/cloud GPU, exported to ONNX.
5. **Phase 5:** near-live: Python inference server first, then in-Unity ONNX via
   Sentis (`com.unity.ai.inference`, already a dependency).

**Parked (do not design for now):** drones, VR headset game, shuttle tracking.
(Racket tracking is UN-parked — it is Phase 2.5. Multi-camera is Phase 3 but
its plan is not concrete. **Injury/biomechanics is UN-parked as of 2026-07-17
at PLAN level only** — the project's purpose is muscle injury in badminton;
see `docs/for-claude/muscle-analysis-plan.md`. Do not start implementing it: the user
said "for this one we plan first", and it is gated on pose quality + racket
fusion landing first.)

## Hard constraints
- **This laptop has NO NVIDIA GPU** (Intel Iris Xe). MediaPipe-class CPU
  inference and Unity work only; all training/heavy inference goes to Colab/cloud.
- Python 3.12.5, pip, ffmpeg installed. No conda.
- Unity 6000.1.4f1, URP. Unity MCP bridge is flaky ("Connection revoked") —
  prefer file-based editing; the user can click menu items manually.

## Layout & conventions
- Repo root = this folder (`BadmintonVR/`). Research notes live in
  `docs/for-claude/research-notes/` (moved from the outer folder 2026-07-16; the .pdf twins
  stay outside the repo) — read them for research context (esp.
  `camera-research.md` §6 pipeline + data schema).
- Python CV/ML code lives in `tools/` (create as needed). Unity code in `Assets/Scripts/`.
- Data: raw videos in `data/raw/` (gitignored, named `test_N.mp4`;
  `position_front` was renamed `test_5` on 2026-07-16); extracted
  `skeleton.json` in `data/skeleton/`. **Privacy rule for the public repo:**
  every frame-bearing image (`data/**/*.png|jpg`, `docs/img/`) is gitignored —
  never commit images containing video frames of people/places.
- `Assets/Editor/CourtBuilder.cs` builds the court: Tools ▸ Badminton ▸ Build Court.
  Court runs along Z (length 13.40 m), X = width (6.10 m), Y-up, meters, origin
  at court center. **skeleton.json uses these same conventions.**
- Coordinate conversion (Y-flip, handedness) happens in **Python**, never Unity.
- GitHub: roasteduck04/BadmintonVR — **public** (user flipped it 2026-07-16).
  Mind the privacy rule above with every commit.
- Runtime helper objects (video-compare canvas, racket, debug trail) must live
  at the SCENE ROOT — `SkeletonRenderer.Clear()` destroys all twin children on
  every clip load.
