# Monocular SMPL skeleton → Unity twin (skeleton.json v2)

*Design doc — 2026-07-23. Owner: wenzhen (physics + video-to-twin + skeleton accuracy).*
Supersedes the "skeleton.json v2 design intent" placeholder in `docs/for-me/DECEMBER-PLAN.md`.

## 1. Goal

Take a **monocular RGB clip of one person moving** and produce a **biomechanically-structured
skeleton with a real spine**, land it in Unity as a moving twin, and be able to **measure its
accuracy** against ground truth. This is Stage 1 of the the biomechanics lane pipeline (video → 3D kinematics)
and the thing the AI lane's team can build on.

Explicitly **general pose estimation** — no badminton-specific models or data. Badminton only
re-enters later, at fine-tuning/validation.

## 2. Why this shape (the node question, resolved)

The current pipeline emits **MediaPipe BlazePose (33 landmarks)**, which has **no pelvis joint,
no spine chain, and no neck joint** — exactly the bones Unity Humanoid requires and the region
(back + shoulder girdle) flagged as injury-prone. The meeting's "20 joints" (the AI lane) and
">32 + a spine node" (wenzhen's notes) are both really asking for *the right topology, not more dots*.

**SMPL** answers this directly: a 24-joint kinematic tree rooted at the pelvis with a true
3-joint spine (`spine1→spine2→spine3`), neck, head, and collars. It is retargetable, it is the
output format of every current monocular method, and it comes with public ground-truth datasets
for measuring accuracy.

## 3. Decisions (locked 2026-07-23)

| Fork | Decision | Rationale |
|---|---|---|
| Camera | **Monocular now, architected for multi-view** | Single-view test clips available today; multi-cam capture starts later. Seam via a source-agnostic schema. |
| Output | **SMPL body model** | Real spine + valid tree; retargets to Unity; has GT datasets. |
| Engine | **WHAM** | Video-based: temporally smooth SMPL **+ global root trajectory**, so the twin travels across the floor. Runs on Colab. |
| Unity | **Procedural SMPL-tree skeleton** | Extend the existing renderer to the 24-joint tree (adds pelvis/spine/neck bones). Drop-in; no rigged avatar needed yet. |
| Compute | **SMPL inference on Colab**, Unity local | This laptop has no NVIDIA GPU (Intel Iris Xe). |
| Footage | **Pexels stock (qualitative) + EMDB/3DPW (accuracy)** | See it work today; measure it on SMPL-GT benchmarks. AIST++ reserved for the multi-view phase. |

## 4. Architecture

```
data/raw/test_N.mp4  (monocular RGB, one person)
        │
        ▼  [Colab notebook: tools/colab/wham_extract.ipynb]
   WHAM: person detect+track → per-frame SMPL (θ pose, β shape, global orient, transl)
        │  + SMPL joint regressor → 24 3D joint positions
        │  + Python coordinate conversion  (WHAM world frame → Unity: Y-up, meters, RH→LH)
        ▼
data/skeleton/test_N.skeleton.json   (schema_version "2.0" — see §5)
        │
        ├──────────────► [Unity] SmplSkeletonDriver → procedural 24-joint twin WITH spine
        │                 (reuses SkeletonRenderer pattern; helper objects at scene root)
        │
        └──────────────► [Colab/local] tools/eval_pose.py → MPJPE / PA-MPJPE vs EMDB/3DPW GT
```

**Multi-view seam:** `skeleton.json v2` holds the SMPL tree *regardless of producer*. Monocular
WHAM writes it now; a future Pose2Sim/EasyMocap triangulation step writes the **same file**.
The Unity consumer and the accuracy harness never change — only the producer swaps.

## 5. skeleton.json v2 — schema (superset of v1)

Keeps v1's **flat float array** so Unity `JsonUtility` still parses with no extra packages;
adds the SMPL tree + params. New/changed fields marked ✚/✎.

```jsonc
{
  "schema_version": "2.0",              // ✎
  "video_id": "test_N",
  "source":     { "type": "monocular_rgb", "fps": 30.0, "resolution": [w,h], "rotate": 0 }, // ✎
  "extractor":  { "pose": "wham-<ver>", "model": "...", "notes": "world-grounded SMPL, smoothed" }, // ✎
  "coordinate_system": "unity",         // Python does the frame conversion, never Unity
  "skeleton":   "smpl-24",              // ✚ topology id
  "joint_names": [ /* 24 SMPL names, index order — §5.1 */ ],   // ✎
  "parents":     [ -1,0,0,0,1,2,3,4,5,6,7,8,9,9,9,12,13,14,16,17,18,19,20,21 ], // ✚ bone tree
  "betas":       [ /* 10 SMPL shape params, constant per subject */ ],          // ✚
  "frames": [
    {
      "frame_id": 0,
      "time": 0.0,
      "joints_flat": [ /* 24 × [x,y,z,conf] = 96 floats, Unity-facing (drop-in with renderer) */ ], // ✎ 24 not 33
      "root_world":  [x,y,z],           // ✚ global translation (twin travels)
      "root_court_xz": null,            // reserved: court placement is a later step
      "smpl": {                          // ✚ params for downstream / avatar retarget (renderer ignores)
        "global_orient": [3],
        "body_pose":     [69],           // 23 joints × 3 axis-angle
        "transl":        [3]
      }
    }
    // ...
  ]
}
```

### 5.1 SMPL-24 joint order (fixed contract)
`pelvis, left_hip, right_hip, spine1, left_knee, right_knee, spine2, left_ankle, right_ankle,
spine3, left_foot, right_foot, neck, left_collar, right_collar, head, left_shoulder,
right_shoulder, left_elbow, right_elbow, left_wrist, right_wrist, left_hand, right_hand`

Spine chain = `pelvis(0) → spine1(3) → spine2(6) → spine3(9) → neck(12) → head(15)`.

## 6. Components to build

1. **`tools/colab/wham_extract.ipynb`** — Colab notebook: install WHAM + deps, download the
   user-provided SMPL model, run WHAM on an uploaded/linked clip, apply the Python
   coordinate conversion, write `test_N.skeleton.json` v2. (Runs on Colab's GPU.)
2. **`tools/smpl_to_skeleton.py`** — the pure-Python conversion (SMPL params + regressed joints →
   v2 JSON, frame conversion, smoothing hooks). Importable by the notebook and unit-testable
   locally with a saved WHAM output (no GPU needed to test the *conversion*).
3. **`Assets/Scripts/SkeletonPlayer/SmplSkeletonDriver.cs`** — reads v2, builds a 24-joint
   procedural skeleton using `parents` for bones, includes pelvis/spine/neck, drives it per
   frame. Reuses the existing SkeletonRenderer/TwinDriver patterns; **helper objects at scene root**
   (SkeletonRenderer.Clear() destroys twin children on clip load).
4. **`tools/eval_pose.py`** — load v2 + a dataset's SMPL GT, align, report **MPJPE / PA-MPJPE**
   per joint. The accuracy deliverable; badminton-free.
5. **Docs** — a short `tools/README` entry + a `docs/for-claude/PROGRESS.md` ledger line when it lands.

## 7. Scope

**In (v1 of this feature):** one monocular clip → WHAM → v2 JSON → procedural spined twin in
Unity → accuracy numbers on one EMDB/3DPW clip. Run on one Pexels clip (qualitative) first.

**Out (later, seam left open):** multi-view triangulation (Pose2Sim/EasyMocap — same schema);
court placement of the moving root (reuse existing homography); avatar/Humanoid retarget;
hands/face (SMPL-X); racket; badminton fine-tuning; near-live/in-Unity inference.

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| WHAM Colab setup friction (deps/CUDA) | Pin versions in the notebook; keep 4D-Humans as a documented fallback engine (same v2 output). |
| **SMPL model license** — files require a free account at `smpl.is.tue.mpg.de` | **wenzhen registers and downloads** (account creation is his to do); notebook consumes the file he uploads. |
| Coordinate-frame mismatch (WHAM world → Unity) | Encode the conversion in one place (`smpl_to_skeleton.py`); unit-test on a known T-pose; visual check in Unity. |
| `JsonUtility` chokes on nested `smpl` block | Unity payload is the flat `joints_flat` + `parents`; the `smpl` block is optional and ignored by the renderer. |
| Global trajectory drift on long clips | Start with short clips (2–5 s of a single movement); WHAM's world grounding is designed for this. |

## 9. Success criteria

- A Pexels clip yields a Unity twin that **moves across the floor with a visible, articulated spine**.
- `eval_pose.py` prints per-joint MPJPE/PA-MPJPE on an EMDB/3DPW clip (numbers, not just a render).
- Swapping the producer (mono → multi-view) would require **no change** to the Unity driver or eval.
