# Research Direction: Video to Biomechanical Simulation to Injury Analysis for Badminton

**OpenCap + Muscles in Action + OpenSim Moco** — May 2026

---

## 1. The Research Agenda

We propose a single end-to-end study with four stages, each producing an independent, publishable result:

**Stage 1. Video → skeleton joint kinematics (OpenCap on badminton).**
Run OpenCap on badminton video to extract 3D joint angles and moments. Validate against IMU-derived kinematics from the MultiSenseBadminton dataset [5].
> **Result:** A quantified error budget for video-derived badminton biomechanics — which joints are reliable, which degrade under fast motion (smash, lunge).

**Stage 2. Video → predicted muscle activations (MIA on badminton).**
Apply the Muscles in Action model [3] to the same badminton video. Compare predicted muscle activations against actual surface EMG from MultiSenseBadminton. Fine-tune on badminton-specific data if the off-the-shelf model does not transfer.
> **Result:** The first measurement of whether video-derived muscle activation generalizes to a racket sport.

**Stage 3. Kinematics + muscle activations → musculoskeletal simulation (OpenSim Moco).**
Feed the Stage 1 kinematics and Stage 2 muscle predictions into OpenSim Moco [2] to compute joint forces, torques, and muscle loads. Run counterfactual what-if scenarios: what happens to shoulder torque if elbow angle changes by 5° during a smash?
> **Result:** Physics-grounded load estimates for badminton strokes, with counterfactual analysis that coaches can inspect.

**Stage 4. Simulated loads → injury risk indicators → validation.**
Compare simulated joint loads against published injury-biomechanics thresholds for badminton (shoulder internal rotation torque in smash, knee valgus moment in lunge, eccentric hamstring loading in recovery). Validate the full pipeline end-to-end against MultiSenseBadminton sensor ground truth.
> **Result:** A validated injury-risk indicator framework grounded in simulation, not statistical classification.

The VR/game component the stakeholders want sits downstream of this pipeline: it consumes the engine's outputs (muscle maps, load indicators, counterfactual comparisons) as a visualization and feedback layer. It is not the research.

---

## 2. Why This Pipeline and Not the Alternatives

Existing work in this space falls short in specific ways:

- **VRBT [4]** builds a VR badminton trainer with injury alerts, but its injury model (EIPS) is a random-forest/XGBoost classifier on pose features. No physics, no muscles, no simulation. High reported AUC (0.953) but no description of injury label provenance, which is exactly the label-quality problem the literature warns about.

- **MultiSenseBadminton [5]** provides the richest public badminton dataset (7,763 swings; IMU, EMG, foot pressure, video; 25 players at 3 skill levels) but does not connect it to simulation or injury analysis. We use it as validation ground truth for every stage of our pipeline.

- **Jin & Li [6]** classify 6 stroke types at 97% from two IMUs. Useful as a stroke segmenter to trigger our biomechanical analysis on specific strokes, but no connection to biomechanics or injury.

- **Meta BTS** is a commercial VR badminton game. Market validation for the stakeholders' game interest, not research.

---

## 3. What We Need and What We Already Have

| Need | Source | Status |
|---|---|---|
| Badminton video + EMG + IMU ground truth | MultiSenseBadminton (Figshare) | Public, downloadable now |
| Video-to-muscle model | MIA (Columbia, GitHub) | Open code + pretrained weights |
| Video-to-kinematics | OpenCap (Stanford) | Open source |
| Musculoskeletal simulation | OpenSim Moco | Open source |
| Motion priors | AMASS | Available |
| Stakeholder badminton video | Michael / Fiona program | After Phase 0 gate |

Everything needed to prototype and validate Stages 1–4 is public and available now. Stakeholder data enters only after gate closure, as previously agreed.

> **The gap.** OpenCap [1] gives you kinematics and dynamics from video but not muscle activations. MIA [3] gives you predicted muscle activations from video but not joint forces. Combining them through OpenSim Moco produces physics-informed muscle-force estimates from video alone — no lab, no markers, no force plates at inference time.

---

## 4. How This Fits the Existing Roadmap

This does not replace the Phase 0–3 plan. It fills the technical content of Phases 1–3:

- **Phase 1** (ingest + baseline CV): Stages 1 and 2 — validate OpenCap and MIA independently on MultiSenseBadminton.
- **Phase 2** (coach fusion): Muscle-activation maps become a new modality for coach review; stroke-level biomechanical reports aligned to coach annotations.
- **Phase 3** (sim/3D): Stages 3 and 4 — full simulation pipeline, injury indicators, counterfactuals, end-to-end validation.

Backlog item E (3D body model + deviation vs prior) is the natural home. Item G (injury prediction) is addressed through simulation rather than classifiers.

---

## 5. Risks

1. **MIA may not transfer to badminton.** Trained on general exercises (squats, lunges, punches), not racket sports. *Mitigation:* Fine-tune on MultiSenseBadminton EMG + video. Stage 2 answers this question directly.

2. **OpenCap may degrade on fast movements.** Smash racket-tip speed exceeds 300 km/h. *Mitigation:* Body-segment kinematics (shoulder, elbow, knee) are slower and more likely to remain valid. Stage 1 quantifies where the accuracy boundary is.

3. **No injury labels exist.** We do not need them. We identify biomechanical risk indicators (loads exceeding published thresholds), not statistical injury predictions. The injury-biomechanics literature provides the thresholds.

4. **Stakeholders expect a game.** Set expectations early: the research produces the biomechanical engine. A VR interface is a downstream deliverable that consumes it.

---

## References

[1] S. D. Uhlrich et al., "OpenCap: Human movement dynamics from smartphone videos," *PLOS Comput. Biol.*, 2023.

[2] C. L. Dembia et al., "OpenSim Moco: Musculoskeletal optimal control," *PLOS Comput. Biol.*, 2020.

[3] M. Chiquier and C. Vondrick, "Muscles in Action," *Proc. ICCV*, pp. 22091–22101, 2023.

[4] Y. Zhu et al., "VRBT: VR Badminton Training with Multitask Injury Alerts," *J. System Simulation*, vol. 38, no. 1, pp. 225–234, 2026.

[5] M. Seong et al., "MultiSenseBadminton: Wearable Sensor-Based Biomechanical Dataset," *Scientific Data*, vol. 11, no. 343, 2024.

[6] G. Jin and X. Li, "Wearable sensing for badminton stroke recognition with 1D-CNN," *Scientific Reports*, vol. 15, no. 41236, 2025.
