# Design: Badminton Video → Skeleton → Unity Twin

**Date:** 2026-07-12 (expanded same day with per-phase breakdowns)
**Status:** Approved in brainstorming; awaiting written-spec review
**Repo:** BadmintonVR (Unity 6000.1.4f1, URP)

---

## 1. What we are building

A pipeline that turns ordinary **phone video of a badminton player** into a
**moving 3D "twin" skeleton inside Unity**, replayed on a regulation court.
Offline (file-based) first, near-live last.

This is the current milestone of the larger the university badminton research project. It
follows the phone/OpenCap-style capture direction from
`research-direction-image-to-sim.md` and the pipeline/schema in
`badminton_camera_research.md` (§6).

### Explicitly parked (not abandoned, just not this milestone)
- Drone-based capture (the university scope doc)
- Injury / biomechanics analysis (OpenSim Moco, muscle loads, MIA)
- VR headset game
- Multi-camera metric-accurate 3D rig (see §5 for the honest fidelity ladder)
- Shuttle and racket tracking (candidates for the milestone after this one)

---

## 2. Architecture — two worlds, one contract

```
PHONE VIDEO ──► [ PYTHON: extraction ] ──► skeleton.json ──► [ UNITY: twin ]
                MediaPipe now,              (schema v1 —        stick figure on
                RTMPose fine-tuned later    THE contract)       CourtBuilder court
```

- **Python world** (`tools/` in repo): all CV/ML. Runs on this laptop for
  MediaPipe-class work; anything requiring training or heavy inference runs on
  Colab/cloud GPU (laptop has Intel Iris Xe only — no CUDA).
- **Unity world** (`Assets/`): consumes `skeleton.json`, renders and replays the
  twin. Never does CV.
- **The contract**: a versioned JSON schema. Both sides depend only on it. It is
  the load-bearing decision of the whole project; changes require a version bump.

### 2.1 Pose + root split (root arrives in Phase 2)

MediaPipe world landmarks are **hip-centered** — pose only, no court position.
So the pipeline splits:

1. **Pose** (limb configuration): MediaPipe pseudo-3D world landmarks,
   hip-relative. **This is all of Phase 1** — the twin plays in place, anchored
   at court center.
2. **Root translation** (where on court): the player's feet position in *image
   pixels*, mapped through a **court homography** (user clicks the 4 court
   corners once per clip) → court-relative X/Z in meters. **Added in Phase 2.**

Unity composes them: stick figure posed by (1), positioned by (2). This matches
`player_court_position` in the research note's §6.2 schema. The schema carries
`root_court_xz` from v1 (nullable), so adding it in Phase 2 is non-breaking.

---

## 3. The data contract — skeleton.json schema v1

One JSON file per processed clip.

```jsonc
{
  "schema_version": "1.0",
  "video_id": "clip_001",
  "source": { "type": "phone_static_tripod", "fps": 30.0, "resolution": [1920, 1080] },
  "extractor": { "pose": "mediapipe-0.10", "notes": "world landmarks, smoothed" },
  "coordinate_system": "unity",       // left-handed, Y-up, meters, court center = origin,
                                       // +Z toward far baseline (matches CourtBuilder)
  "joint_names": [ /* MediaPipe 33-landmark names, fixed order */ ],
  "court": null,                       // Phase 2+: { corners_image: 4x[x,y],
                                       //   homography: 3x3 image→court meters }
  "frames": [
    {
      "frame_id": 0,
      "time": 0.0,
      "root_court_xz": null,            // meters, court coords; null in Phase 1,
      "root_confidence": null,          //   populated from Phase 2 (homography)
      "joints_flat": [ x, y, z, confidence, /* ... 33 joints = 132 floats, */ ]
                                       // hip-relative meters, Unity axes,
                                       // joint_names order. Flat (not nested)
                                       // so Unity JsonUtility parses it with no
                                       // extra packages.
    }
  ]
}
```

Rules:
- Coordinates are **converted to Unity conventions in Python** (Y-up flip,
  handedness) so Unity's importer stays dumb.
- Every value that comes from a model carries a **confidence**; Unity may fade
  or hide low-confidence joints.
- Additive fields (shuttle, racket, stroke labels, 3D-lift results) extend the
  schema in later minor versions; breaking changes bump the major version.

---

