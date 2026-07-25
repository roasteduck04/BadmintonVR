import numpy as np
import pytest

import racket_smoothing as rs


def rigid_series(n, jitter=0.0, seed=0, length=0.69, half_width=0.105, rate=0.1):
    """A racket swinging smoothly, optionally with per-frame noise added to every point.

    `rate` is radians of shaft rotation per frame — at 25 fps, 0.1 is a brisk 2.5 rad/s.
    """
    rng = np.random.default_rng(seed)
    grips, heads, sides = [], [], []
    for i in range(n):
        t = i * rate
        g = np.array([0.1 * i, 0.0, 1.0])
        d = np.array([np.cos(t), np.sin(t), 0.0])
        w = np.array([0.0, 0.0, 1.0])
        h = g + length * d
        s = h + half_width * w
        if jitter:
            g = g + rng.normal(scale=jitter, size=3)
            h = h + rng.normal(scale=jitter, size=3)
            s = s + rng.normal(scale=jitter, size=3)
        grips.append(g), heads.append(h), sides.append(s)
    return np.array(grips), np.array(heads), np.array(sides)


def test_spring_converges_to_a_constant_input():
    out = rs.spring_smooth(np.full(60, 5.0), fps=25)
    assert out[-1] == pytest.approx(5.0, abs=1e-6)


def test_spring_starts_at_the_first_sample():
    # Seeding from the first value avoids a visible lurch from zero on frame 1.
    out = rs.spring_smooth(np.array([7.0, 7.0, 7.0]), fps=25)
    assert out[0] == pytest.approx(7.0)


def test_causal_pass_lags_a_step_rather_than_following_it():
    out = rs.spring_smooth(np.array([0.0] + [1.0] * 40), fps=25, tau=0.12, zero_phase=False)
    assert out[1] < 0.5          # does not jump
    assert out[-1] > 0.95        # but does get there


def test_spring_reduces_jitter():
    rng = np.random.default_rng(0)
    noisy = rng.normal(scale=1.0, size=1000)
    out = rs.spring_smooth(noisy, fps=25)
    assert np.std(np.diff(out)) < 0.15 * np.std(np.diff(noisy))   # measured ~93% reduction


def test_zero_phase_has_no_lag_but_the_causal_pass_does():
    # Offline data, so lag is a choice we do not have to make. At 8.8 m/s the smash would
    # otherwise drag the racket most of a metre behind the hand holding it.
    ramp = np.arange(400) * 0.1
    zp = rs.spring_smooth(ramp, fps=25, tau=0.12)
    causal = rs.spring_smooth(ramp, fps=25, tau=0.12, zero_phase=False)
    assert abs(np.mean((ramp - zp)[100:300])) < 1e-6
    assert np.mean((ramp - causal)[100:300]) > 0.15                # ~2.5 frames behind


def test_filter_is_stable_at_small_tau():
    # Explicit Euler blows up once omega*dt approaches 1 (tau < ~0.1 s at 25 fps); the
    # exact integrator must not.
    rng = np.random.default_rng(1)
    for tau in (0.02, 0.05, 0.09):
        out = rs.spring_smooth(rng.normal(size=500), fps=25, tau=tau)
        assert np.all(np.isfinite(out)), tau
        assert np.abs(out).max() < 10.0, tau


def test_spring_handles_multichannel_input():
    vals = np.tile(np.array([1.0, 2.0, 3.0]), (30, 1))
    out = rs.spring_smooth(vals, fps=25)
    assert out.shape == (30, 3)
    assert out[-1] == pytest.approx([1.0, 2.0, 3.0], abs=1e-6)


def test_spring_leaves_invalid_frames_untouched():
    vals = np.array([0.0, 99.0, 0.0, 0.0, 0.0])
    valid = np.array([True, False, True, True, True])
    out = rs.spring_smooth(vals, fps=25, valid=valid)
    assert out[1] == 99.0        # passed through, not filtered


def test_spring_resets_across_a_gap():
    # The run after the gap must start from its own first sample, not drift up from the
    # pre-gap state — otherwise a prior-filled stretch drags real motion toward it.
    vals = np.array([0.0, 0.0, 0.0, 50.0, 10.0, 10.0])
    valid = np.array([True, True, True, False, True, True])
    out = rs.spring_smooth(vals, fps=25, valid=valid)
    assert out[4] == pytest.approx(10.0)


def test_align_signs_flips_a_relabelled_vector():
    v = np.array([[1.0, 0, 0], [-1.0, 0, 0], [1.0, 0, 0]])
    out = rs.align_signs(v)
    assert out[1] == pytest.approx([1.0, 0.0, 0.0])
    assert out[2] == pytest.approx([1.0, 0.0, 0.0])


