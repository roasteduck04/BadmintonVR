# WHAM → skeleton.json v2 (Colab)

Runs WHAM (world-grounded SMPL) on one monocular clip and writes a normalized
`<video_id>.wham.npz` that `tools/smpl_to_skeleton.py --wham-output` turns into
`skeleton.json v2`. This laptop has no NVIDIA GPU, so inference runs on Colab.

## One-time
1. Register at https://smpl.is.tue.mpg.de and download the **neutral SMPL** model
   (`SMPL_NEUTRAL.pkl`). Upload it to the Colab session (or your Drive).
2. Open `wham_extract.ipynb` in Colab, set Runtime → GPU.

## Run
1. Upload a clip (e.g. a Pexels clip renamed `test_N.mp4`), set `VIDEO_ID`.
2. Run all cells → downloads `test_N.wham.npz`.
3. Locally: `./tools/.venv/Scripts/python.exe tools/smpl_to_skeleton.py --wham-output test_N.wham.npz --video-id test_N --out data/skeleton/test_N.skeleton.json`

## Output contract (what the npz must contain)
- `joints3d` (T,24,3) — SMPL joints, world meters
- `pose` (T,72), `betas` (10,), `transl` (T,3), `fps` (scalar)