## 4. Capture protocol & data management

### 4.1 What you do with a video after capturing it

1. Transfer the clip from phone to laptop (USB cable, or cloud/AirDrop-equivalent).
2. Drop it into **`data/raw/`** in the repo, named
   `YYYYMMDD_<shortdesc>.mp4` (e.g. `20260715_clears_sideview.mp4`).
   Not a temp folder — raw clips are the project's source data and every clip
   captured now becomes candidate training/evaluation material for Phase 3.
3. Run the extractor:
   `python tools/extract_skeleton.py data/raw/20260715_clears_sideview.mp4`
   → writes `data/skeleton/20260715_clears_sideview.json`.
4. Open the Unity SkeletonPlayer scene and load that JSON.

### 4.2 Folder + git conventions

| Folder | Contents | Git |
|---|---|---|
| `data/raw/` | Original video clips | **gitignored** (large binaries; keep a backup copy on cloud drive) |
| `data/skeleton/` | Extracted `skeleton.json` per clip | committed selectively (small, useful fixtures) |
| `tools/` | Python extraction code, `requirements.txt` | committed |
| `Assets/Scripts/SkeletonPlayer/` | Unity playback code | committed |
| `Assets/StreamingAssets/skeleton/` | JSONs the Unity scene loads at runtime | committed sample(s) |

### 4.3 Recording checklist (Phase 1 — no court needed)

- Any location; a court is NOT required for Phase 1.
- Phone fixed (tripod, or propped — must not move), landscape, 1080p, 30 or 60 fps.
- Whole body in frame the entire time, including feet; 3–8 m from the player.
- One person in frame. Decent, even lighting; avoid strong backlight.
- 10–30 s of strokes + footwork (shadow swings are fine).

### 4.4 Recording checklist additions for Phase 2 (court required)

- On a court, all lines of the player's half visible, ideally VideoBadminton-style:
  behind the baseline, elevated (2–4.5 m if achievable — a balcony or stand),
  tilted down ~30°. A lower tripod still works; elevation just improves the
  homography.
- No zooming or panning ever — the homography is computed once per clip and
  assumes a fixed camera.

---

## 5. Camera fidelity ladder — what phones can and can't give us

The user's goal: **as good as possible with phone cameras only.** Ground truth
on what each rung buys, and what is physically impossible:

| Rung | Setup | What you get | Limit |
|---|---|---|---|
| 1 phone (this milestone) | Single fixed phone | Reliable 2D pose + pseudo-3D (hip-relative, learned depth) + court-anchored root position (Phase 2) | Depth is *inferred, not measured*. Monocular depth ambiguity is a geometric fact, not a software gap. Facing direction can flip on ambiguous frames (the BST 2D-vs-3D finding). |
| 2 phones, OpenCap-style (next milestone) | Two phones ~30–45° apart, calibrated (checkerboard), time-synced | **True triangulated 3D** — measured, not guessed. This is exactly why OpenCap uses ≥2 cameras. | Setup friction: calibration + sync (clap/flash sync works) each session. Still not marker-mocap accuracy. |
| 3–4 phones | Adds redundancy for occlusion | Biomechanics-grade claims become defensible | Serious calibration effort |

Decisions this implies:
- **This milestone stays monocular** — that's the accepted fidelity ceiling, and
  Phase 3 (better model) raises quality *within* the monocular limit.
- Everything is built so the second phone slots in later without rework: the
  schema's `pose_3d` is method-tagged, and calibration/sync live entirely in the
  Python world. Two-phone triangulation is the natural **milestone after this
  one**, and it reuses every Phase 1–3 component.
- Practical tip: when recording Phase 2 clips, having a friend film a second
  angle casually (even unsynced) costs nothing and gives Phase 3 extra
  evaluation footage.

---

## 6. Phases — detailed breakdown

### Phase 1 — video → skeleton twin in Unity (no court calibration) ← CURRENT

**Input:** any fixed-camera clip per §4.3. Court lines NOT required.

**Steps:**
1. **Python env:** `tools/requirements.txt` (mediapipe, opencv-python, numpy,
   scipy); venv setup documented in `tools/README.md`.
