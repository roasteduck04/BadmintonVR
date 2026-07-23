import json
import subprocess
import sys

import numpy as np
import pytest

import smpl_to_skeleton as s2s


def test_constants_are_consistent():
    assert s2s.NUM_SMPL_JOINTS == 24
    assert len(s2s.SMPL_JOINT_NAMES) == 24
    assert len(s2s.SMPL_PARENTS) == 24
    assert s2s.SMPL_PARENTS[0] == -1
    # every non-root parent is a valid earlier joint index (a well-formed tree)
    for j, p in enumerate(s2s.SMPL_PARENTS[1:], start=1):
        assert 0 <= p < j
    # spine chain is present and correctly linked
    n = s2s.SMPL_JOINT_NAMES
    assert n[3] == "spine1" and s2s.SMPL_PARENTS[3] == 0
    assert n[6] == "spine2" and s2s.SMPL_PARENTS[6] == 3
    assert n[9] == "spine3" and s2s.SMPL_PARENTS[9] == 6
    assert n[12] == "neck" and s2s.SMPL_PARENTS[12] == 9
    assert n[15] == "head" and s2s.SMPL_PARENTS[15] == 12


def test_apply_transform_flips_z_by_default():
    pts = np.array([[1.0, 2.0, 3.0]])
    out = s2s.apply_transform(pts)
    np.testing.assert_allclose(out, [[1.0, 2.0, -3.0]])


def test_apply_transform_rejects_bad_shape():
    with pytest.raises(ValueError):
        s2s.apply_transform(np.zeros((4, 2)))


def test_build_v2_document_shape_and_schema():
    T = 5
    joints = np.random.RandomState(0).rand(T, 24, 3)
    doc = s2s.build_v2_document("clipA", joints, fps=30.0)
    assert doc["schema_version"] == "2.0"
    assert doc["skeleton"] == "smpl-24"
    assert doc["coordinate_system"] == "unity"
    assert doc["joint_names"] == s2s.SMPL_JOINT_NAMES
    assert doc["parents"] == s2s.SMPL_PARENTS
    assert len(doc["frames"]) == T
    f0 = doc["frames"][0]
    assert len(f0["joints_flat"]) == 24 * 4       # flat 24 x [x,y,z,conf]
    assert len(f0["root_world"]) == 3
    assert f0["root_court_xz"] is None
    # default confidence is 1.0
    assert f0["joints_flat"][3] == 1.0


def test_build_v2_document_applies_transform_to_joints():
    joints = np.zeros((1, 24, 3))
    joints[0, 0] = [1.0, 2.0, 3.0]               # pelvis
    doc = s2s.build_v2_document("clipB", joints, fps=30.0)
    fl = doc["frames"][0]["joints_flat"]
    assert fl[0:3] == [1.0, 2.0, -3.0]           # z flipped
    assert doc["frames"][0]["root_world"] == [1.0, 2.0, -3.0]


def test_build_v2_document_includes_smpl_block_when_pose_given():
    T = 2
    joints = np.zeros((T, 24, 3))
    pose = np.random.RandomState(1).rand(T, 72)
    betas = np.random.RandomState(2).rand(10)
    transl = np.random.RandomState(3).rand(T, 3)
    doc = s2s.build_v2_document("clipC", joints, fps=30.0, pose=pose, betas=betas, transl=transl)
    assert len(doc["betas"]) == 10
    smpl = doc["frames"][0]["smpl"]
    assert len(smpl["global_orient"]) == 3
    assert len(smpl["body_pose"]) == 69
    assert len(smpl["transl"]) == 3


def test_make_synthetic_is_wellformed_and_travels():
    doc = s2s.make_synthetic(frames=10)
    assert len(doc["frames"]) == 10
    assert len(doc["frames"][0]["joints_flat"]) == 24 * 4
    # pelvis x increases over time (the twin travels along +X)
    x0 = doc["frames"][0]["joints_flat"][0]
    x9 = doc["frames"][9]["joints_flat"][0]
    assert x9 > x0


def test_load_wham_output_normalizes_npz(tmp_path):
    npz = tmp_path / "clip.wham.npz"
    T = 4
    np.savez(npz,
             joints3d=np.random.RandomState(0).rand(T, 24, 3),
             pose=np.random.RandomState(1).rand(T, 72),
             betas=np.random.RandomState(2).rand(10),
             transl=np.random.RandomState(3).rand(T, 3),
             fps=np.array(30.0))
    data = s2s.load_wham_output(str(npz))
    assert data["joints3d"].shape == (T, 24, 3)
    assert data["pose"].shape == (T, 72)
    assert data["betas"].shape == (10,)
    assert data["transl"].shape == (T, 3)
    assert float(data["fps"]) == 30.0


def test_load_wham_output_requires_joints(tmp_path):
    npz = tmp_path / "bad.wham.npz"
    np.savez(npz, pose=np.zeros((3, 72)))
    with pytest.raises((KeyError, ValueError)):
        s2s.load_wham_output(str(npz))


def test_cli_synthetic_writes_valid_v2(tmp_path):
    out = tmp_path / "demo.skeleton.json"
    subprocess.run(
        [sys.executable, "tools/smpl_to_skeleton.py", "--synthetic",
         "--frames", "6", "--out", str(out)],
        check=True, cwd=".")
    doc = json.loads(out.read_text())
    assert doc["schema_version"] == "2.0"
    assert len(doc["frames"]) == 6
    assert len(doc["joint_names"]) == 24


def test_make_synthetic_labels_source_synthetic():
    doc = s2s.make_synthetic(frames=3)
    assert doc["source"]["type"] == "synthetic"


def test_build_v2_document_source_type_override():
    joints = np.zeros((1, 24, 3))
    doc = s2s.build_v2_document("c", joints, fps=30.0, source_type="multiview_rgb", notes="pose2sim")
    assert doc["source"]["type"] == "multiview_rgb"
    assert doc["extractor"]["notes"] == "pose2sim"


def test_cli_wham_output_roundtrip(tmp_path):
    npz = tmp_path / "clip.wham.npz"
    T = 4
    np.savez(npz,
             joints3d=np.random.RandomState(0).rand(T, 24, 3),
             pose=np.random.RandomState(1).rand(T, 72),
             betas=np.random.RandomState(2).rand(10),
             transl=np.random.RandomState(3).rand(T, 3),
             fps=np.array(50.0))
    out = tmp_path / "wtest.skeleton.json"
    s2s.main(["--wham-output", str(npz), "--video-id", "wtest", "--out", str(out)])
    doc = json.loads(out.read_text())
    assert doc["schema_version"] == "2.0"
    assert doc["video_id"] == "wtest"
    assert len(doc["frames"]) == T
    assert doc["source"]["type"] == "monocular_rgb"       # WHAM path keeps the monocular default
    assert doc["source"]["fps"] == 50.0                    # fps came from the npz
    assert len(doc["betas"]) == 10
    smpl = doc["frames"][0]["smpl"]
    assert len(smpl["body_pose"]) == 69 and len(smpl["global_orient"]) == 3
