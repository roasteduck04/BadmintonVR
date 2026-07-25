import numpy as np
import pytest

import lift_racket_3d as lift

NAMES = ["top", "bottom", "handle", "left", "right"]
CAM = {"s": 0.2, "tx": 0.5, "ty": 0.3}
FRAME_SIZE = [1920, 1080]


def to_px(xy):
    """World XY -> pixels in FRAME_SIZE, the inverse of what the lift consumes."""
    u = (CAM["s"] * xy[0] + CAM["tx"]) * FRAME_SIZE[0]
    v = (CAM["s"] * xy[1] + CAM["ty"]) * FRAME_SIZE[0]
    return [u, v]


def rec(frame, grip_xy=None, tip_xy=None, status="detected", kp=0.7):
    if grip_xy is None:
        return {"frame": frame, "status": "missing", "keypoints": None,
                "kp_score": None, "det_score": None, "bbox": None}
    kps = [None] * 5
    kps[NAMES.index("handle")] = to_px(grip_xy)
    kps[NAMES.index("top")] = to_px(tip_xy)
    for i, n in enumerate(NAMES):
        if kps[i] is None:
            kps[i] = to_px(grip_xy)
    return {"frame": frame, "status": status, "keypoints": kps, "kp_score": kp,
            "det_score": 0.2, "bbox": [0, 0, 1, 1]}


def track(records):
    return {"video_id": "t", "fps": 25.0, "frame_size": FRAME_SIZE,
            "source_size": [3840, 2160], "keypoint_names": NAMES,
            "num_frames": len(records), "frames": records}


def joints(n, hand_xy=(0.0, 0.0), depth=5.0):
    """SMPL joints with the right arm placed so elbow->wrist points +X."""
    j = np.zeros((n, 24, 3))
    j[..., 2] = depth
    j[:, 23, :2] = hand_xy          # right hand
    j[:, 21, :2] = hand_xy          # right wrist
    j[:, 19, :2] = (hand_xy[0] - 0.3, hand_xy[1])   # right elbow, 0.3 m back along -X
    j[:, 22, :2] = (hand_xy[0] - 3.0, hand_xy[1])   # left hand, far away
    j[:, 20, :2] = (hand_xy[0] - 3.0, hand_xy[1])
    j[:, 18, :2] = (hand_xy[0] - 3.3, hand_xy[1])
    return j


def test_normalized_uv_divides_both_axes_by_width():
    got = lift.normalized_uv([960, 540], FRAME_SIZE)
    assert got[0] == pytest.approx(0.5)
    assert got[1] == pytest.approx(540 / 1920)


def test_apparent_vectors_invert_the_projection():
    t = track([rec(0, (0.0, 0.0), (0.5, 0.0))])
    (grip, delta), = lift.apparent_vectors(t, [CAM], FRAME_SIZE)
    assert grip == pytest.approx([0.0, 0.0], abs=1e-9)
    assert delta == pytest.approx([0.5, 0.0], abs=1e-9)


def test_apparent_vectors_none_without_a_camera():
    t = track([rec(0, (0.0, 0.0), (0.5, 0.0))])
    assert lift.apparent_vectors(t, [None], FRAME_SIZE) == [None]


def test_length_is_the_high_percentile_of_apparent_length():
    # Apparent length peaks when the racket lies in the image plane; shorter readings are
    # foreshortening, so the estimate must track the top of the range, not the mean.
    vecs = [(np.zeros(2), np.array([L, 0.0])) for L in [0.2, 0.3, 0.4, 0.5, 0.6, 0.66]]
    assert lift.estimate_length(vecs) == pytest.approx(np.percentile(
        [0.2, 0.3, 0.4, 0.5, 0.6, 0.66], 90))


def test_length_estimate_refuses_too_few_samples():
    with pytest.raises(ValueError, match="cannot estimate"):
        lift.estimate_length([(np.zeros(2), np.array([0.6, 0.0]))])


def test_depth_solution_satisfies_the_length_constraint():
    vecs = [(np.zeros(2), np.array([0.4, 0.3]))]      # flat length 0.5
    (d,) = lift.resolve_depths(vecs, 0.65, [None])
    assert np.linalg.norm(d) == pytest.approx(0.65)
    assert abs(d[2]) == pytest.approx(np.sqrt(0.65 ** 2 - 0.5 ** 2))


def test_depth_clamps_when_the_racket_looks_longer_than_it_is():
    vecs = [(np.zeros(2), np.array([0.9, 0.0]))]
    (d,) = lift.resolve_depths(vecs, 0.65, [None])
    assert d[2] == pytest.approx(0.0)                  # no imaginary depth


