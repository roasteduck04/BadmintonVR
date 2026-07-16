# AI plan: smoother, more confident pose & position

Goal: raise the **smoothness** (no jitter/teleporting) and **confidence**
(trustworthy joints and court position) of the twin, in steps that each pay off
on their own. Constraint: this laptop has no NVIDIA GPU — everything local must
run on CPU; anything heavier goes to Colab.

## Where we are (2026-07-16)

Already in the pipeline:
- MediaPipe world landmarks, **confidence-gated + Savitzky–Golay smoothed**
  (`extract_skeleton.py`) — pose level.
- Unity-side root `Lerp` smoothing + confidence cutoff (`SkeletonPlayback`).
- Multi-keyframe homography for moving cameras; extraction clamps at
  ±4.55 m X / ±8.20 m Z.

Known weaknesses (visible in the Debug HUD):
- Root position jitters at the **far baseline** (perspective blow-up: tiny pixel
  error = big meters — camera height issue, not fixable in software alone).
- Low-confidence stretches (occlusion, motion blur) make joints pop in/out.
- Unity's Lerp smoothing adds lag proportional to smoothness.

## Step 0 — measure first (local, ~1 evening)

`tools/measure_quality.py`: per-clip report so every later step proves itself.
- **Jitter**: mean |Δposition| per frame for root XZ and each joint (m/frame).
- **Confidence**: mean/min per joint, % frames below cutoff, gap lengths.
- **Position sanity**: % in court box, clamp hits, max speed (humans < ~5 m/s).
Acceptance: numbers for test_1..test_5 in a table, committed.

## Step 1 — confidence-weighted filtering (local, CPU, biggest win/effort)

In `extract_skeleton.py`, replace plain Savitzky–Golay with:
1. **Gap fill**: interpolate joints/root across low-confidence stretches
   (< ~0.5 s) instead of holding/popping.
2. **One-Euro filter** on root XZ (speed-adaptive: still when slow, responsive
   when lunging — beats fixed Lerp; then lower Unity `rootSmoothing` toward 0).
3. Weight samples by confidence so a c=0.2 frame can't drag a c=0.9 neighbor.
Acceptance: jitter down ≥30% on test_3/test_5 with no visible lag in
side-by-side (Video Compare).

## Step 2 — Kalman + physics gating on court position (local, CPU)

Constant-velocity **Kalman filter** on root XZ:
- Measurement noise scaled by root confidence AND by distance from camera
  (far-baseline measurements trusted less — this directly targets the
  perspective blow-up).
- **Gate outliers**: reject frames implying > ~6 m/s or teleports; predict
  through them. Clamp hits become rejected measurements instead of data.
Acceptance: zero visible teleports; clamp-marker frames no longer bend the
trail (check in Debug HUD).

## Step 3 — temporal 3D pose lifting (Colab GPU, export back)

Per-frame MediaPipe ignores time. A temporal lifter (MotionBERT / VideoPose3D
class) takes the whole 2D keypoint sequence and outputs smooth, consistent 3D:
- Runs offline on Colab over exported 2D keypoints; writes back into
  `skeleton.json` (bump schema minor version, keep Unity contract).
- Expected: biggest visual quality jump for the pose itself (no more rubber
  arms during fast swings).
Acceptance: side-by-side old/new clip; joint jitter down again; limb lengths
near-constant across frames (new metric in Step 0's script).

## Step 4 — stronger 2D backbone (Colab, optional)

Swap/augment MediaPipe with RTMPose/ViTPose (ONNX) batch-run on Colab. Only if
Step 3 still leaves pose errors — measure first. Feeds Phase 4 (badminton
fine-tune) later.

## Racket tie-in (next phase, runs in parallel)

The racket is currently **arm-estimated** in Unity (elbow→wrist). Detection
path, cheapest first:
1. Zero-shot: COCO "tennis racket" class of an off-the-shelf YOLO on
   test_3/4/5 frames (CPU-tolerable at low fps offline).
2. If weak: fine-tune on Roboflow community badminton-racket data (Colab),
   or auto-label own frames with an open-vocab detector (YOLO-World).
3. Fuse: arm direction gives 3D orientation prior, detection corrects it;
   RacketVision-style racket keypoints are the long-term reference.

## Order & effort

| Step | Where | Effort | Do when |
|---|---|---|---|
| 0 measure | local | S | first |
| 1 One-Euro + gap fill | local | M | right after 0 |
| 2 Kalman + gating | local | M | after 1 |
| 3 temporal lifting | Colab | L | when pose quality is the bottleneck |
| 4 better backbone | Colab | L | only if 3 isn't enough |
