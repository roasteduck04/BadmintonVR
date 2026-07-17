# Muscle-usage analysis — PLAN ONLY (2026-07-17)

Goal (user, 2026-07-17): *"since the project is about muscle injury in
badminton, i want to be able to see what muscles is being used when doing
certain movement."* This doc is the **plan**; nothing here is built yet.

This un-parks the injury/biomechanics thread deliberately and narrowly: the
target is **which muscles are working during a movement**, visualised on the
twin — not clinical injury prediction.

## The honest constraint first

A monocular phone video cannot measure muscle activation. Nothing downstream
changes that. What we CAN do is a chain of estimates, each with a real error
bar:

```
video → 2D pose → 3D pose (est.) → joint angles (est.) → joint moments (est.)
      → muscle activations (est., needs a musculoskeletal model)
```

Every arrow multiplies error. So the plan is staged by **what each stage can
honestly claim**, and stage 1 is already useful for coaching-style feedback
without claiming anything medical.

## Prerequisites (must land first)

- **Pose quality**: Steps 1–3 of `docs/ai-smoothing-plan.md`. Joint *angles*
  are far more sensitive to jitter than joint *positions* — a 2 cm elbow
  wobble is invisible on screen but swings the elbow angle several degrees,
  and moments differentiate that noise twice. Temporal lifting (Step 3) is
  effectively a hard requirement, not optional.
- **Racket**: Steps A–D of the racket tie-in. Racket mass (~85 g) and its
  swing position are what load the shoulder/forearm; without racket pose the
  arm moments are guesswork.
- **Track B driver**: gives continuous, constant-bone-length motion — the
  input any biomechanics stage assumes.

## Stage 1 — kinematics ("what the body did") — local, cheap

Deliverable: `tools/analyze_movement.py` + a Unity readout.
- Joint angles per frame from the twin: shoulder flexion/abduction/rotation,
  elbow flexion, wrist flexion/deviation (Step A's hand landmarks make this
  possible), hip/knee/ankle flexion, trunk rotation/lean.
- Angular velocities/accelerations (smoothed derivatives).
- **Movement segmentation**: detect strokes (racket-speed peaks) and
  footwork (lunge, jump, recovery) so results are reported *per movement*,
  which is what the request actually asks for.
Claim level: descriptive, defensible. Already useful.

## Stage 2 — muscle *involvement* heuristic — local, cheap, honest

Not a simulation: a documented mapping from joint action → prime movers,
weighted by joint angular effort. E.g. shoulder internal rotation during a
smash → subscapularis/pec major/lat; elbow extension → triceps; wrist
pronation → pronator teres; landing knee extension (eccentric) → quadriceps;
push-off → gastroc/soleus/glutes.
- Unity: **highlight the muscle groups on the avatar**, intensity ∝ estimated
  effort, with a per-movement bar readout. This is the visual the user wants.
- Must be labelled *indicative, rule-based* in the UI. It shows which muscles
  are **involved**, not how hard they fire.
- Eccentric/concentric flag from the sign of joint power — worth calling out,
  since eccentric load (landing, deceleration) is where badminton injuries
  concentrate.

## Stage 3 — inverse dynamics → real muscle estimates — Colab

[OpenSim](https://simtk.org/projects/opensim) (or the differentiable
alternative, [MyoSuite]/OpenSim-Moco) with a standard upper+lower-limb model:
- Scale the model to the player, feed joint angles → **inverse kinematics** →
  **inverse dynamics** (joint moments) → **static optimisation** → per-muscle
  activation estimates.
- Needs: mass/height input, ground-reaction estimation (we have no force
  plate — this is the weak link; contact modelling or a GRF-prediction net),
  racket as an added segment mass.
- Runs offline on Colab; result written back as a `muscle` block in
  `skeleton.json` (schema minor bump).
Claim level: estimates with stated assumptions. This is the level real papers
publish at — and where "which muscles, how much" becomes defensible.

## Stage 4 — validation against ground truth (the part that makes it research)

[MultiSenseBadminton](https://www.nature.com/articles/s41597-024-03144-z)
(GIST + MIT CSAIL, *Scientific Data* 2024) is the missing ruler: 23 hours,
25 players of varying skill, with **EMG (real muscle activation)**, full-body
IMU motion, foot pressure and gaze — focused on forehand clear and backhand
drive.
- Use it to **check our estimates against measured EMG** on the same stroke
  types: run Stages 1–3 on their motion data, correlate our estimated
  activations against their EMG channels.
- If correlation is decent, our video-only estimates have a stated accuracy —
  that is the publishable claim, and the honest basis for any injury talk.
- Stretch: train a direct **motion → EMG regressor** on their data and run it
  on our twin, skipping OpenSim entirely. Attractive (fast, no GRF problem),
  but only credible after Stage 4's correlation exists.

## What this plan will NOT claim

No injury prediction, no diagnosis, no "you are at risk" output. The defensible
end state is: *"this movement loaded these muscle groups, eccentrically, at
roughly this relative intensity, estimated from video with known error"* —
plus known risk-factor flags from the literature (e.g. landing knee valgus,
excessive shoulder external rotation at cocking).

## Order

| Stage | Where | Effort | Do when |
|---|---|---|---|
| 1 kinematics + segmentation | local | M | after ai-smoothing Step 1–2 |
| 2 involvement heuristic + Unity highlight | local | M | right after 1 — the visual payoff |
| 3 OpenSim inverse dynamics | Colab | L | when pose is lifted (Step 3) + racket fused |
| 4 EMG validation (MultiSenseBadminton) | Colab | L | after 3 — turns estimates into claims |

## Open questions for the user (not blocking the plan)

1. **Which movements matter most?** Smash/clear (shoulder-elbow, overhead) vs
   lunge/landing (knee-ankle)? The stroke set decides which model half to
   invest in — and MultiSenseBadminton only covers forehand clear + backhand
   drive, so those two are the cheapest to validate.
2. **Is a real EMG capture ever in scope** (own body, cheap sensor), or is
   published data the only ground truth we will use?
3. **Injury framing**: is the eventual output for a coach (technique
   feedback), or a research claim about load? That changes Stage 4's bar.
