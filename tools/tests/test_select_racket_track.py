import json
import subprocess
import sys

import pytest

import select_racket_track as srt

NAMES = ["top", "bottom", "handle", "left", "right"]


def cand(cx, cy, kp=0.7, det=0.1, shaft=100.0):
    """A candidate whose 5 keypoints sit around (cx, cy), with a uniform keypoint score.

    `shaft` sets the grip-to-tip distance ('top' above centre, 'handle' below).
    """
    half = shaft / 2.0
    pts = [[cx, cy - half], [cx, cy + half * 0.6], [cx, cy + half],
           [cx - 20, cy], [cx + 20, cy]]
    return {"bbox": [cx - 20, cy - half, cx + 20, cy + half], "det_score": det,
            "keypoints": pts, "keypoint_scores": [kp] * 5}


def doc(frames, **over):
    d = {"video_id": "t", "fps": 25.0, "stride": 1, "frame_size": [1920, 1080],
         "source_size": [3840, 2160], "source": "upstream",
         "keypoint_names": NAMES, "num_frames": len(frames),
         "frames": [{"frame": i, "bbox": None, "det_score": None, "keypoints": None,
                     "keypoint_scores": None, "cands": c} for i, c in enumerate(frames)]}
    d.update(over)
    return d


def test_mean_kp_score_averages_all_five():
    c = cand(100, 100)
    c["keypoint_scores"] = [0.2, 0.4, 0.6, 0.8, 1.0]
    assert srt.mean_kp_score(c) == pytest.approx(0.6)


def test_candidates_falls_back_to_v3_flat_fields():
    # v3 files predate `cands`; the flat argmax box must still feed the same policy.
    c = cand(100, 100)
    v3 = {"frame": 0, "bbox": c["bbox"], "det_score": c["det_score"],
          "keypoints": c["keypoints"], "keypoint_scores": c["keypoint_scores"]}
    got = srt.candidates(v3)
    assert len(got) == 1 and got[0]["keypoints"] == c["keypoints"]


def test_candidates_empty_when_nothing_detected():
    assert srt.candidates({"frame": 0, "bbox": None, "keypoints": None}) == []


def test_selection_ranks_by_keypoint_score_not_detector_score():
    # The whole point: on test_6 a det=0.08 box was the real racket and a det=0.30 box
    # was a net-post artifact. Keypoint score is the signal.
    decoy = cand(1800, 500, kp=0.15, det=0.90)
    real = cand(400, 500, kp=0.70, det=0.08)
    picks = srt.select_track(doc([[decoy, real]])["frames"])
    assert picks[0]["keypoints"] == real["keypoints"]


def test_weak_frame_is_left_unpicked():
    picks = srt.select_track(doc([[cand(400, 500, kp=0.2)]])["frames"])
    assert picks[0] is None


def test_frame_with_no_candidates_is_none():
    picks = srt.select_track(doc([[]])["frames"])
    assert picks[0] is None


def test_isolated_outlier_is_rejected():
    # Three anchors; the middle one is 1500 px away from both neighbours -> artifact.
    frames = doc([[cand(400, 500)], [cand(1900, 500)], [cand(410, 505)]])["frames"]
    picks = srt.select_track(frames)
    assert picks[0] is not None and picks[2] is not None
    assert picks[1] is None


def test_anchor_without_neighbours_survives():
    # A lone confident detection has nothing to corroborate it, but absence of
    # corroboration is not evidence against — it must not be dropped.
    frames = doc([[cand(400, 500)], [], [], [], []])["frames"]
    assert srt.select_track(frames)[0] is not None


def test_continuity_recovers_a_relaxed_candidate_near_an_anchor():
    weak = cand(420, 505, kp=0.40)          # below MIN (0.50), above RELAX (0.35)
    frames = doc([[cand(400, 500)], [weak]])["frames"]
    picks = srt.select_track(frames)
    assert picks[1] is not None and picks[1]["keypoints"] == weak["keypoints"]


def test_continuity_does_not_recover_a_distant_candidate():
    far = cand(1800, 900, kp=0.40)
    frames = doc([[cand(400, 500)], [far]])["frames"]
    assert srt.select_track(frames)[1] is None


def test_recovery_rejects_a_collapsed_shaft():
    # test_6 frame 58: a relaxed fit that sat on the grip but never found the head, giving
    # a 68 px shaft beside a 200 px one. Close enough in space, implausible in scale.
    stub = cand(420, 505, kp=0.40, shaft=30.0)
    frames = doc([[cand(400, 500, shaft=200.0)], [stub]])["frames"]
    assert srt.select_track(frames)[1] is None


def test_recovery_accepts_a_mildly_foreshortened_shaft():
    # Real foreshortening shortens the racket smoothly; a 1.4x change must still pass.
    ok = cand(420, 505, kp=0.40, shaft=140.0)
    frames = doc([[cand(400, 500, shaft=200.0)], [ok]])["frames"]
    assert srt.select_track(frames)[1] is not None


