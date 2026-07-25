# Colab notebooks

This laptop has no NVIDIA GPU, so every heavy pass runs on Colab.

| notebook | what it does | output |
|---|---|---|
| `wham_extract.ipynb` | body pose — ROMP → SMPL params | `<id>.smpl.npz` |
| `racketvision_extract.ipynb` | racket — RacketVision RTMDet→RTMPose | `<id>.racket2d.json` + overlay mp4 |

---

# 1. Pose → skeleton.json v2

Runs a monocular pose engine on one clip and writes a normalized `<video_id>.smpl.npz`
that `tools/smpl_to_skeleton.py --wham-output` turns into `skeleton.json v2` (and feeds
the Blender SMPL mesh — Route A). This laptop has no NVIDIA GPU, so inference runs on Colab.

**Engine: ROMP** (`simple_romp`). We started on WHAM but its Colab setup (conda + a
compiled SLAM module + checkpoint scripts) is very painful; ROMP is a plain pip package
that outputs the same SMPL params. WHAM / 4D-Humans stay as later quality upgrades — the
npz contract below is engine-agnostic, so nothing downstream changes when we swap.

The notebook file is still named `wham_extract.ipynb` (historical); it runs ROMP.

## One-time
1. Register at https://smpl.is.tue.mpg.de and download the **neutral SMPL** model.
   Locally it is `models/smpl/SMPL_NEUTRAL.pkl` (see `models/smpl/README.md`).
2. Open `wham_extract.ipynb` in Colab, set Runtime → GPU.

## Run
1. **Cell 1** — `pip install simple_romp`.
2. **Cell 2** — de-chumpifies + converts the SMPL model to `~/.romp/SMPL_NEUTRAL.pth`.
   The official pkl is chumpy-pickled and chumpy is broken on Colab's Python 3.12; the cell
   patches enough to import it once, saves a clean pkl, and hands you back
   `SMPL_NEUTRAL_clean.pkl` — upload **that** on future runs to skip chumpy entirely.
   Watch for `chumpy imported OK` then `converted -> True`.
3. **Cell 3** — upload a clip (e.g. a Pexels clip named `test_N.mp4`), set `VIDEO_ID`;
   it downscales to 720p and runs ROMP.
4. **Cell 4** — downloads `test_N.smpl.npz`.
5. Locally: `./tools/.venv/Scripts/python.exe tools/smpl_to_skeleton.py --wham-output test_N.smpl.npz --video-id test_N --out data/skeleton/test_N.skeleton.json`

## Output contract (what the npz must contain)
- `joints3d` (T,24,3) — SMPL joints (ROMP's `joints[:24]`, SMPL order)
- `pose` (T,72), `betas` (10,), `transl` (T,3), `fps` (scalar)

`smpl_to_skeleton.py` only *requires* `joints3d`; the rest are optional but ROMP provides
all five. The `--wham-output` flag name is historical — it reads any `.npz` on this contract.

---

# 2. Racket → racket2d.json (`racketvision_extract.ipynb`)

Runs the pretrained **RacketVision** model (AAAI'26, MIT — github.com/OrcustD/RacketVision)
on one clip: RTMDet racket detector → RTMPose 5-keypoint head. Stage 1 of the vision-racket
work; Stage 2 (lift 2D→3D at the SMPL hand) and Stage 3 (racket on the twin) are local.

**Keypoints** (confirmed from the repo's `configs/_base_/datasets/racket_pose.py`):
`0=top, 1=bottom, 2=handle, 3=left, 4=right`. Long axis = `handle` (grip) → `top` (head tip);
`left`/`right` = head width. Published per-keypoint accuracy on badminton: top 99.4 / bottom
99.7 / handle 97.3 / **left 74.6 / right 75.5** — the sides are occluded by the hand, so trust
the long axis and treat face-roll as noisy.

## Run
**GPU runtime required.** Order: **1 → 2 → (kernel auto-restarts) → 2c → 3-8.**
Do NOT re-run Cell 2 after the restart.

- **Cell 2** installs the whole stack and then restarts the kernel *on purpose*.
- **Cell 2c** is the debug cell: it repairs numpy in-kernel and imports every heavy module
  one at a time printing PASS/FAIL. Run it first after the restart; if anything FAILs its
  output names the culprit without a Cell-3→5 re-run.
- **Cell 6** prints the hit rate (`racket detected in N/M`) plus a `det >= x` table; **Cell 8**
  downloads the JSON + overlay. Save the JSON to `data/racket/<id>.racket2d.json` (the overlay
  mp4 is frame-bearing and gitignored).

## Detector recall is the weak link (v3 → v4, 2026-07-25)
The first successful run (v3, `DET_THR = 0.30`) found the racket in **16/189 frames of
test_6 — 8.5%**. But the frames it *did* find were near-perfect: on an overhead smash
scored at **0.31** the five keypoints sat exactly on the racket (`top` on the tip,
`left`/`right` across the head, `handle` at the grip). Misses were ordinary poses — racket
hanging down against the red floor, or its head face-on over the torso. So RTMPose is fine
and **RTMDet recall is the bottleneck**; the useful signal lives *below* 0.30.

v4 therefore runs **`DET_THR = 0.05`** and keeps the **top 3 boxes per frame with keypoints
for each** (`frames[i].cands`). Choosing among them is temporal-continuity work that belongs
in a local script, where a wrong rule costs one rerun instead of another Colab install.

## Output contract
`keypoints` are **pixels in the 1080p frame** the model ran on, not source pixels — the JSON
carries `frame_size` and `source_size` so Stage 2 can map them onto the SMPL body (which came
from a 720p pass of the same clip). Also recorded: `fps` (ffprobed, not assumed), `stride`,
per-frame `bbox`/`det_score`/`keypoint_scores`, and the detector settings under `det`.
Frames with no accepted detection are kept with `keypoints: null` so indices stay aligned.

The flat per-frame `bbox`/`det_score`/`keypoints`/`keypoint_scores` are the **argmax**
candidate (v3-compatible); `cands` is the full top-K list, best first, each entry with the
same four fields. Filter on `det_score` downstream — the `det.score_thr` recorded in the
file is only the floor the pass ran at.

## Why the environment is so fussy
Colab is Python 3.12 + torch 2.11; OpenMMLab has no wheels for that. The working recipe —
**torch 2.3.1+cu121 + mmcv 2.2.0 (prebuilt wheel) + mmdet 3.3.0 / mmpose 1.3.2 `--no-deps`
+ an mmcv-ceiling patch + numpy pinned to 1.26.4 via a constraints file + `transformers`
removed + xtcocotools stub + `pkgutil.ImpImporter` and `FileFinder.find_module` shims** —
took twelve debug rounds; each one is recorded in `docs/for-claude/PROGRESS.md`. Two traps
worth remembering: mmcv's compiled ops need **numpy < 2** (a constraints file + a kernel
restart are both mandatory — an in-kernel last-step pin does not hold), and `transformers`
must be **absent**, because on torch 2.3 it half-disables itself and then raises a
`NameError` that mmdet's `except ImportError` cannot catch.

**Colab wipes the VM after a few idle hours** — installs, `/content`, frames, all of it.
Caching the built env + frames to Drive is an open TODO.
