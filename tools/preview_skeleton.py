"""
preview_skeleton.py — quick sanity view of a skeleton.json WITHOUT Unity.

Renders N sampled frames as a 3D stick-figure montage PNG so you can confirm
the extraction looks like a moving human before opening the editor.

Usage: python tools/preview_skeleton.py data/skeleton/<clip>.json [--frames 8]
"""
import argparse
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

BONES = [(11,12),(11,23),(12,24),(23,24),(11,13),(13,15),(12,14),(14,16),
         (15,19),(16,20),(23,25),(25,27),(24,26),(26,28),(27,31),(28,32),
         (0,11),(0,12)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json")
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    d = json.load(open(args.json))
    F = len(d["frames"])
    arr = np.array([f["joints_flat"] for f in d["frames"]]).reshape(F, 33, 4)
    xyz = arr[:, :, :3]
    ground = xyz[:, :, 1].min()
    xyz[:, :, 1] -= ground  # stand on floor

    idxs = np.linspace(0, F - 1, args.frames, dtype=int)
    cols = min(4, args.frames)
    rows = int(np.ceil(args.frames / cols))
    fig = plt.figure(figsize=(cols * 3, rows * 3.6))

    for k, fi in enumerate(idxs):
        ax = fig.add_subplot(rows, cols, k + 1, projection="3d")
        p = xyz[fi]
        for a, b in BONES:
            ax.plot([p[a, 0], p[b, 0]], [p[a, 2], p[b, 2]], [p[a, 1], p[b, 1]],
                    color="#2bb0ff", linewidth=2)
        ax.scatter(p[:, 0], p[:, 2], p[:, 1], color="#f2d933", s=10)
        ax.set_title(f"frame {fi}  t={d['frames'][fi]['time']:.1f}s", fontsize=8)
        ax.set_xlim(-1, 1); ax.set_ylim(-1, 1); ax.set_zlim(0, 2)
        ax.set_box_aspect((1, 1, 1.4))
        ax.view_init(elev=8, azim=-70)
        ax.set_xticks([]); ax.set_yticks([]); ax.set_zticks([])

    out = args.out or args.json.replace(".json", "_preview.png")
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    print("wrote", out)


if __name__ == "__main__":
    main()
