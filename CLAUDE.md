# BadmintonVR — project notes for Claude

## What this project actually is
NOT a VR game (yet). It is a **video → skeleton → Unity twin** research pipeline:
phone video of a badminton player → pose extraction (Python) → `skeleton.json`
(schema v1, the load-bearing contract) → Unity replays a moving twin skeleton on
a regulation court.

Read `docs/superpowers/specs/2026-07-12-video-to-unity-twin-design.md` for the
approved design (phases, schema, decisions) before making architectural changes.

## Milestone phases
1. **Phase 1 (current):** offline phone clip → stick-figure twin in Unity.
2. **Phase 2:** fine-tune a badminton-specific pose model (RTMPose/ViTPose class)
   on existing datasets (VideoBadminton, ShuttleSet, MultiSenseBadminton) — on
   Colab/cloud GPU, exported to ONNX.
3. **Phase 3:** near-live: Python inference server first, then in-Unity ONNX via
   Sentis (`com.unity.ai.inference`, already a dependency).

**Parked (do not design for now):** drones, injury/biomechanics (OpenSim),
VR headset game, multi-camera rigs, shuttle/racket tracking.

## Hard constraints
- **This laptop has NO NVIDIA GPU** (Intel Iris Xe). MediaPipe-class CPU
  inference and Unity work only; all training/heavy inference goes to Colab/cloud.
- Python 3.12.5, pip, ffmpeg installed. No conda.
- Unity 6000.1.4f1, URP. Unity MCP bridge is flaky ("Connection revoked") —
  prefer file-based editing; the user can click menu items manually.

## Layout & conventions
- Repo root = this folder (`BadmintonVR/`). Outer folder holds the 3 research
  .md/.pdf docs — read them for research context (esp.
  `badminton_camera_research.md` §6 pipeline + data schema).
- Python CV/ML code lives in `tools/` (create as needed). Unity code in `Assets/Scripts/`.
- `Assets/Editor/CourtBuilder.cs` builds the court: Tools ▸ Badminton ▸ Build Court.
  Court runs along Z (length 13.40 m), X = width (6.10 m), Y-up, meters, origin
  at court center. **skeleton.json uses these same conventions.**
- Coordinate conversion (Y-flip, handedness) happens in **Python**, never Unity.
- GitHub: roasteduck04/BadmintonVR (private; user wants it public eventually —
  confirm before flipping).