2. **Extractor** (`tools/extract_skeleton.py`):
   - decode frames (OpenCV), run MediaPipe Pose per frame → 33 world landmarks
     + per-joint visibility scores;
   - confidence-gate: drop joints below threshold, interpolate gaps < ~0.3 s,
     flag longer gaps;
   - smooth (One-Euro or Savitzky-Golay — pick by eyeballing jitter vs lag);
   - convert to Unity axes (Y-up, left-handed, meters);
   - write schema-v1 JSON to `data/skeleton/`.
3. **Unity SkeletonPlayer** (`Assets/Scripts/SkeletonPlayer/`), four small parts:
   - `SkeletonData` — JSON parsing into runtime structs;
   - `SkeletonPlayback` — clock, frame stepping/interpolation, speed;
   - `SkeletonRenderer` — spheres at joints + line/capsule bones, low-confidence
     joints faded;
   - `PlaybackUI` — play / pause / scrub bar / speed (0.1×–2×).
   Twin anchored at court center on the CourtBuilder court.
4. **Validation:** original video and twin side-by-side; strokes must be
   recognizable (a clear looks like a clear).

**Exit criteria:** a 10–30 s clip plays back as a recognizable, stable stick
figure; scrubbing works; no wild limb flicker; extractor is one command.

### Phase 2 — court-anchored twin (homography)

**Input:** clip re-recorded per §4.4 (court lines visible).

**Steps:**
1. Corner-click UI (OpenCV window, click 4 corners of the player's half,
   keyboard to redo) → `cv2.getPerspectiveTransform` homography.
2. Sanity check: reproject known court points (e.g. service line intersections);
   refuse to proceed beyond tolerance.
3. Per frame: ankle-midpoint pixels → homography → court X/Z; smooth the root
   path separately from the pose (different noise character).
4. Populate `court` + `root_court_xz` in the same schema (non-breaking).
5. Unity: `SkeletonPlayback` drives root transform from `root_court_xz`.
6. **Validation with ground truth you can create for free:** record a clip of
   the player standing still on known line intersections — extracted positions
   must match those court coordinates within ~10–20 cm.

**Exit criteria:** twin moves around the Unity court matching the player's real
movement; standing-still test passes.

### Phase 3 — badminton-tuned skeleton model

**Goal:** measurably better pose on badminton motion (lunges, jump smashes,
overhead extremes, motion blur, unusual facing) than generic MediaPipe.

**Steps:**
1. **3a — Evaluation set first** (nothing improves without a yardstick):
   pick ~10–20 diverse clips (our recordings + VideoBadminton samples), manually
   label keypoints on selected keyframes; metrics = PCK (keypoint correctness),
   temporal jitter, limb-length stability, missing-joint rate.
2. **3b — Baseline shootout:** off-the-shelf MediaPipe vs RTMPose vs
   ViTPose-class on the eval set. Pick the best base model. (BST used
   RTMPose/MMPose; respect their finding that 2D beat generic 3D lifting.)
3. **3c — Assemble training data** (see §7 for why this matters):
   - **VideoBadminton** — 7,822 controlled 60 fps clips, 18 action classes;
   - **ShuttleSet / broadcast clips** — BST-style extraction gives pseudo-labels
     at scale;
   - **MultiSenseBadminton** — sensor ground truth (IMU) for validation;
   - **our own Phase 1–2 clips** — every clip recorded so far, with manual
     keyframe labels on the hard frames (lunges, smashes).
4. **3d — Fine-tune on Colab/cloud GPU**; export **ONNX**; run locally via
   onnxruntime (CPU, or DirectML which can use the Iris Xe iGPU); swap into
   `extract_skeleton.py` behind a `--model` flag. Same schema out.

**Exit criteria:** fine-tuned model beats the 3b baseline on the eval set, and
the twin visibly improves on the known-hard frames.

### Phase 4 — near-live video → Unity twin

**Goal:** point a phone at a player, twin moves with ≲1 s delay.

**Getting live phone video into the laptop (the "OTG" question):** OTG is not
the right tool — USB OTG is for plugging peripherals *into* a phone. For
phone → laptop the practical options are:
- **Phone-as-webcam over USB cable** (recommended): recent Android has a native
  "webcam" USB mode; otherwise DroidCam/Iriun over USB. Lowest latency, no
  network dependence. The laptop then sees it as a normal webcam
  (`cv2.VideoCapture`).
