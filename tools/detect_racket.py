"""
detect_racket.py — ZERO-SHOT racket detection probe (Phase 2.5 step 2a).

Question this answers: can an off-the-shelf COCO detector see the racket in
OUR footage at all (small, motion-blurred object at 6+ m)? COCO has no
"badminton racket" class, but "tennis racket" (class 38) fires on badminton
rackets often enough to be a useful zero-shot probe.

This is a MEASUREMENT, not the final detector. Outcomes (see
docs/ai-smoothing-plan.md, racket tie-in):
  - hit-rate high  -> zero-shot boxes may already be usable to correct the
                      arm-estimated racket direction (2D fusion).
  - hit-rate low   -> skip to RacketVision pretrained RacketPose on Colab
                      (5 racket keypoints; MIT; repo OrcustD/RacketVision).

Runs on CPU (no GPU on this laptop) — sample frames, don't run every frame.

Usage:
  tools/.venv/Scripts/python tools/detect_racket.py                 # test_3/4/5
  tools/.venv/Scripts/python tools/detect_racket.py data/raw/test_4.mp4 --stride 5
  tools/.venv/Scripts/python tools/detect_racket.py --model yolov8s.pt --imgsz 1920

Outputs (data/racket/ — images are gitignored, JSON is committed):
  <stem>_zeroshot.json      per-sampled-frame detections [x1,y1,x2,y2,conf]
  <stem>/frame_NNNNN.jpg    overlay for every sampled frame WITH a detection
  printed summary table across clips
"""

import argparse
import json
import os
import sys

import cv2

COCO_TENNIS_RACKET = 38
DEFAULT_CLIPS = ["data/raw/test_3.mp4", "data/raw/test_4.mp4", "data/raw/test_5.mp4"]


def probe_clip(model, video_path, stride, imgsz, conf, out_dir):
    stem = os.path.splitext(os.path.basename(video_path))[0]
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"!! cannot open {video_path}")
        return None
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    overlay_dir = os.path.join(out_dir, stem)
    os.makedirs(overlay_dir, exist_ok=True)

    frames = []  # {"frame": i, "t": sec, "dets": [[x1,y1,x2,y2,conf], ...]}
    sampled = hits = 0
    best = 0.0

    for i in range(0, total, stride):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, img = cap.read()
        if not ok:
            break
        sampled += 1

        res = model.predict(img, imgsz=imgsz, conf=conf,
                            classes=[COCO_TENNIS_RACKET], verbose=False)[0]
        dets = []
        for b in res.boxes:
            x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
            c = float(b.conf[0])
            dets.append([round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1),
                         round(c, 3)])
            best = max(best, c)

        frames.append({"frame": i, "t": round(i / fps, 3), "dets": dets})
        if dets:
            hits += 1
            for x1, y1, x2, y2, c in dets:
                cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)),
                              (0, 140, 255), 2)
                cv2.putText(img, f"racket {c:.2f}", (int(x1), int(y1) - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 140, 255), 2)
            cv2.imwrite(os.path.join(overlay_dir, f"frame_{i:05d}.jpg"), img)
        if sampled % 20 == 0:
            print(f"  {stem}: {sampled} frames sampled, {hits} with detection...")

    cap.release()

    report = {
        "video": os.path.basename(video_path),
        "detector": "zero-shot COCO 'tennis racket'",
        "stride": stride, "imgsz": imgsz, "conf_threshold": conf,
        "frames_sampled": sampled, "frames_with_detection": hits,
        "hit_rate": round(hits / sampled, 3) if sampled else 0.0,
        "best_confidence": round(best, 3),
        "frames": frames,
    }
    out_json = os.path.join(out_dir, f"{stem}_zeroshot.json")
    with open(out_json, "w") as f:
        json.dump(report, f, indent=1)
    print(f"  -> {out_json}  (overlays in {overlay_dir}/)")
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("videos", nargs="*", default=DEFAULT_CLIPS,
                    help="clips to probe (default: the racket clips test_3/4/5)")
    ap.add_argument("--model", default="yolov8s.pt",
                    help="ultralytics weights (auto-downloads); n=fast s=better")
    ap.add_argument("--stride", type=int, default=10,
                    help="sample every Nth frame (CPU budget)")
    ap.add_argument("--imgsz", type=int, default=1280,
                    help="inference size; racket is small -> keep this high")
    ap.add_argument("--conf", type=float, default=0.10,
                    help="low threshold on purpose: this probe measures recall")
    ap.add_argument("--out", default=os.path.join("data", "racket"))
    args = ap.parse_args()

    from ultralytics import YOLO  # late import: slow, and after arg errors
    model = YOLO(args.model)

    os.makedirs(args.out, exist_ok=True)
    reports = []
    for v in args.videos:
        print(f"probing {v} ...")
        r = probe_clip(model, v, args.stride, args.imgsz, args.conf, args.out)
        if r:
            reports.append(r)

    if not reports:
        sys.exit("no clips processed")

    print("\n=== zero-shot racket probe summary ===")
    print(f"{'clip':<10} {'sampled':>8} {'hits':>6} {'hit rate':>9} {'best conf':>10}")
    for r in reports:
        print(f"{r['video']:<10} {r['frames_sampled']:>8} "
              f"{r['frames_with_detection']:>6} {r['hit_rate']:>9.1%} "
              f"{r['best_confidence']:>10.2f}")
    print("\nRead the outcome rules in the module docstring / "
          "docs/ai-smoothing-plan.md (racket tie-in).")


if __name__ == "__main__":
    main()