def test_align_signs_keeps_genuine_direction_changes():
    v = np.array([[1.0, 0, 0], [0.0, 1.0, 0]])     # 90 deg apart: not a sign flip
    out = rs.align_signs(v)
    assert out[1] == pytest.approx([0.0, 1.0, 0.0])


def test_smoothing_preserves_length_and_width():
    g, h, s = rigid_series(80, jitter=0.01, seed=1)
    gs, hs, ss = rs.smooth_racket(g, h, s, fps=25)
    lens = np.linalg.norm(hs - gs, axis=1)
    wids = np.linalg.norm(ss - hs, axis=1)
    assert np.std(lens) < 1e-9          # rigid by construction, not approximately
    assert np.std(wids) < 1e-9
    assert lens[0] == pytest.approx(0.69, abs=0.01)
    assert wids[0] == pytest.approx(0.105, abs=0.01)


def test_smoothing_keeps_the_head_square_to_the_shaft():
    g, h, s = rigid_series(60, jitter=0.01, seed=2)
    gs, hs, ss = rs.smooth_racket(g, h, s, fps=25)
    shaft = hs - gs
    across = ss - hs
    dots = np.abs(np.einsum("ij,ij->i", shaft, across))
    assert dots.max() < 1e-9            # smoothing must not shear the head off the shaft


def test_smoothing_moves_the_racket_closer_to_the_truth():
    # Measured against the clean series, not std(diff): this fixture's genuine swing
    # dominates the frame-to-frame step, so a diff-based metric would barely register the
    # noise being removed and would pass for the wrong reason.
    _, clean_h, _ = rigid_series(120, jitter=0.0, seed=3, rate=0.02)
    g, h, s = rigid_series(120, jitter=0.02, seed=3, rate=0.02)
    _, hs, _ = rs.smooth_racket(g, h, s, fps=25)
    err_raw = np.linalg.norm(h - clean_h, axis=1).mean()
    err_smooth = np.linalg.norm(hs - clean_h, axis=1).mean()
    # ~0.5, not ~0.07: tau=0.12 s at 25 fps averages only a few frames, so RMS error
    # against the truth halves even though frame-to-frame jitter drops by 93%.
    assert err_smooth < 0.55 * err_raw


def test_smoothing_a_fast_swing_costs_accuracy():
    # The trade-off, pinned down rather than hidden: at tau=0.12 s a racket turning
    # 2.5 rad/s moves ~17 degrees within the smoothing window, so the filter blurs real
    # motion as well as noise and the gain over raw shrinks to almost nothing. Anyone
    # tuning tau upward for a prettier idle pose is paying for it during the stroke.
    _, clean_h, _ = rigid_series(120, jitter=0.0, seed=3, rate=0.1)
    g, h, s = rigid_series(120, jitter=0.02, seed=3, rate=0.1)
    _, hs, _ = rs.smooth_racket(g, h, s, fps=25)
    err_raw = np.linalg.norm(h - clean_h, axis=1).mean()
    err_smooth = np.linalg.norm(hs - clean_h, axis=1).mean()
    assert 0.5 * err_raw < err_smooth < err_raw


def test_smoothing_survives_a_sign_flipped_width_vector():
    g, h, s = rigid_series(40, jitter=0.0, seed=4)
    s = s.copy()
    s[20] = h[20] - (s[20] - h[20])          # relabelled left/right on one frame
    gs, hs, ss = rs.smooth_racket(g, h, s, fps=25)
    wid = np.linalg.norm(ss - hs, axis=1)
    assert wid.min() > 0.05                  # the plane never collapses
    assert np.std(wid) < 1e-9


def test_invalid_frames_pass_through_unchanged():
    g, h, s = rigid_series(30, jitter=0.01, seed=5)
    valid = np.ones(30, dtype=bool)
    valid[10:14] = False
    gs, hs, ss = rs.smooth_racket(g, h, s, fps=25, valid=valid)
    assert gs[10:14] == pytest.approx(g[10:14])
    assert hs[10:14] == pytest.approx(h[10:14])


def test_all_invalid_input_is_returned_untouched():
    g, h, s = rigid_series(10, jitter=0.01, seed=6)
    gs, hs, ss = rs.smooth_racket(g, h, s, fps=25, valid=np.zeros(10, dtype=bool))
    assert gs == pytest.approx(g) and hs == pytest.approx(h) and ss == pytest.approx(s)


def test_empty_input_does_not_crash():
    assert len(rs.spring_smooth(np.zeros((0, 3)), fps=25)) == 0
