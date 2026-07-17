"""Tests for tools/label_moves.py on SYNTHETIC skeleton docs."""
import sys, os
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from label_moves import (load_doc, wrist_speed, detect_strokes,
                         R_WRIST, NUM_JOINTS, STRIDE)


def make_doc(n_frames=200, fps=60.0, root_xz=(0.0, 4.0)):
    """Neutral standing doc: all joints at fixed plausible heights, conf 1.0."""
    frames = []
    for i in range(n_frames):
        jf = [0.0] * (NUM_JOINTS * STRIDE)
        for j in range(NUM_JOINTS):
            jf[j * STRIDE + 1] = 1.0   # y
            jf[j * STRIDE + 3] = 1.0   # conf
        frames.append({"frame_id": i, "time": i / fps,
                       "root_court_xz": list(root_xz),
                       "root_confidence": 1.0, "joints_flat": jf})
    return {"schema_version": "1.0", "video_id": "synth",
            "source": {"type": "phone_static", "fps": fps},
            "frames": frames}


def set_joint(doc, frame, joint, x=None, y=None, z=None, conf=None):
    jf = doc["frames"][frame]["joints_flat"]
    b = joint * STRIDE
    for off, v in enumerate((x, y, z, conf)):
        if v is not None:
            jf[b + off] = v


def add_swing(doc, peak_frame, peak_speed=6.0, width=8):
    """Move the right wrist so its speed ramps to ~peak_speed at peak_frame.
    Starts from the wrist's current x and HOLDS the final x afterwards —
    otherwise the snap back to x=0 is a phantom speed spike."""
    fps = doc["source"]["fps"]
    b = R_WRIST * STRIDE
    pre = peak_frame - width - 1
    x = doc["frames"][pre]["joints_flat"][b] if pre >= 0 else 0.0
    for i in range(peak_frame - width, peak_frame + width + 1):
        # triangular speed profile, motion along +x
        s = peak_speed * (1 - abs(i - peak_frame) / width)
        x += s / fps
        set_joint(doc, i, R_WRIST, x=x)
    for i in range(peak_frame + width + 1, len(doc["frames"])):
        set_joint(doc, i, R_WRIST, x=x)


def test_wrist_speed_still_is_zero():
    doc = make_doc()
    sp = wrist_speed(doc)
    assert sp.shape == (200,)
    assert np.nanmax(sp) < 0.1


def test_wrist_speed_moving():
    doc = make_doc()
    add_swing(doc, peak_frame=100, peak_speed=6.0)
    sp = wrist_speed(doc)
    assert np.nanmax(sp[92:109]) > 3.0   # smoothing lowers the 6.0 peak


def test_wrist_speed_nan_when_low_conf():
    doc = make_doc()
    set_joint(doc, 50, R_WRIST, conf=0.1)
    sp = wrist_speed(doc)
    assert np.isnan(sp[50])


def test_detect_strokes_two_peaks():
    doc = make_doc(n_frames=400)
    add_swing(doc, 100); add_swing(doc, 300)
    sp = wrist_speed(doc)
    peaks = detect_strokes(sp, fps=60.0)
    assert len(peaks) == 2
    assert abs(peaks[0] - 100) <= 3 and abs(peaks[1] - 300) <= 3


def test_detect_strokes_min_gap_merges():
    doc = make_doc(n_frames=400)
    add_swing(doc, 100); add_swing(doc, 112)   # 0.2 s apart < 0.5 s min gap
    sp = wrist_speed(doc)
    assert len(detect_strokes(sp, fps=60.0)) == 1


def test_detect_strokes_below_threshold_ignored():
    doc = make_doc(n_frames=400)
    add_swing(doc, 100, peak_speed=1.0)        # gentle drift, not a stroke
    sp = wrist_speed(doc)
    assert detect_strokes(sp, fps=60.0) == []