- **Phone-as-webcam over Wi-Fi** (DroidCam/Iriun wireless): cable-free, slightly
  more latency/jitter; fine as fallback.
- **RTSP/IP-camera app**: most flexible, most latency; last resort.

**Steps:**
1. **4a — Throughput spike:** measure pose fps on this laptop from a live feed
   (downscale to 720p/540p as needed); target ≥15 fps sustained.
2. **4b — Route A (Python server):** capture → pose → per-frame skeleton
   messages (same field layout as schema frames) over WebSocket → Unity client
   (e.g. NativeWebSocket) → the *same* SkeletonPlayer in "live" mode.
3. **4c — Route B (in-Unity, Sentis):** port the Phase 3 ONNX into
   `com.unity.ai.inference`; camera via Unity WebCamTexture; re-implement
   pre/post-processing in Unity. No server — the elegant end-state.
4. Plan: A first (lower risk, proves the loop), B after.

**Exit criteria:** live stroke → twin motion ≲1 s later, ≥15 fps, no drift.

---

## 7. How more training data helps this project

Generic pose models (MediaPipe included) are trained on everyday poses —
standing, walking, sports snapshots. Badminton lives in their long tail:
deep lunges, jump smashes with full arm extension overhead, extreme trunk
rotation, motion blur at 300 km/h racket speeds, players facing away from
camera. That's the **domain gap**, and it's why the twin will glitch exactly on
the frames that matter most.

More badminton training data attacks this from four directions:
1. **Covers the hard poses.** Fine-tuning teaches the model what a lunge or
   smash skeleton actually looks like, instead of guessing from gym poses.
2. **Diversity → generalization.** Different players, lighting, angles, and
   skill levels stop the model from overfitting to one setup — critical since
   Phase 4 will meet arbitrary live conditions.
3. **Ground truth enables *measurement*.** MultiSenseBadminton's sensor data and
   our manually labeled keyframes let us *prove* improvement (Phase 3a metrics)
   instead of eyeballing it.
4. **Compounding asset.** Every clip recorded in Phases 1–2 flows into the
   Phase 3 training/eval pool because the pipeline stores everything in the
   schema. Data collection is not a separate activity — using the pipeline *is*
   collecting data. This is also the long-term research contribution angle from
   the camera note (§10.3): a badminton-specific video-to-simulation dataset.

Rule of thumb for expectations: going from 0 → a few hundred badminton-specific
labeled clips gives the big jump (domain adaptation); after that, returns come
from *diversity* and *label quality*, not raw volume.

---

## 8. Error handling & quality
- Low-confidence / missing joints: interpolate short gaps, flag long ones;
  Unity fades those bones.
- Homography sanity check (Phase 2+): reprojected court points within tolerance
  or refuse to write JSON.
- Extraction is deterministic and idempotent: same clip in → same JSON out;
  JSON is committed test-fixture material for the Unity side.

## 9. Testing
- **Python:** unit tests on coordinate conversion (known synthetic poses),
  schema validation (jsonschema); homography round-trip from Phase 2.
- **Unity:** a committed sample `skeleton.json` fixture; SkeletonPlayer play-mode
  test that loads it and steps frames without exceptions; visual check in editor.
- **End-to-end:** recorded clip → JSON → twin, reviewed side-by-side; Phase 2
  standing-still court-position test.

## 10. Risks
| Risk | Mitigation |
|---|---|
| MediaPipe struggles with fast smashes / unusual facing | Accepted for Phases 1–2 (approx fidelity); Phase 3 exists precisely to fix this |
| Depth/orientation wrong in pseudo-3D | Geometric monocular limit (§5); Phase 2 homography gives a trustworthy root independent of pose depth; 2-phone triangulation is the next-milestone fix |
| Laptop can't train | All training on Colab/cloud; laptop does CPU/DirectML inference + Unity only |
| Live fps too low on this laptop (Phase 4) | Downscale input, frame-skip with interpolation, onnxruntime-DirectML on the Iris Xe |
| Unity MCP connection flaky | File-based workflow works regardless; user can run menu items manually |
| Court corners mis-clicked (Phase 2) | Reprojection sanity check + easy re-run |
| Public dataset licensing (Phase 3) | VideoBadminton/ShuttleSet/MultiSenseBadminton are research datasets — fine for internal training; check terms before redistribution |
