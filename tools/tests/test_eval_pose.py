import json

import numpy as np
import pytest

import eval_pose as ep
import smpl_to_skeleton as s2s


def test_load_skeleton_joints_from_synthetic(tmp_path):
    doc = s2s.make_synthetic(frames=5)
    p = tmp_path / "demo.skeleton.json"
    p.write_text(json.dumps(doc))
    joints, names = ep.load_skeleton_joints(str(p))
    assert joints.shape == (5, 24, 3)
    assert names == s2s.SMPL_JOINT_NAMES
    # first three floats of joints_flat == the joint's xyz
    assert np.allclose(joints[0, 0], doc["frames"][0]["joints_flat"][0:3])


def test_mpjpe_zero_for_identical():
    x = np.random.RandomState(0).rand(3, 24, 3)
    assert ep.mpjpe(x, x) == pytest.approx(0.0)


def test_match_joints_returns_common_indices():
    pred = ["pelvis", "neck", "head"]
    gt = ["head", "pelvis"]
    pi, gi = ep.match_joints(pred, gt)
    assert list(pred[i] for i in pi) == list(gt[i] for i in gi)
    assert set(pred[i] for i in pi) == {"pelvis", "head"}


def test_pa_mpjpe_invariant_to_similarity_transform():
    rng = np.random.RandomState(42)
    gt = rng.rand(4, 24, 3)
    # a random rotation, scale, translation applied to gt -> pred
    a = 0.7
    R = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    s, t = 2.5, np.array([3.0, -1.0, 0.5])
    pred = (s * (gt @ R.T)) + t
    assert ep.mpjpe(pred, gt) > 0.1                 # raw error is large
    assert ep.pa_mpjpe(pred, gt) == pytest.approx(0.0, abs=1e-6)  # alignment removes it