def test_seed_follows_the_forearm():
    # Two signs are geometrically valid; the forearm prior decides the first one.
    vecs = [(np.zeros(2), np.array([0.3, 0.0]))]
    fwd = [np.array([0.0, 0.0, 1.0])]
    assert lift.resolve_depths(vecs, 0.65, fwd)[0][2] > 0
    back = [np.array([0.0, 0.0, -1.0])]
    assert lift.resolve_depths(vecs, 0.65, back)[0][2] < 0


def test_continuity_prevents_a_flip_mid_run():
    # Frame 0 is seeded toward +Z; frame 1 must stay on that side even though -Z is equally
    # valid geometrically. A racket cannot swap ends between two frames at 25 fps.
    vecs = [(np.zeros(2), np.array([0.3, 0.0])), (np.zeros(2), np.array([0.31, 0.0]))]
    ds = lift.resolve_depths(vecs, 0.65, [np.array([0.0, 0.0, 1.0]), None])
    assert ds[0][2] > 0 and ds[1][2] > 0


def test_each_run_is_seeded_independently_across_a_gap():
    # A stale sign must not be carried over a gap; run 2 re-seeds from its own forearm.
    vecs = [(np.zeros(2), np.array([0.3, 0.0])), None, (np.zeros(2), np.array([0.3, 0.0]))]
    fwd = [np.array([0.0, 0.0, 1.0]), None, np.array([0.0, 0.0, -1.0])]
    ds = lift.resolve_depths(vecs, 0.65, fwd)
    assert ds[0][2] > 0 and ds[1] is None and ds[2][2] < 0


def test_handedness_is_detected_from_the_grip_position():
    j = joints(2, hand_xy=(1.0, 0.5))
    t = track([rec(0, (1.0, 0.5), (1.5, 0.5)), rec(1, (1.0, 0.5), (1.5, 0.5))])
    side, scores = lift.detect_handedness(t, [CAM, CAM], j, FRAME_SIZE)
    assert side == "right"
    assert scores["right"] < scores["left"]


def test_series_marks_undetected_frames_as_a_zero_confidence_prior():
    j = joints(2)
    t = track([rec(0, (0.0, 0.0), (0.6, 0.0)), rec(1)])
    series, _ = lift.build_racket_series(t, [CAM, CAM], j, FRAME_SIZE, "right", 0.65)
    assert series[0]["status"] == lift.STATUS_MEASURED
    assert series[0]["confidence"] == pytest.approx(0.7)
    assert series[1]["status"] == lift.STATUS_PRIOR and series[1]["confidence"] == 0.0
    # the prior lays the racket along the forearm, starting at the hand
    assert series[1]["grip"] == pytest.approx(j[1][23])
    assert np.linalg.norm(series[1]["head"] - series[1]["grip"]) == pytest.approx(0.65)


def test_series_can_leave_gaps_empty():
    j = joints(2)
    t = track([rec(0, (0.0, 0.0), (0.6, 0.0)), rec(1)])
    series, _ = lift.build_racket_series(t, [CAM, CAM], j, FRAME_SIZE, "right", 0.65,
                                         fill_missing=False)
    assert series[1]["status"] == lift.STATUS_NONE and series[1]["grip"] is None


def test_grip_depth_comes_from_the_hand():
    j = joints(1, depth=4.2)
    t = track([rec(0, (0.0, 0.0), (0.6, 0.0))])
    series, _ = lift.build_racket_series(t, [CAM], j, FRAME_SIZE, "right", 0.65)
    assert series[0]["grip"][2] == pytest.approx(4.2)


def skeleton(n):
    return {"schema_version": "2.0", "video_id": "t", "skeleton": "smpl-24",
            "joint_names": [f"j{i}" for i in range(24)],
            "parents": [-1] + [0] * 23,
            "frames": [{"frame_id": i, "joints_flat": [0.0] * 96} for i in range(n)]}


def test_appended_joints_extend_the_tree_correctly():
    j = joints(2)
    t = track([rec(0, (0.0, 0.0), (0.6, 0.0)), rec(1)])
    series, _ = lift.build_racket_series(t, [CAM, CAM], j, FRAME_SIZE, "right", 0.65)
    doc = lift.append_racket_joints(skeleton(2), series, side="right", length=0.65,
                                    width=0.21, track_path="tr.json", camera_path="cam.json")
    assert doc["joint_names"][24:] == ["racket_grip", "racket_head", "racket_side"]
    assert doc["parents"][24:] == [21, 24, 25]        # grip hangs off the right wrist
    assert len(doc["frames"][0]["joints_flat"]) == 27 * 4
    assert doc["racket"]["coverage"]["measured"] == 1
    assert doc["racket"]["coverage"]["prior"] == 1
    assert doc["frames"][1]["racket_status"] == "prior"


