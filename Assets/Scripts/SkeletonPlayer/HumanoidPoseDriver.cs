using System.Collections.Generic;
using System.IO;
using UnityEngine;

namespace BadmintonVR.SkeletonPlayer
{
    /// <summary>
    /// Drives a rigged Humanoid (Mecanim) avatar from a skeleton.json clip by
    /// retargeting the 33 MediaPipe joints onto the rig's bones.
    ///
    /// Method (rotation-only, so the avatar keeps its OWN proportions):
    /// at Start we cache each driven bone's rest world-rotation and the rest
    /// world-direction to its child. Each frame we align that rest direction to
    /// the captured joint direction and re-apply from rest (no drift). The whole
    /// body is oriented by the pelvis basis (hips), and every limb segment is
    /// aligned absolutely, so facing errors never break the limb articulation.
    ///
    /// Root translation (Phase 2): clips extracted with --court carry
    /// `root_court_xz` (player ground position in court meters, origin at court
    /// center — the court itself is built at the world origin). When present and
    /// driveRootPosition is on, the avatar root is moved to that XZ each frame;
    /// clips without it play in place, exactly as in Phase 1.
    /// </summary>
    [RequireComponent(typeof(Animator))]
    public class HumanoidPoseDriver : MonoBehaviour
    {
        [Header("Clip")]
        [Tooltip("Path under Assets/StreamingAssets, e.g. skeleton/clip.json")]
        public string streamingAssetsPath = "skeleton/20260715_clears_sideview.json";
        public bool playOnStart = true;
        public bool loop = true;
        [Range(0.1f, 2f)] public float speed = 1f;

        [Header("Retargeting")]
        [Tooltip("Orient the whole body from the pelvis basis. Turn off if the " +
                 "torso looks wrong; the avatar then stands facing forward but " +
                 "arms/legs still articulate.")]
        public bool driveHips = true;
        [Tooltip("Flip body facing 180° about Y (analogous to the extractor's --flip-z).")]
        public bool faceFlip = false;
        [Tooltip("Joints below this confidence don't update their bone (holds last pose).")]
        [Range(0f, 1f)] public float confidenceCutoff = 0.3f;
        [Tooltip("Temporal smoothing: 0 = raw, 1 = very smooth (laggy).")]
        [Range(0f, 0.95f)] public float smoothing = 0.35f;

        [Header("Root position (Phase 2)")]
        [Tooltip("Move the avatar to root_court_xz when the clip has it (extracted with --court).")]
        public bool driveRootPosition = true;
        [Tooltip("Frames whose root confidence is below this hold the last position.")]
        [Range(0f, 1f)] public float rootConfidenceCutoff = 0.2f;
        [Tooltip("Smoothing for the root position: 0 = raw, 1 = very smooth (laggy).")]
        [Range(0f, 0.95f)] public float rootSmoothing = 0.2f;

        // MediaPipe landmark indices used here.
        const int NOSE = 0, L_SHO = 11, R_SHO = 12, L_ELB = 13, R_ELB = 14,
                  L_WRI = 15, R_WRI = 16, L_HIP = 23, R_HIP = 24, L_KNE = 25,
                  R_KNE = 26, L_ANK = 27, R_ANK = 28;

        struct Drive
        {
            public Transform bone;       // bone we rotate
            public Transform childRef;   // bone that defines the rest direction
            public int startLm, endLm;   // captured direction = end - start
            public Quaternion restRot;   // world rotation at bind
            public Vector3 restDir;      // world child direction at bind
            public Quaternion current;   // last applied (for smoothing)
        }

        Animator _anim;
        SkeletonDoc _doc;
        readonly List<Drive> _drives = new List<Drive>();

        // Pelvis basis (hips) rest data.
        Transform _hips;
        Quaternion _hipsRestRot, _hipsRestBasis;
        Quaternion _hipsCurrent;
        bool _hipsReady;

        float _t;
        bool _playing;
        float _rootY;          // spawn height, preserved while moving on XZ
        Vector3 _rootCurrent;  // last applied root position (for smoothing)
        bool _rootActive;

        public SkeletonDoc Doc => _doc;
        public bool IsPlaying => _playing;

        void Awake() => _anim = GetComponent<Animator>();

        void Start()
        {
            if (!_anim.isHuman)
            {
                Debug.LogError("[HumanoidPoseDriver] Avatar is not a Humanoid rig. " +
                    "Re-import the model with Rig > Animation Type = Humanoid.");
                enabled = false;
                return;
            }

            _doc = SkeletonDoc.Load(streamingAssetsPath);
            if (_doc == null) { enabled = false; return; }

            CacheRig();

            _rootActive = driveRootPosition && _doc.HasRoot;
            _rootY = transform.position.y;
            _rootCurrent = transform.position;
            if (_rootActive)
            {
                // jump straight to the clip's start position (no lerp-in from spawn)
                Vector2 xz = _doc.RootXZ(0);
                _rootCurrent = new Vector3(xz.x, _rootY, xz.y);
                transform.position = _rootCurrent;
            }

            _playing = playOnStart;
            ApplyFrame(0); // show a pose immediately
        }