def test_degenerate_anchor_length_cannot_veto():
    assert srt._length_plausible(150.0, 0.0, 2.0) is True


def test_recovery_sweeps_backward_too():
    # The anchor is last; the weak frame before it must still be recovered.
    weak = cand(420, 505, kp=0.40)
    frames = doc([[weak], [cand(400, 500)]])["frames"]
    assert srt.select_track(frames)[0] is not None


def test_interpolation_fills_a_bracketed_gap_at_the_midpoint():
    a, b = cand(100, 100), cand(300, 100)
    filled = srt.interpolate_gaps([a, None, b], max_gap=4)
    kps, status = filled[1]
    assert status == srt.STATUS_INTERPOLATED
    assert kps[0][0] == pytest.approx(200.0)          # halfway between the two 'top' points
    assert kps[0][1] == pytest.approx(50.0)


def test_interpolation_skips_gaps_longer_than_max():
    picks = [cand(100, 100)] + [None] * 5 + [cand(300, 100)]
    filled = srt.interpolate_gaps(picks, max_gap=4)
    assert all(s == srt.STATUS_MISSING for _, s in filled[1:6])


def test_interpolation_never_extrapolates_past_the_ends():
    # One-sided gaps carry no evidence about where the racket went.
    filled = srt.interpolate_gaps([None, cand(100, 100), None], max_gap=4)
    assert filled[0][1] == srt.STATUS_MISSING
    assert filled[2][1] == srt.STATUS_MISSING


def test_document_counts_coverage_and_carries_geometry():
    d = doc([[cand(100, 100)], [], [cand(300, 100)]])
    picks = srt.select_track(d["frames"])
    filled = srt.interpolate_gaps(picks, max_gap=4)
    out = srt.build_track_document(d, picks, filled, min_kp_score=0.5, relax_kp_score=0.35,
                                   max_jump_px=250.0, max_len_ratio=2.0, max_interp_gap=4,
                                   source_path="in.json")
    assert out["coverage"] == {"detected": 2, "interpolated": 1, "missing": 0}
    assert out["frame_size"] == [1920, 1080] and out["source_size"] == [3840, 2160]
    assert out["fps"] == 25.0 and out["keypoint_names"] == NAMES
    assert out["upstream"] == "upstream"          # provenance of the 2D pass is preserved
    assert out["frames"][1]["kp_score"] is None   # interpolated frames have no measurement


def test_shaft_length_is_grip_to_tip():
    kps = [[0, 0], [0, 0], [0, 100], [0, 0], [0, 0]]   # top at y=0, handle at y=100
    assert srt.shaft_length_px(kps, NAMES) == pytest.approx(100.0)


def test_cli_end_to_end(tmp_path):
    d = doc([[cand(100, 100)], [], [cand(300, 100)], [], [], [], [], [], []])
    src = tmp_path / "in.racket2d.json"
    src.write_text(json.dumps(d), encoding="utf-8")
    dst = tmp_path / "out.rackettrack.json"
    r = subprocess.run([sys.executable, "tools/select_racket_track.py", str(src),
                        "--out", str(dst)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    out = json.loads(dst.read_text(encoding="utf-8"))
    assert out["num_frames"] == 9
    assert out["coverage"]["detected"] == 2
    assert "detected" in r.stdout


def test_per_keypoint_scores_are_carried_through():
    # The racket ROLL is derived from `left`/`right` alone, and those are the model's
    # weakest keypoints — a consumer must be able to gate on them, not just on the mean.
    c = cand(100, 100)
    c["keypoint_scores"] = [0.9, 0.9, 0.9, 0.3, 0.9]
    d = doc([[c]])
    picks = srt.select_track(d["frames"])
    filled = srt.interpolate_gaps(picks, max_gap=4)
    out = srt.build_track_document(d, picks, filled, min_kp_score=0.5, relax_kp_score=0.35,
                                   max_jump_px=250.0, max_len_ratio=2.0, max_interp_gap=4,
                                   source_path="in.json")
    assert out["frames"][0]["keypoint_scores"] == [0.9, 0.9, 0.9, 0.3, 0.9]


def test_interpolated_frames_have_no_per_keypoint_scores():
    d = doc([[cand(100, 100)], [], [cand(300, 100)]])
    picks = srt.select_track(d["frames"])
    filled = srt.interpolate_gaps(picks, max_gap=4)
    out = srt.build_track_document(d, picks, filled, min_kp_score=0.5, relax_kp_score=0.35,
                                   max_jump_px=250.0, max_len_ratio=2.0, max_interp_gap=4,
                                   source_path="in.json")
    assert out["frames"][1]["status"] == srt.STATUS_INTERPOLATED
    assert out["frames"][1]["keypoint_scores"] is None
