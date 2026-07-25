import numpy as np
import pytest

import fit_camera as fc


def synth_points(n=12, seed=0):
    rng = np.random.default_rng(seed)
    p3 = rng.normal(size=(n, 3))
    p3[:, 2] += 5.0                       # in front of the camera
    return p3


def test_mapping_indices_are_in_range():
    assert all(0 <= mp < 33 for mp in fc.MP_TO_SMPL)
    assert all(0 <= sm < 24 for sm in fc.MP_TO_SMPL.values())
    # a landmark must not be claimed by two SMPL joints, or the fit is double-counting
    assert len(set(fc.MP_TO_SMPL.values())) == len(fc.MP_TO_SMPL)


def test_fit_recovers_a_known_weak_perspective_camera():
    truth = {"s": 0.21, "tx": 0.48, "ty": 0.33}
    p3 = synth_points()
    uv = fc.project(truth, p3)
    got = fc.fit_frame(p3, uv)
    for k, v in truth.items():
        assert got[k] == pytest.approx(v, abs=1e-9)
    assert got["rms"] == pytest.approx(0.0, abs=1e-9)
    assert got["n_points"] == 12


def test_fit_is_unaffected_by_depth():
    # Weak perspective ignores Z by definition; moving points in depth must not change it.
    p3 = synth_points()
    uv = fc.project({"s": 0.2, "tx": 0.5, "ty": 0.4}, p3)
    shifted = p3.copy()
    shifted[:, 2] += 3.0
    assert fc.fit_frame(shifted, uv)["s"] == pytest.approx(0.2, abs=1e-9)


def test_fit_returns_none_when_underdetermined():
    p3 = synth_points(n=3)
    assert fc.fit_frame(p3, fc.project({"s": 0.2, "tx": 0.0, "ty": 0.0}, p3)) is None


def test_fit_rejects_a_degenerate_negative_scale():
    p3 = synth_points()
    uv = fc.project({"s": -0.2, "tx": 0.5, "ty": 0.4}, p3)
    assert fc.fit_frame(p3, uv) is None


def test_fit_reports_residual_when_the_data_does_not_agree():
    p3 = synth_points()
    uv = fc.project({"s": 0.2, "tx": 0.5, "ty": 0.4}, p3)
    uv[0] += 0.1
    assert fc.fit_frame(p3, uv)["rms"] > 0.01


def test_unproject_inverts_project_in_xy():
    cam = {"s": 0.2, "tx": 0.5, "ty": 0.4}
    p = np.array([1.5, -0.7, 4.2])
    back = fc.unproject_xy(cam, fc.project(cam, p))
    assert back == pytest.approx(p[:2])


def test_normalize_by_width_makes_axes_isotropic():
    # MediaPipe gives x/W and y/H; a square in pixels must come out square afterwards.
    pts = np.array([[[0.5, 0.5]]])
    out = fc.normalize_by_width(pts, width=1920, height=1080)
    assert out[0, 0, 0] == pytest.approx(0.5)
    assert out[0, 0, 1] == pytest.approx(0.5 * 1080 / 1920)


def series_fixture(frames=2, seed=1):
    """joints3d plus the 2D landmarks a known camera would produce for them."""
    truth = {"s": 0.2, "tx": 0.5, "ty": 0.3}
    rng = np.random.default_rng(seed)
    joints3d = rng.normal(size=(frames, 24, 3))
    joints3d[..., 2] += 5.0
    img = np.zeros((frames, 33, 2))
    for t in range(frames):
        for mp_i, smpl_i in fc.MP_TO_SMPL.items():
            img[t, mp_i] = fc.project(truth, joints3d[t, smpl_i])
    return joints3d, img, truth


def test_series_skips_frames_with_too_few_visible_landmarks():
    joints3d, img, truth = series_fixture(2)
    mp_idx = list(fc.MP_TO_SMPL)
    vis = np.zeros((2, 33))
    vis[0, mp_idx] = 1.0                  # frame 0 fully visible
    vis[1, mp_idx[:2]] = 1.0              # frame 1 has only 2 -> below MIN_POINTS
    cams = fc.fit_series(img, vis, joints3d)
    assert cams[0] is not None and cams[0]["frame"] == 0
    assert cams[0]["s"] == pytest.approx(truth["s"], abs=1e-9)
    assert cams[1] is None


def test_series_stops_at_the_shorter_input():
    joints3d, img, _ = series_fixture(1)
    img = np.repeat(img, 5, axis=0)
    assert len(fc.fit_series(img, np.ones((5, 33)), joints3d)) == 1
