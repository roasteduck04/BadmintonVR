# Design: tidy-up, racket visual, debug tools, go public (2026-07-16)

Approved by user 2026-07-16 ("approve, proceed with everything").

## Scope

Five workstreams, single-camera assumption (multi-camera Phase 3 plan is not
concrete yet):

### 1. Folder tidy-up
- `position_front` → `test_5` everywhere: `data/raw`, `data/calib` (json +
  overlays + check images, incl. internal `video` field), `data/skeleton`
  (incl. `video_id`), `Assets/StreamingAssets/skeleton` (+ .meta), code
  defaults. All clips follow `test_N`; derived files keep the stem — that is
  the lookup key for Unity tools (Video Compare, future calib lookups).
- Stale `WRONG-fullcourt` backups → `data/calib/archive/` (gitignored).
- Research `.md` notes → `docs/research/` (committed); PDFs stay outside.

### 2. Fix invisible Video Compare
Root cause: `SkeletonRenderer.Clear()` destroys every twin child on clip load;
the overlay canvas was a twin child → wiped a frame after creation
(`MissingReferenceException` on the RawImage). Fix: canvas at scene root,
null guards, cleanup in `OnDestroy`. **Rule going forward: runtime helper
objects never live under the twin.**

### 3. Racket visual (Phase 2.5 step 1)
`RacketVisual` on the twin: orange shaft+head from primitives (~0.68 m), grip
at the RIGHT wrist, blade along elbow→wrist. Shown only for clips in
`clipsWithRacket` (test_3/4/5); hides below confidence cutoff. Geometry at
scene root (rule above). This is the baseline the future detector is judged
against.

Racket detection decision (user asked "gather my own data?"): **no** —
cheapest-first ladder is (a) zero-shot COCO "tennis racket" YOLO,
(b) Roboflow community badminton-racket datasets / auto-label own frames with
an open-vocab detector, fine-tune on Colab, (c) fuse detection with the arm
prior for 3D orientation (RacketVision-style keypoints as long-term
reference). Own-video gathering only as a last resort.

### 4. Debug tools ("see what the AI sees")
`PipelineDebugHUD` on the twin: (a) joints tinted green→red by MediaPipe
confidence via MaterialPropertyBlock; (b) cyan floor trail of the full
extracted path, red spheres at clamp-entry frames (|X| ≥ 4.55, |Z| ≥ 8.20),
magenta puck at current frame; (c) OnGUI stats box (clip, frame, root XZ +
conf, mean pose conf, % in box, clamp count). Toggle H (Input System-aware).
Menus: `Tools ▸ Badminton ▸ Debug HUD / Racket / Video Compare / Clip
Switcher`.

### 5. Go public
- `.gitignore` += `data/**/*.png`, `data/**/*.jpg`, `docs/img/`,
  `data/calib/archive/` — no frame-bearing image (user + location visible)
  reaches the public repo. Raw videos were already ignored.
- `README.md` (pipeline, layout, quickstart, roadmap, privacy note) + MIT
  `LICENSE`.
- Commit + push; the visibility flip itself is done by the user
  (`gh repo edit roasteduck04/BadmintonVR --visibility public` or GitHub
  Settings ▸ Danger Zone) — assistant does not change repo permissions.

## AI quality roadmap
Separate doc: `docs/ai-smoothing-plan.md` — measure (Step 0) → One-Euro +
confidence-weighted gap fill (local) → Kalman + physics gating on root XZ
(local) → temporal 3D lifting on Colab → stronger 2D backbone only if still
needed. Each step has acceptance criteria tied to the Step-0 metrics.
