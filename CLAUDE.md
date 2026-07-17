# BadmintonVR — project notes for Claude

## What this project actually is
NOT a VR game (yet). It is a **video → skeleton → Unity twin** research pipeline:
phone video of a badminton player → pose extraction (Python) → `skeleton.json`
(schema v1, the load-bearing contract) → Unity replays a moving twin skeleton on
a regulation court.

Read `docs/superpowers/specs/2026-07-12-video-to-unity-twin-design.md` for the
approved design (phases, schema, decisions) before making architectural changes.
**Read `docs/PROGRESS.md` for what is already built and how to run it** — and
append a dated entry there when something new lands.

## Milestone phases
1. **Phase 1 (DONE):** phone clip → stick-figure/humanoid twin in Unity, pose
   only — NO court calibration; twin plays in place at court center.
2. **Phase 2 — single-phone court position.** Split into two sub-phases after
   the 2026-07-15 calibration post-mortem (the first attempt's calibration was
   off — see `docs/PROGRESS.md` and `docs/DOCUMENTARY.md`):
   - **Phase 2.1 (DONE) — corner tracking & calibration.** Clean, correctly-labeled
     ground-plane homography from one static phone (`tools/calibrate_court.py`).
     First attempt on `position_front.mp4` FAILED (0.6x ultrawide from the ground;
     right-side corners clicked on the neighboring paint set). Re-shot as stills
     from a higher corner angle at 1.0x (`data/raw/court_2.jpg`) and calibrated
     successfully → `data/calib/court_2_court.json` (see `docs/PROGRESS.md`
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
   0.92); no own-data gathering needed. Step C (next): fuse best-box-near-wrist
   with the arm prior → `racket` block in skeleton.json. Step D: RacketVision
   (AAAI'26, MIT, 5 racket keypoints + pretrained ckpts) on Colab.
   See `docs/ai-smoothing-plan.md` (racket tie-in section).
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
see `docs/muscle-analysis-plan.md`. Do not start implementing it: the user
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
  `docs/research/` (moved from the outer folder 2026-07-16; the .pdf twins
  stay outside the repo) — read them for research context (esp.
  `badminton_camera_research.md` §6 pipeline + data schema).
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
