# Video-to-Skeleton Badminton Analysis for Simulation-Oriented Player Movement Reconstruction

**Research Note** — Prepared for professor review and project direction planning  
**Date:** 9 June 2026

> **Purpose of this note:** This research note explains the current state of badminton video-analysis research and translates it into a practical research direction for our project: using tournament/internet videos first, then controlled video recordings, to extract player skeletons and movement information for a badminton simulation. The note is designed to help professors understand (1) what has already been done, (2) which papers are most relevant, (3) what the research gap is, and (4) how the existing work can be extrapolated into a proof-of-concept simulation pipeline.

---

## Table of Contents

1. [Purpose and Research Positioning](#1-purpose-and-research-positioning)
2. [Executive Thesis](#2-executive-thesis)
3. [Current Research Landscape](#3-current-research-landscape)
4. [Deep Dive: BST as the Anchor Source](#4-deep-dive-bst-as-the-anchor-source)
5. [Supporting Sources and How They Extend the Pipeline](#5-supporting-sources-and-how-they-extend-the-pipeline)
6. [Proposed Extrapolated Methodology for Our Project](#6-proposed-extrapolated-methodology-for-our-project)
7. [Camera-Angle and Data-Source Recommendations](#7-camera-angle-and-data-source-recommendations)
8. [Evaluation Plan](#8-evaluation-plan)
9. [Risks, Limitations, and Ethical/Practical Constraints](#9-risks-limitations-and-ethicalpractical-constraints)
10. [Recommended Research Direction](#10-recommended-research-direction)
11. [References](#references)

---

## 1. Purpose and Research Positioning

The project has pivoted from a broad badminton injury/technique-detection idea toward a more focused computer-vision and simulation problem: extracting player movement from badminton video and converting it into a skeleton representation that can be used inside a simulation environment. The short-term data source will be public tournament or internet video, because it enables rapid proof-of-concept development without requiring immediate access to players, sensors, or a full recording setup. The longer-term plan is to record controlled badminton footage with camera angles chosen specifically for pose estimation, court mapping, shuttle tracking, and 3D motion reconstruction.

The core research question is: **can existing badminton video-analysis methods be extended from stroke recognition and tactical annotation into a pipeline that reconstructs court-relative player skeleton motion for simulation?** This is not the same as ordinary action classification. Action classification asks *"what stroke is this?"* Our direction asks *"how can the player's body movement, court position, and shuttle context be represented well enough to animate and evaluate movement in a simulated badminton court?"*

The most important distinction for the professors is that current research has solved pieces of the problem, but not the full pipeline. BST shows that broadcast badminton video can be processed into player skeletal joints, shuttle trajectory, and court/player positions for stroke classification. VideoBadminton shows how to record a clean badminton action-recognition dataset. MonoTrack shows how shuttle trajectory can be reconstructed from monocular video. OpenCap and OpenCap Monocular show that video-based movement reconstruction can be connected to 3D kinematics and biomechanics. The research opportunity is to connect these pieces into a simulation-ready movement reconstruction workflow.

---

## 2. Executive Thesis

BST should be treated as the anchor source for this research note because it is closest to our intended pipeline: broadcast badminton video is clipped around strokes, human pose estimation is used to obtain skeletal joints, shuttle trajectory and court-line/player-position information are extracted, and a transformer-based model classifies stroke types. However, BST does not produce a final rigged 3D avatar or simulation-ready skeleton. Its output remains a stroke-classification result based on extracted 2D/3D pose and context features. Therefore, our contribution should be framed as an extension beyond BST: from video-based stroke understanding toward court-relative, skeleton-based motion reconstruction for simulation.

VideoBadminton remains highly important, but for a different reason. It should be used as the main source for controlled recording methodology: camera height, camera position, frame rate, lens calibration, and badminton action labels. The note should not claim that VideoBadminton is the best skeleton-from-video source; it is better understood as a dataset-design and camera-capture reference.

| Rank | Source | Primary Value | Why It Matters | Main Limitation |
|------|--------|--------------|----------------|-----------------|
| 1 | **BST: Badminton Stroke-type Transformer** | Anchor source for skeleton-from-video badminton analysis | Uses broadcast match video, pose estimation, shuttle tracking, court detection, and player positions for stroke classification. | Does not output simulation-ready 3D avatar motion. 3D pose is explored but 2D joints perform better. |
| 2 | **VideoBadminton** | Controlled camera and dataset design source | Gives concrete recording setup, 60 fps footage, 18 action labels, OpenCV distortion correction, and benchmarked action-recognition models. | Mostly action recognition, not simulation or 3D motion reconstruction. |
| 3 | **MonoTrack** | Shuttle trajectory source | Supports shuttle trajectory reconstruction from monocular broadcast-style badminton video. | Focuses on shuttle, not full player skeleton or biomechanics. |
| 4 | **ShuttleSet / ShuttleSet22** | Stroke-level annotation source | Provides large-scale stroke-level match annotations, player locations, hitting locations, and tactical labels. | Not primarily a pose/simulation dataset. |
| 5 | **BFMD** | Emerging full-match dense annotation source | Adds full-match multimodal annotations including shot types, shuttle trajectories, player pose keypoints, and shot captions. | Very recent and captioning-focused; not yet a complete skeleton-to-simulation pipeline. |
| 6 | **OpenCap / OpenCap Monocular** | 3D biomechanics extrapolation source | Shows video-based human movement can be converted into 3D kinematics/dynamics and clinically relevant movement metrics. | Not badminton-specific and may need validation for high-speed court movement. |

---

## 3. Current Research Landscape

The current research landscape can be divided into five overlapping areas: badminton-specific stroke recognition, badminton video dataset construction, shuttle trajectory reconstruction, stroke-level tactical annotation, and general video-based 3D human movement reconstruction. Our project sits at the intersection of these areas. The strongest argument is not that one paper solves the full problem; rather, the literature now contains enough components to justify building and evaluating an integrated video-to-skeleton-to-simulation pipeline.

| Research Area | Representative Source | What Current Research Outputs | How We Extrapolate It |
|---|---|---|---|
| Badminton-specific skeleton and stroke recognition | BST | Broadcast match video; human pose joints; shuttle trajectory; player/court positions; stroke label output. | Directly supports proof of concept from tournament/internet video. |
| Controlled badminton video dataset design | VideoBadminton | Self-recorded practice footage; 7,822 clips; 18 action classes; 60 fps; camera behind baseline; calibration. | Guides our later controlled recording setup and label taxonomy. |
| Shuttle trajectory reconstruction | MonoTrack | Monocular video; court dimensions; shuttle tracking; hit recognition; physics-based trajectory fitting. | Adds shuttle context to player skeleton movement; important for realistic simulation. |
| Stroke-level tactical data | ShuttleSet / BadmintonDB / ShuttleSet22 | Rallies, strokes, shot types, player locations, hitting locations, outcomes. | Provides structured labels and match context for supervised training and evaluation. |
| Dense full-match understanding | BFMD | 19 broadcast matches; 20+ hours; rallies; hit events; shot captions; shuttle trajectories; player pose keypoints. | Useful for future full-match video understanding and multimodal annotation. |
| Human movement biomechanics from video | OpenCap / OpenCap Monocular | 2+ smartphone or single smartphone video; 3D kinematics; forces; musculoskeletal dynamics. | Provides a pathway from pose extraction to injury/biomechanical metrics. |

---

## 4. Deep Dive: BST as the Anchor Source

BST is the strongest anchor paper for this note because it directly addresses the same starting condition as our proof of concept: badminton broadcast match video. The paper identifies badminton-specific computer-vision challenges including player identification, court-line detection, shuttlecock trajectory tracking, and player stroke-type classification. Instead of relying only on RGB appearance, BST processes stroke clips through human pose estimation, shuttle tracking, and court/player-position extraction before classifying stroke type.

### 4.1 What BST Does

- **Input:** Badminton singles broadcast match video.
- **Stroke clipping:** The match is segmented into stroke clips around hit frames. The clipping strategy is designed to include the target stroke and surrounding opponent strokes so that the model sees relevant pose and trajectory context.
- **Pose extraction:** MMPose is used with RTMPose for 2D pose estimation and MotionBERT for 3D pose estimation. The authors ultimately use 2D poses because they perform better for downstream stroke classification.
- **Court and player position extraction:** Court lines are used to filter irrelevant people and determine the two players' positions. MonoTrack or a court detector is used where court-line information is not already available.
- **Shuttle trajectory extraction:** The shuttlecock trajectory is treated as a key input rather than a minor auxiliary cue.
- **Model:** Player joints/bones, shuttle positions, and player positions are fed into a transformer-based model to classify stroke type.
- **Output:** Stroke-type classification, not a full animation-ready 3D motion file.

### 4.2 Why BST Matters for Our Project

BST is valuable because it proves that passive badminton broadcast video can be converted into structured intermediate representations: player joints, shuttle trajectory, court positions, and stroke clips. Those intermediate representations are exactly the kind of inputs our project needs before building a simulation. For our purposes, the most important output is not the final stroke label; it is the extraction pipeline that precedes the label. That pipeline can be repurposed as a data preparation layer for simulation.

The BST results also show that skeleton-only human-action recognition is insufficient for badminton. Player pose alone struggles because many strokes have subtle body differences, and deception can make pose misleading. The shuttle trajectory provides critical context because it reveals what was actually hit and where the shot is going. This strongly supports our proposed data schema: **player skeleton should not be stored alone; each frame or stroke should also include court-relative player position and shuttle context.**

| BST Component | Research Significance | Project Extrapolation |
|---|---|---|
| Stroke-centered clipping | Reduces irrelevant video and centers the target action. | Clip internet/tournament rallies around hit frames before pose extraction and simulation retargeting. |
| 2D pose joints | Works better than their tested 3D pose for stroke classification. | Use 2D pose as the first reliable POC layer; do not overpromise 3D accuracy immediately. |
| Player positions | Court context improves interpretation of a stroke. | Map player skeletons into court coordinates using homography. |
| Shuttle trajectory | Critical to disambiguate stroke type and intent. | Add shuttle track as a simulated object path; use it to infer impact timing and shot type. |
| 2D vs 3D finding | General 3D pose models can fail on badminton-specific poses. | Plan badminton-specific validation and possibly multi-camera controlled capture for 3D later. |

### 4.3 BST Limitations That Our Project Must Not Ignore

- BST's final research task is stroke-type classification. It does not create a simulation-ready rig, a full-body 3D animation file, or injury metrics.
- BST relies on accurate hit-frame detection and shuttlecock trajectory tracking. If those upstream detections fail, stroke classification and any downstream simulation will also degrade.
- The paper's own 2D-versus-3D comparison is important: 3D joints performed worse than 2D joints, and an example shows incorrect body-facing direction in a badminton frame. This means a naive "lift 2D skeleton to 3D" approach is risky.
- BST focuses on singles. Doubles introduces more occlusion, more players, more player-identification complexity, and more frequent overlap between bodies and racket/shuttle paths.
- BST does not solve racket tracking, foot-ground contact, inverse kinematics, joint-angle biomechanics, or animation retargeting. These are required for a simulation pipeline.

---

## 5. Supporting Sources and How They Extend the Pipeline

### 5.1 VideoBadminton: Recording Methodology and Controlled Dataset Design

VideoBadminton is the strongest source for planning our own controlled recording environment. It provides a concrete badminton-specific capture setup: footage recorded at 1280 × 960 resolution and 60 fps using a dedicated camera placed approximately 2 meters behind the baseline, 4.5 meters high, and tilted at about 30 degrees. The authors also used wide-angle footage and corrected lens distortion through OpenCV calibration with chessboard images. This is directly useful for our camera-angle section because court-line distortion can corrupt player-position mapping and shuttle-position estimation.

VideoBadminton also gives a useful action-label vocabulary. Its 18 action classes can serve as the first version of our project's stroke taxonomy. However, because VideoBadminton mainly benchmarks action-recognition models such as SlowFast, ST-GCN, and PoseC3D, it should not be described as the best skeleton-to-simulation source. Its primary role in our project is controlled capture design, labeling, and benchmarking.

### 5.2 MonoTrack: Shuttle Trajectory and Hit-Frame Support

MonoTrack is useful because a badminton simulation cannot depend only on the player skeleton. The shuttle trajectory determines the timing, target, and tactical meaning of the player movement. MonoTrack presents an end-to-end monocular badminton pipeline for 3D shuttle trajectory extraction and segmentation, integrating badminton domain knowledge such as court dimensions, shot placement, and physical laws of motion. For our project, MonoTrack is best used as a **shuttle-context module**: it can support hit-frame detection, shuttle path reconstruction, and the simulated shuttle object path.

### 5.3 ShuttleSet and ShuttleSet22: Structured Stroke-Level Annotation

ShuttleSet is important because it shows how stroke-level badminton data can be organized at match scale. It contains annotated rallies, strokes, shot types, hitting locations, and player locations from high-level singles matches. BST uses ShuttleSet as a main benchmark, which increases its relevance for our project. For our system, ShuttleSet-like records can become the label structure around which pose and simulation data are organized: each stroke should have a hit frame, player identity, court position, stroke label, shuttle position/trajectory, and outcome context.

### 5.4 BFMD and FineBadminton: Emerging Full-Match and Multimodal Understanding

Newer work is moving beyond isolated clips toward richer full-match understanding. BFMD, submitted in 2026 and accepted to CVSports2026, describes a full-match dense badminton dataset with 19 broadcast matches, over 20 hours of play, 1,687 rallies, and 16,751 hit events. Its annotations include shot types, shuttle trajectories, player pose keypoints, and shot captions. This is highly relevant as evidence that badminton video research is moving toward dense multimodal representations, although BFMD remains captioning and understanding-oriented rather than simulation-oriented.

FineBadminton similarly reflects a move toward multi-level badminton video understanding, including tactical semantics and decision evaluation. It is less central to skeleton reconstruction than BST, but it supports the broader research trend: future badminton intelligence systems will likely combine visual, spatial, tactical, and semantic cues rather than relying on a single modality.

### 5.5 OpenCap and OpenCap Monocular: Bridge to 3D Movement and Injury Analysis

OpenCap is not badminton-specific, but it is highly important for the later injury/biomechanics part of the project. It shows that standard videos can be used to estimate 3D kinematics and musculoskeletal dynamics through pose estimation, biomechanical modeling, and physics-based simulation. OpenCap Monocular extends this direction by estimating 3D skeletal kinematics and kinetics from a single smartphone video. These systems support the claim that video-based movement analysis can move beyond classification toward biomechanically meaningful metrics. The caveat is that their validation tasks are not high-speed badminton strokes and lunges, so we would need badminton-specific validation before making strong injury-risk claims.

---

## 6. Proposed Extrapolated Methodology for Our Project

The proposed methodology is to combine the strongest parts of the current literature into a staged pipeline. The first stage should be proof-of-concept from public singles match video. The second stage should be controlled recording based on VideoBadminton-like camera placement. The third stage should convert pose trajectories into a simulation representation, and the fourth stage should evaluate technical and biomechanical metrics.

### 6.1 Proof-of-Concept Pipeline Using Tournament/Internet Video

| Stage | Method | Output |
|---|---|---|
| 1. Video selection | Select high-quality singles rally footage with a stable rear/broadcast angle, visible full court, minimal zoom/pan, and clear player separation. | Input videos suitable for court detection and pose estimation. |
| 2. Court detection | Detect or manually mark court corners and compute homography to map image coordinates to court coordinates. | Court coordinate system for player position and movement. |
| 3. Player detection/tracking | Identify the two players and track them across frames; filter spectators/referees using court position. | Player IDs and bounding boxes. |
| 4. 2D pose estimation | Use a pose-estimation model such as RTMPose/MMPose, YOLOv8-Pose, ViTPose, MediaPipe, or OpenPose. | 2D skeletal joints with confidence values. |
| 5. Shuttle tracking | Use TrackNet/MonoTrack-style methods or manual annotation for early POC clips. | 2D/3D shuttle path and candidate hit frames. |
| 6. Stroke-centered clipping | Segment around hit frames using BST-inspired clip windows. | Stroke clips with pose, shuttle, and court context. |
| 7. Skeleton cleaning | Smooth jitter, interpolate missing joints, flag occlusions, and standardize joint format. | Stable skeleton time series. |
| 8. 2.5D/3D reconstruction | Start with court-relative 2D skeleton placement; later add 3D pose estimation or multi-camera triangulation. | Simulation-ready approximate player motion. |
| 9. Simulation integration | Retarget skeleton to a simple avatar in Unity/Blender and align movement to a badminton court. | Animated player skeleton in a simulation court. |
| 10. Evaluation | Assess pose quality, stroke segmentation, visual realism, and coach/professor feedback. | Evidence that the pipeline is technically viable. |

### 6.2 Minimum Viable Data Schema

To make the pipeline useful for simulation and later analysis, each processed video should produce structured data rather than only visual overlays. A recommended minimum schema is below.

| Data Field | Purpose |
|---|---|
| `video_id` | Unique identifier for the source video or clip. |
| `frame_id / timestamp` | Frame number and time in seconds. |
| `camera_metadata` | Source type, frame rate, resolution, camera angle category, and calibration availability. |
| `court_corners_image` | Detected or manually annotated court corners in image coordinates. |
| `homography_matrix` | Mapping from image coordinates to court coordinates. |
| `player_id` | Top/bottom player or assigned track ID. |
| `pose_2d_keypoints` | 2D joint coordinates and confidence scores. |
| `pose_3d_keypoints_optional` | Estimated 3D joints if available; must include confidence and method used. |
| `player_court_position` | Player center or feet position in court coordinates. |
| `shuttle_position` | 2D or 3D shuttle position and confidence. |
| `hit_frame_flag` | Whether the frame is a detected/manual hit frame. |
| `stroke_label_optional` | Stroke type if available from dataset/manual annotation/model inference. |
| `occlusion_quality_flags` | Missing joints, player overlap, camera cut, motion blur, or shuttle occlusion. |
| `simulation_export` | Retargeted skeleton format, avatar rig mapping, and Unity/Blender import path. |

### 6.3 Practical Technical Architecture

```
Video
  → court detection / homography
  → player tracking
  → 2D pose
  → shuttle tracking
  → hit-frame / stroke clipping
  → skeleton cleaning
  → optional 3D reconstruction
  → avatar retargeting
  → simulation playback
  → technique / biomechanics metrics
```

---

## 7. Camera-Angle and Data-Source Recommendations

For proof-of-concept, public tournament or internet video is acceptable if the goal is to show that a skeleton can be extracted and placed into a simulated court. However, it should be treated as noisy research data, not ground truth. The best first target is singles match footage from a stable high rear/broadcast perspective because this view usually includes the full court and both players, and because BST and ShuttleSet-style work are already aligned with broadcast match video.

| Camera Angle | Recommendation | Strength | Weakness |
|---|---|---|---|
| High rear baseline / broadcast view | **Best first choice** | Full court visible, player positions interpretable, compatible with BST/ShuttleSet-style data. | Far player may be small; vertical joint depth is ambiguous. |
| Side view | Useful secondary view for controlled recording | Better for sagittal movement, lunging depth, jump/landing, trunk lean. | Poorer for court-wide tactical movement and shuttle depth. |
| Diagonal corner view | Good supplement | Can improve depth perception and reduce full overlap compared with pure rear view. | Homography and pose interpretation are more complex. |
| Low courtside view | Not recommended as main source | Can capture racket/upper-body detail. | Frequent occlusion, incomplete court, hard court mapping. |
| Doubles broadcast view | Avoid for first POC | Eventual relevance for real badminton. | Four players, occlusion, harder player identification. |

For controlled recording, the VideoBadminton setup is the strongest starting reference: 60 fps or higher, camera behind the baseline, elevated around 4.5 meters, tilted downward, with lens calibration. For simulation-ready 3D movement, a single camera is likely insufficient. A controlled setup should eventually add at least one side or diagonal camera. The most realistic staged plan is:

1. **One high rear camera** — for compatibility with internet/broadcast videos.
2. **Two-camera setup** — for better 3D reconstruction.
3. **Three-to-four-camera setup** — if injury/biomechanical claims are required.

---

## 8. Evaluation Plan

The project should be evaluated at multiple levels because a single end-to-end metric will hide errors. For example, a visually plausible simulation could still have inaccurate knee angles, and a good stroke classifier could still have poor skeleton quality. The evaluation should separate video-processing accuracy, skeleton quality, action/stroke understanding, and simulation usefulness.

| Evaluation Layer | Suggested Metrics | How to Validate |
|---|---|---|
| Court mapping | Corner error, homography consistency, player-court coordinate stability. | Manual court-corner annotation on sample clips. |
| Player tracking | Track continuity, ID switches, missed detections. | Manual review of selected rallies. |
| 2D pose quality | Joint confidence, missing joints, temporal jitter, limb-length stability. | Pose overlay review; compare with manual keyframe checks. |
| Shuttle tracking | 2D shuttle position error, hit-frame error, trajectory plausibility. | Manual shuttle labels for short clips; compare with MonoTrack/TrackNet output. |
| Stroke segmentation/classification | Accuracy, macro-F1, top-2 accuracy; confusion between similar strokes. | Use annotated datasets or manually labeled proof clips. |
| Simulation output | Visual plausibility, foot placement, body orientation, timing alignment. | Coach/professor review and frame-by-frame inspection. |
| Biomechanical extension | Joint-angle consistency, landing/lunge metrics, asymmetry indicators. | Controlled capture validation; compare with OpenCap-style or multi-camera reference where possible. |

---

## 9. Risks, Limitations, and Ethical/Practical Constraints

- **Copyright:** Public tournament videos may be copyrighted. They can be useful for internal proof of concept, but publication, redistribution, or dataset release may require permission or use of datasets with explicit access terms.
- **Broadcast camera limitations:** A broadcast camera is not optimized for biomechanics. It may be adequate for 2D pose and stroke understanding, but not for accurate joint angles, injury-risk inference, or animation-grade 3D movement.
- **Badminton-specific 3D pose weakness:** BST's comparison shows that general 3D pose lifting can produce incorrect orientation in badminton frames and underperform 2D pose for classification.
- **Shuttlecock tracking difficulty:** The shuttlecock is small, fast, and frequently occluded. A simulation that depends on shuttle context must include confidence scores and manual correction options.
- **Racket tracking gap:** Racket tracking remains underdeveloped in this proposed pipeline. Stroke recognition can work without perfect racket geometry, but simulation and technique feedback will eventually need racket orientation and contact timing.
- **Doubles complexity:** Doubles should be avoided until the singles pipeline is stable because doubles multiplies the player-identification and occlusion problem.
- **Conservative injury-risk claims:** A video-to-skeleton POC can show movement reconstruction; it should not claim validated injury prediction unless tested against biomechanical ground truth or expert-labeled injury-risk criteria.

---

## 10. Recommended Research Direction

The recommended research direction is to position the project as an extension of current badminton video-analysis research into simulation-ready movement reconstruction. The project should not be framed as merely making a VR badminton game. It should be framed as a research pipeline: **extracting court-relative skeleton motion from badminton videos and using it to drive a simulation environment that can later support technique feedback and injury-risk analysis.**

### 10.1 Short-Term Proof-of-Concept

- Use 5–10 high-quality singles broadcast rally clips with stable rear/broadcast angle.
- Manually mark court corners for the first prototype if automatic detection is unreliable.
- Extract one player's 2D skeleton and map it into court coordinates.
- Animate a simple avatar or skeleton in a simulated badminton court.
- Overlay/compare the original video and simulation playback to demonstrate feasibility.

### 10.2 Medium-Term Controlled Data Collection

- Record players using a VideoBadminton-inspired rear elevated camera setup at 60 fps or higher.
- Add a side or diagonal camera for 3D reconstruction and biomechanical validation.
- Use calibration objects/chessboard calibration and court-line calibration before data collection.
- Collect repeated controlled strokes and footwork drills before full rallies.
- Store data in a structured schema that links pose, court position, shuttle path, hit frame, and stroke label.

### 10.3 Long-Term Research Contribution

The long-term contribution could be a badminton-specific video-to-simulation dataset or pipeline. The novelty would be in converting passive or controlled badminton video into court-relative skeleton motion that can be replayed, analyzed, and eventually used for VR/3D simulation. This would sit between existing action-recognition datasets and full motion-capture systems: cheaper and more scalable than marker-based mocap, but more structured and simulation-oriented than ordinary stroke classification.

---

## References

1. Chang, J.-Y. (2026). *BST: Badminton Stroke-type Transformer for Skeleton-based Action Recognition in Racket Sports.* arXiv:2502.21085v4.
2. Li, Q., Chiu, T.-C., Huang, H.-W., Sun, M.-T., & Ku, W.-S. (2024). *VideoBadminton: A Video Dataset for Badminton Action Recognition / Benchmarking Badminton Action Recognition with a New Fine-Grained Dataset.* arXiv:2403.12385.
3. Liu, P., & Wang, J.-H. (2022). *MonoTrack: Shuttle Trajectory Reconstruction from Monocular Badminton Video.* CVPR Workshops / arXiv:2204.01899.
4. Wang, W.-Y., Huang, Y.-C., Ik, T.-U., & Peng, W.-C. (2023). *ShuttleSet: A Human-Annotated Stroke-Level Singles Dataset for Badminton Tactical Analysis.* arXiv:2306.04948.
5. Ding, N., Fujii, K., & Tamaki, T. (2026). *BFMD: A Full-Match Badminton Dense Dataset for Dense Shot Captioning.* arXiv:2603.25533.
6. He, X., Liu, W., Ma, S., Liu, Q., Ma, C., & Wu, J. (2025). *FineBadminton: A Multi-Level Dataset for Fine-Grained Badminton Video Understanding.* arXiv:2508.07554.
7. Uhlrich, S. D., Falisse, A., Kidzinski, L., Muccini, J., Ko, M., Chaudhari, A. S., Hicks, J. L., & Delp, S. L. (2023). *OpenCap: Human movement dynamics from smartphone videos.* PLOS Computational Biology, 19(10), e1011462.
8. Gilon, S., Miller, E. Y., & Uhlrich, S. D. (2026). *OpenCap Monocular: 3D Human Kinematics and Musculoskeletal Dynamics from a Single Smartphone Video.* arXiv:2603.24733.
9. Chen, T., Chen, K., Liu, X., Ke, P., & Sun, Z. (2026). *BadminSense: Enabling Fine-Grained Badminton Stroke Evaluation on a Single Smartwatch.* arXiv:2603.21825.
10. Ban, K.-W., See, J., Abdullah, J., & Loh, Y.-P. (2022). *BadmintonDB: A Badminton Dataset for Player-specific Match Analysis and Prediction.*

---

*Citation note: The document uses author-year citations in the text and full source links in the references section to keep the note readable for professor review.*
