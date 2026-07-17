# Design: badminton move recognition (2026-07-17)

Approved by user 2026-07-17 ("A then B: rules now, model later"; design approved
with "create a pr and write the spec").

User goal: *"i want to be able to detect what the person is currently doing,
like of all badminton moves."* This also unblocks the muscle plan's Stage 1
(per-movement reporting needs to know which movement it was —
`docs/muscle-analysis-plan.md`).

## Decisions (user, via questions)

- **Move set:** start coarse, expand later. v1 classes:
  `overhead_smash`, `overhead_clear`, `drop`, `underarm_lift`, `net_shot`,
  `drive`, plus `moving` / `idle` between strokes. Finer splits
  (forehand/backhand, jumps, footwork patterns) come after v1 works.
- **Where it runs:** offline Python labels each clip once → `moves` block in
  `skeleton.json` → Unity displays during replay. No inference in Unity.
- **Ground truth:** public datasets only for train/eval; the user's clips are
  the demo (labeled by the system, judged by eye). Optional later upgrade: a
  30 s self-announced clip would give a real accuracy number on own footage —
  not required.
- **Approach:** A then B (below), one design, same output contract.

## 1. Contract — `moves` block in skeleton.json

Optional top-level array; schema **minor version bump**; consumers must
tolerate its absence (old files keep loading).

```json
"moves": [
  {"start": 120, "peak": 138, "end": 165, "label": "overhead_clear", "confidence": 0.8},
  {"start": 166, "end": 210, "label": "moving"}
]
```

- `start`/`end`: inclusive frame range. Every frame of the clip belongs to
  exactly ONE segment (segments tile the clip; no gaps, no overlaps).
- `peak`: stroke-contact frame; present only on stroke segments.
- `confidence`: 0..1; rule-margin based (A) or model softmax (B).
- Labels are the v1 class strings above; unknown labels must not crash Unity
  (forward compatibility for finer classes).

Both Approach A and Approach B write this same block. Unity and the muscle
plan never care which produced it.

## 2. Approach A — `tools/label_moves.py` (heuristic, local CPU)

Input: a `skeleton.json` (33 MediaPipe joints × [x,y,z,conf] per frame,
`root_court_xz`). Racket hand: right (per-project default; flag to flip).

Pipeline:
1. **Stroke detection:** smooth the racket-wrist 3D speed; peaks above a
   threshold with minimum separation (~0.5 s) mark stroke moments.
2. **Segmentation:** each stroke segment spans where wrist speed rises above /
   falls back below a fraction of its peak. Between strokes: `moving` if
   root court-speed exceeds a walking threshold, else `idle`.
3. **Features at the peak:** wrist height vs shoulder/head; post-peak wrist
   velocity direction (down-fast → smash, up/forward → clear/lift); elbow
   extension; torso rotation; root distance from the net line (net_shot vs
   rear-court strokes).
4. **Rule classification** → label + margin-based confidence. Rules are
   transparent: `--report` explains every label with its feature values.
5. **Output:** `--report` printed timeline; `--overlay` debug video with the
   label burned in (gitignored — frame-bearing); `--write` inserts the
   `moves` block into `data/skeleton/<clip>.json` AND
   `Assets/StreamingAssets/skeleton/<clip>.json` (schema minor bump).

Low-confidence poses: frames whose wrist confidence < cutoff are excluded
from peak detection (no stroke can be detected on garbage), and segments are
never split by brief confidence dropouts.

## 3. Unity display

- `SkeletonDoc` parses the optional `moves` array (absent → empty; unknown
  labels pass through as raw strings).
- New `MoveLabelHUD` component + `Tools ▸ Badminton ▸ Move Label ▸ Add/Remove`
  menu (mirrors DebugHUDSetup pattern): shows the current move label +
  confidence prominently during replay, plus a compact segment timeline
  (e.g. progress bar with colored segments) in the corner. OnGUI like
  PipelineDebugHUD; Input-System-guarded toggle key (M).
- It is a subtitle track: zero inference, zero per-frame allocation.

## 4. Approach B — trained classifier (Colab, later, separate round)

- **Step 0 (verify before anything):** confirm VideoBadminton
  (arXiv 2403.12385) download access + license; fallback: ShuttleSet.
- Preprocess on Colab: run OUR MediaPipe extraction over their clips so
  training data is in our exact skeleton format (camera-invariant-ish,
  and no domain gap from a different pose estimator).
- Train a small temporal classifier (TCN / ST-GCN class) on stroke windows;
  augment (mirror, small rotations, speed jitter). Export ONNX.
- `label_moves.py --model x.onnx`: replaces ONLY the rule-classification step
  (segmentation stays heuristic); onnxruntime CPU locally.
- Eval: confusion matrix on held-out public data, committed to the repo.
  The same ONNX is the Phase-5 live candidate (Sentis).
- Class mapping: their fine classes → our v1 classes for comparison; expand
  our class list only when the model beats the rules on the confusions that
  matter (smash/clear, drop/net).

## 5. Acceptance

Approach A, on test_3/4/5:
- Timeline reads correctly against Video Compare by eye (user judgment).
- ≥90% of frames covered by segments (tiling invariant is actually a hard
  100% by construction — the 90% figure is for non-`idle` misc coverage
  sanity).
- No stroke segment shorter than 0.2 s or longer than ~2 s.
- smash↔clear and drop↔net confusions are ALLOWED at this stage — fixing
  them is Approach B's job and its success metric.
- Muscle-plan Stage 1 can consume the segments as-is.

## Out of scope (v1)

Footwork classification (lunge/split-step/jump), forehand/backhand splits,
serve detection, shuttle tracking, live in-Unity inference.
