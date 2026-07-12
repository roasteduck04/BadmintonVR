# Design: Badminton Video → Skeleton → Unity Twin

**Date:** 2026-07-12
**Status:** Approved in brainstorming; awaiting written-spec review
**Repo:** BadmintonVR (Unity 6000.1.4f1, URP)

---

## 1. What we are building

A pipeline that turns ordinary **phone video of a badminton player** into a **moving 3D "twin" skeleton inside Unity**, replayed on a regulation court. Offline (file-based) first, near-live last.

This is the current milestone of the larger NTU badminton research project. It follows the phone/OpenCap-style capture direction from `research-direction-image-to-sim.md` and the pipeline/schema in `badminton_camera_research.md` (§6).

### Explicitly parked (not abandoned, just not this milestone)
- Drone-based capture (NTU scope doc)
- Injury / biomechanics analysis (OpenSim Moco, muscle loads, MIA)
- VR headset game
- Multi-camera 3D rig / metric-accurate 3D
- Shuttle and racket tracking (Phase 1.5+ candidates, after the body twin works)

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

### 2.1 Why the twin doesn't run in place (pose + root split)

MediaPipe world landmarks are **hip-centered** — pose only, no court position.
So the pipeline splits:

1. **Pose** (limb configuration): MediaPipe pseudo-3D world landmarks, hip-relative.
2. **Root translation** (where on court): the player's feet position in *image
   pixels*, mapped through a **court homography** (user clicks the 4 court
   corners once per clip) → court-relative X/Z in meters.

Unity composes them: stick figure posed by (1), positioned by (2). This matches
`player_court_position` in the research note's §6.2 schema.

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
  "court": {
    "corners_image": [[x,y],[x,y],[x,y],[x,y]],   // clicked corners, image px
    "homography": [ /* 3x3 row-major, image → court meters */ ]
  },
  "frames": [
    {
      "frame_id": 0,
      "time": 0.0,
      "root_court_xz": [1.23, -4.56],   // meters, court coords; null if unknown
      "root_confidence": 0.92,
      "joints": [ [x, y, z, confidence], /* 33 entries, hip-relative meters, Unity axes */ ]
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

## 4. Phases

### Phase 1 — workable phone video → Unity twin (offline) ← CURRENT
**Input:** one phone clip — fixed tripod, court lines visible (at least the
player's half), one player, ~10–30 s of strokes + footwork. User has court
access and will record this.

**Deliverables:**
1. `tools/extract_skeleton.py` — Python: court-corner click UI (OpenCV) →
   homography; MediaPipe per-frame pose; feet→court root path; smoothing
   (confidence-gated, e.g. One-Euro or Savitzky-Golay); writes schema-v1 JSON.
2. `Assets/Scripts/SkeletonPlayer/` — Unity: JSON importer + **stick-figure**
   renderer (spheres + bone lines) on the CourtBuilder court, with
   play / pause / scrub / speed controls.
3. Side-by-side validation: original video vs twin playback, eyeballed.

**Decisions made:** approximate-3D fidelity (not metric); stick figure first,
**rigged Humanoid avatar is a stretch goal** after the data looks right;
skeleton only (no shuttle/racket).

### Phase 2 — badminton-tuned skeleton model
**Goal:** replace generic MediaPipe with a pose model that is measurably better
on badminton motion (lunges, smashes, occlusion, unusual facing).

- Benchmark MediaPipe vs RTMPose/ViTPose on badminton clips (BST used
  RTMPose/MMPose; 2D beat generic 3D lifting — respect that finding).
- Fine-tune on existing data: VideoBadminton, ShuttleSet-derived clips,
  MultiSenseBadminton (sensor ground truth for validation).
- Runs on **Colab/cloud GPU**. Output: improved model **exported to ONNX**,
  feeding the *same* schema (bump minor version if joints change).
- Evaluation per the research note §8: joint jitter, limb-length stability,
  missing-joint rate, plus visual review — not a single end-to-end score.

### Phase 3 — near-live video → Unity twin
**Goal:** point a phone at a rally, see the twin move with seconds-or-less delay.

Two routes, decided by a Phase 3 spike:
- **Route A — Python inference server:** phone/webcam → Python (ONNX runtime) →
  skeleton frames streamed to Unity over WebSocket/UDP. Same schema, streamed
  not file-loaded. Lower risk, works first.
- **Route B — in-Unity inference (Sentis):** the Phase 2 ONNX model runs inside
  Unity via `com.unity.ai.inference` (already a project dependency). No server;
  the elegant end-state. Risk: preprocessing (letterboxing, normalization) and
  postprocessing must be reimplemented in Unity.

Plan: A first, B as the follow-on once A proves the loop.

---

## 5. Error handling & quality
- Low-confidence / missing joints: interpolate short gaps, flag long ones in
  `occlusion_quality_flags`-style fields; Unity fades those bones.
- Homography sanity check: reprojected court corners must land within tolerance;
  refuse to write JSON otherwise.
- Extraction is deterministic and idempotent: same clip in → same JSON out;
  JSON is committed test-fixture material for the Unity side.

## 6. Testing
- **Python:** unit tests on coordinate conversion (known synthetic poses),
  homography round-trip, schema validation (jsonschema).
- **Unity:** a committed sample `skeleton.json` fixture; SkeletonPlayer play-mode
  test that loads it and steps frames without exceptions; visual check in editor.
- **End-to-end:** the recorded phone clip → JSON → twin, reviewed side-by-side.

## 7. Risks
| Risk | Mitigation |
|---|---|
| MediaPipe struggles with fast smashes / unusual facing | Accepted for Phase 1 (approx fidelity); Phase 2 exists precisely to fix this |
| Depth/orientation wrong in pseudo-3D | Known BST finding; twin is "approximate", root position stays trustworthy via homography |
| Laptop can't train | All training on Colab/cloud; laptop does MediaPipe + Unity only |
| Unity MCP connection flaky | File-based workflow works regardless; user can run menu items manually |
| Court corners mis-clicked | Reprojection sanity check + easy re-run |