def test_appended_joints_are_converted_to_the_unity_frame():
    # The other 24 joints are already Unity-frame; leaving these in camera space would put
    # the racket upside down and nothing would flag it.
    j = joints(1)
    t = track([rec(0, (0.0, 1.0), (0.6, 1.0))])
    series, _ = lift.build_racket_series(t, [CAM], j, FRAME_SIZE, "right", 0.65)
    doc = lift.append_racket_joints(skeleton(1), series, side="right", length=0.65,
                                    width=0.21, track_path="t", camera_path="c")
    flat = doc["frames"][0]["joints_flat"]
    grip_y = flat[24 * 4 + 1]
    assert grip_y == pytest.approx(-1.0)              # Y flipped by WORLD_TO_UNITY


EMPTY = [{"grip": None, "head": None, "side": None, "status": lift.STATUS_NONE,
          "confidence": 0.0, "roll_status": lift.ROLL_NONE}]


def test_missing_frames_are_written_as_zero_confidence_slots():
    doc = lift.append_racket_joints(skeleton(1), EMPTY, side="right", length=0.65,
                                    width=0.21, track_path="t", camera_path="c")
    assert doc["frames"][0]["joints_flat"][24 * 4:] == [0.0] * 12


def test_left_handed_clip_parents_the_grip_to_the_left_wrist():
    doc = lift.append_racket_joints(skeleton(1), EMPTY, side="left", length=0.65,
                                    width=0.21, track_path="t", camera_path="c")
    assert doc["parents"][24] == 20


# --- roll: the third degree of freedom -------------------------------------------------

def test_reference_frame_is_orthonormal_and_deterministic():
    d = np.array([0.3, -0.5, 0.8])
    d /= np.linalg.norm(d)
    ref, orth = lift.reference_frame(d)
    assert float(ref @ d) == pytest.approx(0.0, abs=1e-12)
    assert float(orth @ d) == pytest.approx(0.0, abs=1e-12)
    assert float(ref @ orth) == pytest.approx(0.0, abs=1e-12)
    assert np.linalg.norm(ref) == pytest.approx(1.0)
    # same shaft must always give the same zero, or smoothing chases its own frame
    assert lift.reference_frame(d)[0] == pytest.approx(ref)


def test_reference_frame_survives_a_vertical_shaft():
    # World "up" is the natural reference but degenerates when the shaft IS up.
    ref, orth = lift.reference_frame(np.array([0.0, 1.0, 0.0]))
    assert np.all(np.isfinite(ref)) and np.all(np.isfinite(orth))
    assert np.linalg.norm(ref) == pytest.approx(1.0)


def test_roll_angle_round_trips_through_a_vector():
    d = np.array([0.0, 0.0, 1.0])
    for theta in (-2.0, -0.3, 0.0, 0.7, 2.9):
        w = lift.roll_to_vector(d, theta)
        assert np.linalg.norm(w) == pytest.approx(1.0)
        assert float(w @ d) == pytest.approx(0.0, abs=1e-12)
        assert lift.roll_angle(d, w) == pytest.approx(theta)


def test_width_vector_is_perpendicular_to_the_shaft():
    d = np.array([1.0, 0.0, 0.0])
    kps = [None] * 5
    kps[NAMES.index("left")] = to_px((0.0, -0.1))
    kps[NAMES.index("right")] = to_px((0.0, 0.1))
    for i in range(5):
        if kps[i] is None:
            kps[i] = to_px((0.0, 0.0))
    w, correction = lift.width_vector(CAM, kps, NAMES, FRAME_SIZE, d, 0.21)
    assert float(w @ d) == pytest.approx(0.0, abs=1e-9)
    assert np.linalg.norm(w) == pytest.approx(1.0)
    assert correction >= 0.0


def test_width_vector_rejects_a_collapsed_rim():
    # left and right on the same pixel: no width, no roll information.
    d = np.array([0.0, 0.0, 1.0])
    kps = [to_px((0.0, 0.0))] * 5
    w, _ = lift.width_vector(CAM, kps, NAMES, FRAME_SIZE, d, 0.21)
    assert w is None


def test_unwrap_treats_roll_as_pi_periodic():
    # left/right are interchangeable, so a jump of ~pi is a relabelling, not a half turn.
    got = lift.unwrap_pi([0.05, 0.05 + np.pi, 0.05])
    assert got[1] == pytest.approx(0.05, abs=1e-9)
    assert got[2] == pytest.approx(0.05, abs=1e-9)


def test_unwrap_passes_gaps_through():
    got = lift.unwrap_pi([0.1, None, 0.1])
    assert got[1] is None


def test_smoothing_kills_an_isolated_outlier():
    angles = [0.10, 0.11, 1.40, 0.12, 0.13]      # one spike
    out = lift.smooth_rolls(angles, window=3)
    assert out[2] == pytest.approx(0.11, abs=0.05)


