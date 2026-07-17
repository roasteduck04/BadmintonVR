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

## Step 2.5 — foot locking (Unity, local)

Root position (homography) and pose (MediaPipe) are computed independently, so
the feet slide while "walking" — the classic ice-skating artifact, and a big
part of why the twin doesn't feel human.

- Detect a **planted foot**: low world-space velocity + near floor height for
  N frames.
- While planted, **pin** that foot's world position; distribute the correction
  up the leg / into the root so the body still follows the extracted path on
  average.
- Release the pin when the foot's target moves away faster than a threshold
  (step taken).
Acceptance: no visible skating in the walking sections of test_3/test_5
side-by-side (Video Compare); root path deviates < ~10 cm from the extracted
trail.

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

## Racket tie-in (Phase 2.5 — in progress)

### Step A (DONE 2026-07-17) — wrist articulation, no detection needed
The racket was welded to the elbow→wrist line, which is wrong by 60–90°
during shots — the wrist is a joint, and MediaPipe already gives us hand
landmarks we weren't using. `RacketVisual` now orients the shaft by blending
the forearm line toward the **wrist→knuckle-midpoint** direction
(landmarks 18/20 right, 17/19 left), and rolls the string bed using the palm
normal (cross product of the two knuckle rays). `handInfluence` (0..1, default
0.85) trades articulation against hand-landmark jitter; falls back to the
forearm line when hand confidence < cutoff. Still an ESTIMATE — but an
articulated one, and the baseline detection gets judged against.

### Step B (DONE 2026-07-17) — zero-shot probe: `tools/detect_racket.py`
COCO "tennis racket" (class 38, yolov8s, imgsz 1280, conf 0.10, every 15th
frame, CPU) on our own footage:

| clip | frames sampled | with detection | hit rate | best conf |
|---|---|---|---|---|
| test_3 | 99 | 90 | **90.9%** | 0.91 |
| test_4 | 65 | 31 | 47.7% | 0.86 |
| test_5 | 95 | 61 | 64.2% | 0.92 |

Verdict: **zero-shot works** — verified by eye on overlays, boxes are on the
real racket (incl. a raised mid-swing racket at 0.86). Two caveats:
- duplicate boxes on the same racket (~half of hits) → keep the highest-conf
  box nearest the detected wrist, not raw output.
- test_4 is weakest (player further away / more blur) → the misses are the
  fast-swing frames, exactly the ones we care about most.
No own-data gathering, no fine-tune needed to start.

### Step C (next) — fuse detection with the arm prior
Per frame: take the best box near the wrist → box center + long axis give a 2D
racket direction → correct the Step-A estimate (which supplies 3D depth the
box cannot). Gaps (test_4's blurred swings) fall back to the arm estimate, so
the racket never disappears. Write into `skeleton.json` as a `racket` block
(schema minor bump, Unity contract preserved).

### Step D (later) — RacketVision for true racket pose
[RacketVision](https://github.com/OrcustD/RacketVision) (AAAI 2026 Oral, MIT
licence) is exactly this problem, already solved on 1,672 clips / 435k frames
of badminton+tennis+table-tennis: **5 racket keypoints** (top, bottom, handle,
left, right) via a two-stage detect→RTMPose-M pipeline, with **pretrained
checkpoints** (`download_checkpoints.py`) and badminton configs. Dataset on
HuggingFace `linfeng302/RacketVision`. Plan: run their pretrained RacketPose on
our frames **on Colab** (no GPU here), export keypoints per frame, and use them
instead of the box in Step C — 5 keypoints give real racket *orientation and
roll*, not just position. Only fine-tune if their zero-shot transfer to our
void-deck footage is poor.

## Track B — persistent twin driver (agreed 2026-07-17)

Architecture shift, complementary to Steps 1–3 (they clean the DATA; this
changes how the data DRIVES the body). Today the twin is rebuilt/teleported
per frame from raw joints. Instead: spawn ONE model at first detection and
keep it alive; every new capture frame is a **target it moves toward**, so
continuity (constant bones, momentum, ground contact) is structural, not
filtered in afterwards.

Decisions (user, 2026-07-17):
- **Both bodies, switchable**: the driver feeds either the skinned humanoid
  (`character.fbx` via the humanoid rig — the "actual model") or the stick
  figure; a toggle switches, so raw vs driven can be compared directly.
- **Springs + IK goals**: root and limb end-effectors (hands/feet, head)
  chase their targets with critically-damped springs; elbows/knees are
  solved by IK (Animation Rigging / humanoid rig), so intermediate joints
  look human even when MediaPipe is noisy. Physics ragdoll = later
  experiment, not first.
- **Lookahead allowed, as a setting**: clips are recorded files, so the
  driver may peek ~0.2–0.5 s ahead and steer toward where the player is
  GOING — smoothness without lag. Exposed as `lookaheadSeconds` (0 = causal)
  because Phase 5 near-live cannot look ahead.

Foot locking (Step 2.5) folds into this driver naturally: a planted foot is
just an IK goal that stops moving.

Acceptance: side-by-side raw vs driven on test_3/test_5 — no teleports, no
skating, constant limb lengths, and lunges arrive on time (lookahead
compensates the spring lag).

## Order & effort

| Step | Where | Effort | Do when |
|---|---|---|---|
| 0 measure | local | S | first |
| 1 One-Euro + gap fill | local | M | right after 0 |
| 2 Kalman + gating | local | M | after 1 |
| 2.5 foot locking | local (Unity) | M | after 2 — kills the ice-skating |
| 3 temporal lifting | Colab | L | when pose quality is the bottleneck |
| 4 better backbone | Colab | L | only if 3 isn't enough |