        void CacheRig()
        {
            _drives.Clear();
            AddDrive(HumanBodyBones.LeftUpperArm, HumanBodyBones.LeftLowerArm, L_SHO, L_ELB);
            AddDrive(HumanBodyBones.LeftLowerArm, HumanBodyBones.LeftHand, L_ELB, L_WRI);
            AddDrive(HumanBodyBones.RightUpperArm, HumanBodyBones.RightLowerArm, R_SHO, R_ELB);
            AddDrive(HumanBodyBones.RightLowerArm, HumanBodyBones.RightHand, R_ELB, R_WRI);
            AddDrive(HumanBodyBones.LeftUpperLeg, HumanBodyBones.LeftLowerLeg, L_HIP, L_KNE);
            AddDrive(HumanBodyBones.LeftLowerLeg, HumanBodyBones.LeftFoot, L_KNE, L_ANK);
            AddDrive(HumanBodyBones.RightUpperLeg, HumanBodyBones.RightLowerLeg, R_HIP, R_KNE);
            AddDrive(HumanBodyBones.RightLowerLeg, HumanBodyBones.RightFoot, R_KNE, R_ANK);

            _hips = _anim.GetBoneTransform(HumanBodyBones.Hips);
            var lUp = _anim.GetBoneTransform(HumanBodyBones.LeftUpperLeg);
            var rUp = _anim.GetBoneTransform(HumanBodyBones.RightUpperLeg);
            var lArm = _anim.GetBoneTransform(HumanBodyBones.LeftUpperArm);
            var rArm = _anim.GetBoneTransform(HumanBodyBones.RightUpperArm);
            _hipsReady = _hips && lUp && rUp && lArm && rArm;
            if (_hipsReady)
            {
                Vector3 hipMid = (lUp.position + rUp.position) * 0.5f;
                Vector3 shoMid = (lArm.position + rArm.position) * 0.5f;
                Vector3 up = (shoMid - hipMid).normalized;
                Vector3 right = (rUp.position - lUp.position).normalized;
                _hipsRestRot = _hips.rotation;
                _hipsRestBasis = BasisRot(right, up);
                _hipsCurrent = _hipsRestRot;
            }
        }

        void AddDrive(HumanBodyBones bone, HumanBodyBones child, int a, int b)
        {
            var tf = _anim.GetBoneTransform(bone);
            var ctf = _anim.GetBoneTransform(child);
            if (tf == null || ctf == null) return; // optional bone missing on this rig
            _drives.Add(new Drive
            {
                bone = tf,
                childRef = ctf,
                startLm = a,
                endLm = b,
                restRot = tf.rotation,
                restDir = (ctf.position - tf.position).normalized,
                current = tf.rotation,
            });
        }

        void Update()
        {
            if (_doc == null || !_playing) return;
            _t += Time.deltaTime * speed;
            float dur = _doc.Duration;
            if (dur <= 0f) return;
            if (_t > dur) { if (loop) _t %= dur; else { _t = dur; _playing = false; } }
            ApplyFrame(FrameForTime(_t));
        }

        int FrameForTime(float t)
        {
            int f = Mathf.RoundToInt(t * _doc.Fps);
            return Mathf.Clamp(f, 0, _doc.FrameCount - 1);
        }

        void ApplyFrame(int frame)
        {
            // Root position first: the whole body rides on it.
            if (_rootActive && _doc.RootConf(frame) >= rootConfidenceCutoff)
            {
                Vector2 xz = _doc.RootXZ(frame);
                Vector3 target = new Vector3(xz.x, _rootY, xz.y);
                _rootCurrent = rootSmoothing <= 0f
                    ? target
                    : Vector3.Lerp(target, _rootCurrent, rootSmoothing);
                transform.position = _rootCurrent;
            }

            // Body orientation first so limb parents settle.
            if (driveHips && _hipsReady)
            {
                bool ok = Conf(frame, L_HIP) && Conf(frame, R_HIP) &&
                          Conf(frame, L_SHO) && Conf(frame, R_SHO);
                if (ok)
                {
                    Vector3 hipMid = (P(frame, L_HIP) + P(frame, R_HIP)) * 0.5f;
                    Vector3 shoMid = (P(frame, L_SHO) + P(frame, R_SHO)) * 0.5f;
                    Vector3 up = (shoMid - hipMid);
                    Vector3 right = (P(frame, R_HIP) - P(frame, L_HIP));
                    if (faceFlip) right = -right;
                    Quaternion tgtBasis = BasisRot(
                        transform.rotation * right, transform.rotation * up);
                    Quaternion target = tgtBasis * Quaternion.Inverse(_hipsRestBasis) * _hipsRestRot;
                    _hipsCurrent = Smooth(_hipsCurrent, target);
                    _hips.rotation = _hipsCurrent;
                }
            }

            for (int i = 0; i < _drives.Count; i++)
            {
                var d = _drives[i];
                if (!Conf(frame, d.startLm) || !Conf(frame, d.endLm)) continue;
                Vector3 tgt = transform.rotation * (P(frame, d.endLm) - P(frame, d.startLm));
                if (tgt.sqrMagnitude < 1e-8f) continue;
                Quaternion delta = Quaternion.FromToRotation(d.restDir, tgt.normalized);
                Quaternion target = delta * d.restRot;
                d.current = Smooth(d.current, target);
                d.bone.rotation = d.current;
                _drives[i] = d;
            }
        }

        Quaternion Smooth(Quaternion cur, Quaternion target)
            => smoothing <= 0f ? target : Quaternion.Slerp(target, cur, smoothing);

        // Build a rotation whose axes come from a (right, up) pair.
        static Quaternion BasisRot(Vector3 right, Vector3 up)
        {
            up = up.normalized;
            Vector3 fwd = Vector3.Cross(right.normalized, up).normalized;
            if (fwd.sqrMagnitude < 1e-8f) return Quaternion.identity;
            return Quaternion.LookRotation(fwd, up);
        }

        Vector3 P(int frame, int lm) => _doc.JointPos(frame, lm);
        bool Conf(int frame, int lm) => _doc.JointConf(frame, lm) >= confidenceCutoff;

        // --- simple external control (optional) ---
        public void Play() => _playing = true;
        public void Pause() => _playing = false;
        public void TogglePlay() => _playing = !_playing;
    }
}
