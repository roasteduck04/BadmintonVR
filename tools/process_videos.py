"""
process_videos.py — one-command batch: video(s) -> skeleton.json -> Unity.

Drop clips into data/raw/ and run this. For every video it:
  1. extracts a Unity-space skeleton (via extract_skeleton.py),
  2. writes data/skeleton/<name>.json,
  3. copies that json into Assets/StreamingAssets/skeleton/ so Unity sees it.

Usage:
    python tools/process_videos.py                 # all mp4/mov in data/raw
    python tools/process_videos.py test_1 test_2   # just these (name or path)
    python tools/process_videos.py --flip-z        # pass flags through to extractor

Any unknown flag (--rotate, --flip-z, --min-confidence, --smooth-window,
--debug-frame) is forwarded to extract_skeleton.py for every clip.

Phase 2: if data/calib/<name>_court.json exists (made once per camera setup
with tools/calibrate_court.py), it is passed automatically so the skeleton
gets root_court_xz (player position on the court).
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)  # project root (BadmintonVR/)
RAW = os.path.join(ROOT, "data", "raw")
CALIB = os.path.join(ROOT, "data", "calib")
SKEL = os.path.join(ROOT, "data", "skeleton")
STREAMING = os.path.join(ROOT, "Assets", "StreamingAssets", "skeleton")
EXTRACTOR = os.path.join(HERE, "extract_skeleton.py")
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".avi", ".mkv")


def stem_of(path):
    stem = os.path.basename(path)
    while os.path.splitext(stem)[1]:
        stem = os.path.splitext(stem)[0]
    return stem


def resolve_video(token):
    """Accept a bare name (test_1), a filename, or a path; find it in data/raw."""
    if os.path.isfile(token):
        return token
    cand = os.path.join(RAW, token)
    if os.path.isfile(cand):
        return cand
    for ext in VIDEO_EXTS:
        cand = os.path.join(RAW, token + ext)
        if os.path.isfile(cand):
            return cand
    return None


def main():
    args = sys.argv[1:]
    names = [a for a in args if not a.startswith("-")]
    passthrough = [a for a in args if a.startswith("-")]

    if names:
        videos = []
        for n in names:
            v = resolve_video(n)
            if v is None:
                print(f"!! could not find video for '{n}' in {RAW}")
            else:
                videos.append(v)
    else:
        videos = [os.path.join(RAW, f) for f in sorted(os.listdir(RAW))
                  if f.lower().endswith(VIDEO_EXTS)]

    if not videos:
        sys.exit(f"No videos to process. Put clips in {RAW} or name them explicitly.")

    os.makedirs(STREAMING, exist_ok=True)
    print(f"Processing {len(videos)} video(s). Flags: {' '.join(passthrough) or '(defaults)'}\n")

    ok = []
    for v in videos:
        stem = stem_of(v)
        print(f"--- {stem} " + "-" * (40 - len(stem)))
        cmd = [sys.executable, EXTRACTOR, v] + passthrough
        court = os.path.join(CALIB, stem + "_court.json")
        if "--court" not in " ".join(passthrough) and os.path.isfile(court):
            cmd += ["--court", court]
            print(f"  using court calibration {os.path.relpath(court, ROOT)}")
        r = subprocess.run(cmd, cwd=ROOT)
        if r.returncode != 0:
            print(f"!! extraction failed for {stem}\n")
            continue
        src = os.path.join(SKEL, stem + ".json")
        if not os.path.isfile(src):
            print(f"!! expected {src} but it's missing\n")
            continue
        dst = os.path.join(STREAMING, stem + ".json")
        shutil.copyfile(src, dst)
        print(f"  copied -> Assets/StreamingAssets/skeleton/{stem}.json\n")
        ok.append(stem)

    print("=" * 50)
    print(f"Done. {len(ok)}/{len(videos)} ready in Unity: {', '.join(ok) or '(none)'}")
    if ok:
        print("In Unity: Tools > Badminton > Build Two-Player Scene "
              "(or Choose Avatar for one).")


if __name__ == "__main__":
    main()