def test_smoothing_bridges_a_short_gap_only():
    out = lift.smooth_rolls([0.0, None, None, 0.4], window=1, max_gap=4)
    assert out[1] == pytest.approx(0.4 / 3)
    assert out[2] == pytest.approx(0.8 / 3)


def test_smoothing_refuses_to_bridge_a_long_gap():
    # Bridging 40 frames of nothing produces a curve that looks exactly like data.
    angles = [0.0] + [None] * 6 + [1.0]
    out = lift.smooth_rolls(angles, window=1, max_gap=4)
    assert all(v is None for v in out[1:7])


def test_smoothing_never_extrapolates_past_the_ends():
    out = lift.smooth_rolls([None, 0.5, None], window=1)
    assert out[0] is None and out[2] is None


def rec_roll(frame, grip_xy, tip_xy, half_w, scores=None):
    """A record whose left/right straddle the tip by half_w along +Y."""
    r = rec(frame, grip_xy, tip_xy)
    r["keypoints"][NAMES.index("left")] = to_px((tip_xy[0], tip_xy[1] - half_w))
    r["keypoints"][NAMES.index("right")] = to_px((tip_xy[0], tip_xy[1] + half_w))
    r["keypoint_scores"] = scores or [0.7] * 5
    return r


def test_roll_is_rejected_when_the_side_keypoints_are_weak():
    low = [0.7, 0.7, 0.7, 0.2, 0.7]              # `left` below the gate
    t = track([rec_roll(0, (0.0, 0.0), (0.6, 0.0), 0.1, scores=low)])
    deltas = [np.array([0.6, 0.0, 0.0])]
    angles, info = lift.solve_rolls(t, [CAM], FRAME_SIZE, deltas, 0.21)
    assert angles[0] is None
    assert info[0]["reason"] == "low_side_score"


def test_roll_is_solved_when_the_side_keypoints_are_good():
    t = track([rec_roll(0, (0.0, 0.0), (0.6, 0.0), 0.1)])
    deltas = [np.array([0.6, 0.0, 0.0])]
    angles, info = lift.solve_rolls(t, [CAM], FRAME_SIZE, deltas, 0.21)
    assert angles[0] is not None and info[0]["reason"] == "ok"


def test_roll_status_distinguishes_solved_from_bridged():
    j = joints(4)
    t = track([rec_roll(0, (0.0, 0.0), (0.6, 0.0), 0.1),
               rec(1, (0.0, 0.0), (0.6, 0.0)),          # no usable rim -> bridged
               rec_roll(2, (0.0, 0.0), (0.6, 0.0), 0.1),
               rec(3)])                                  # no racket at all
    series, _ = lift.build_racket_series(t, [CAM] * 4, j, FRAME_SIZE, "right", 0.65,
                                         width=0.21)
    assert series[0]["roll_status"] == lift.ROLL_MEASURED
    assert series[2]["roll_status"] == lift.ROLL_MEASURED
    assert series[3]["roll_status"] == lift.ROLL_NONE


def test_side_joint_completes_the_racket_frame():
    j = joints(1)
    t = track([rec_roll(0, (0.0, 0.0), (0.6, 0.0), 0.1)])
    series, _ = lift.build_racket_series(t, [CAM], j, FRAME_SIZE, "right", 0.65, width=0.21)
    e = series[0]
    across = e["side"] - e["head"]
    shaft = e["head"] - e["grip"]
    assert np.linalg.norm(across) == pytest.approx(0.21 / 2)
    assert float(across @ shaft) == pytest.approx(0.0, abs=1e-9)   # in the racket plane
    assert np.linalg.norm(np.cross(shaft, across)) > 1e-6          # a real normal exists


def test_racket_is_a_bare_line_when_roll_is_disabled():
    j = joints(1)
    t = track([rec_roll(0, (0.0, 0.0), (0.6, 0.0), 0.1)])
    series, _ = lift.build_racket_series(t, [CAM], j, FRAME_SIZE, "right", 0.65, width=None)
    assert series[0]["roll_status"] == lift.ROLL_NONE
    assert series[0]["side"] == pytest.approx(series[0]["head"])   # zero-width offset


def test_roll_confidence_is_zeroed_when_roll_is_unknown():
    j = joints(1)
    t = track([rec(0, (0.0, 0.0), (0.6, 0.0))])
    series, _ = lift.build_racket_series(t, [CAM], j, FRAME_SIZE, "right", 0.65, width=None)
    doc = lift.append_racket_joints(skeleton(1), series, side="right", length=0.65,
                                    width=0.21, track_path="t", camera_path="c")
    flat = doc["frames"][0]["joints_flat"]
    assert flat[25 * 4 + 3] > 0.0        # head keeps the position confidence
    assert flat[26 * 4 + 3] == 0.0       # side does not inherit it
