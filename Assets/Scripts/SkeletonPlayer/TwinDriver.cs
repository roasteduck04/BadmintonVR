using UnityEngine;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
#endif

namespace BadmintonVR.SkeletonPlayer
{
    /// <summary>
    /// Track B: the PERSISTENT twin driver (docs/ai-smoothing-plan.md).
    ///
    /// Instead of teleporting the twin to raw MediaPipe data every frame, ONE
    /// body is kept alive and each capture frame becomes a TARGET it moves
    /// toward:
    ///   - critically-damped springs on the root and every joint (still when
    ///     the player is still, fast when lunging — no fixed-lag Lerp);
    ///   - analytic two-bone IK for elbows/knees, so limb segments keep the
    ///     clip's median bone lengths (no "breathing" limbs) and intermediate
    ///     joints stay human even on noisy frames;
    ///   - FOOT LOCKING: a planted foot is pinned so it can't ice-skate;
    ///   - LOOKAHEAD: clips are recorded files, so the driver may peek
    ///     `lookaheadSeconds` ahead and steer toward where the player is
    ///     GOING — smoothness without lag. Set 0 for causal (Phase-5 preview).
    ///   - joints never pop in/out: below-confidence frames just stop moving
    ///     the target and the spring holds.
    ///
    /// T toggles raw/driven at runtime for a direct comparison. The humanoid
    /// avatar can follow the same driven pose via HumanoidPoseDriver.poseSource.
    /// Runs in LateUpdate (after SkeletonPlayback applied the raw frame) and
    /// overrides the stick figure through SkeletonRenderer.ShowPoseWorld.
    /// </summary>
    [RequireComponent(typeof(SkeletonPlayback))]
    [DefaultExecutionOrder(-10)] // our LateUpdate must run before RacketVisual's
    public class TwinDriver : MonoBehaviour
    {
        [Header("Master")]
        public bool driveEnabled = true;
        [Tooltip("Runtime toggle between RAW (MediaPipe as-is) and DRIVEN.")]
        public KeyCode toggleKey = KeyCode.T;

        [Header("Lookahead")]
        [Tooltip("Peek this far ahead in the recording and steer toward it. " +
                 "0 = causal (what near-live Phase 5 would feel like).")]
        [Range(0f, 0.5f)] public float lookaheadSeconds = 0.2f;

        [Header("Spring stiffness (halflife seconds — lower = stiffer)")]
        [Range(0.02f, 0.5f)] public float rootHalflife = 0.12f;
        [Range(0.02f, 0.5f)] public float jointHalflife = 0.06f;

        [Header("Foot locking")]
        public bool footLock = true;
        [Tooltip("A foot moving slower than this (m/s) near the floor gets pinned.")]
        public float lockBelowSpeed = 0.35f;
        [Tooltip("Only feet below this height (m) can be pinned.")]
        public float lockBelowHeight = 0.18f;
        [Tooltip("Unpin when the captured foot has moved this far (m) from the pin.")]
        public float unlockDistance = 0.22f;

        [Header("Confidence")]
        [Range(0f, 1f)] public float confidenceCutoff = 0.3f;

        // MediaPipe landmark indices
        const int LSho = 11, RSho = 12, LElb = 13, RElb = 14, LWri = 15, RWri = 16,
                  LHip = 23, RHip = 24, LKne = 25, RKne = 26, LAnk = 27, RAnk = 28;
        static readonly int[] LHandExt = { 17, 19, 21 }, RHandExt = { 18, 20, 22 };
        static readonly int[] LFootExt = { 29, 31 }, RFootExt = { 30, 32 };

        SkeletonPlayback _playback;
        SkeletonRenderer _renderer;
        SkeletonDoc _builtFor;
        float _lift, _rootY;
        bool _ready;

        Vector3[] _pos, _vel;   // driven joint state, WORLD space
        Vector3[] _lastTarget;  // last good raw target per joint (world)
        bool[] _seen;           // joint had good confidence at least once
        Vector3 _rootPos, _rootVel;
        Vector2 _lastRootTarget;

        // limb segment reference lengths: L/R upper arm, forearm, thigh, shin
        float _luArm, _lfArm, _ruArm, _rfArm, _lThigh, _lShin, _rThigh, _rShin;

        struct FootPin { public bool locked; public Vector3 pos; public Vector3 prevTarget; public bool hasPrev; }
        FootPin _lFoot, _rFoot;

        public bool Active => driveEnabled && _ready;
        public Vector3 WorldJoint(int j) => _pos[j];
        public bool JointOk(int j) => _seen[j];
        /// <summary>Driven joint in twin-local space (what SkeletonDoc.JointPos + lift would be).</summary>
        public Vector3 JointLocal(int j) => transform.InverseTransformPoint(_pos[j]);
        public Vector2 DrivenRootXZ => new Vector2(_rootPos.x, _rootPos.z);

        void Awake()
        {
            _playback = GetComponent<SkeletonPlayback>();
            _renderer = GetComponent<SkeletonRenderer>();
        }

        void LateUpdate()
        {
            if (TogglePressed()) driveEnabled = !driveEnabled;

            var doc = _playback.Doc;
            if (doc == null || doc.FrameCount == 0) { _ready = false; return; }
            if (_builtFor != doc) InitForClip(doc);
            if (!driveEnabled) return; // playback's own ShowFrame keeps showing RAW

            float dt = Time.deltaTime;
            if (dt <= 0f) return;

            int fNow = _playback.CurrentFrame;
            int fLook = Mathf.Clamp(fNow + Mathf.RoundToInt(lookaheadSeconds * doc.Fps),
                                    0, doc.FrameCount - 1);

            DriveRoot(doc, fLook, dt);
            DriveJoints(doc, fNow, fLook, dt);
            ApplyFootLocks(doc, fNow, dt);
            SolveLimbs(doc, fNow);
            PlaceExtremities(doc, fNow);

            _renderer.ShowPoseWorld(_pos, _seen);
        }

        // ---------------- init ----------------

        void InitForClip(SkeletonDoc doc)
        {
            _builtFor = doc;
            _lift = -doc.MinY();
            _rootY = transform.position.y;
            int n = SkeletonDoc.NumJoints;
            _pos = new Vector3[n]; _vel = new Vector3[n];
            _lastTarget = new Vector3[n]; _seen = new bool[n];

            MeasureBoneLengths(doc);

            // snap to frame 0 so there's no fly-in
            _rootPos = transform.position; _rootVel = Vector3.zero;
            if (doc.HasRoot)
            {
                Vector2 xz = doc.RootXZ(0);
                _rootPos = new Vector3(xz.x, _rootY, xz.y);
                _lastRootTarget = xz;
            }
            transform.position = _rootPos;
            for (int j = 0; j < n; j++)
            {
                Vector3 w = RawWorld(doc, 0, j);
                _pos[j] = w; _lastTarget[j] = w; _vel[j] = Vector3.zero;
                _seen[j] = doc.JointConf(0, j) >= confidenceCutoff;
            }
            _lFoot = default; _rFoot = default;
            _ready = true;
        }

        // median limb lengths over the clip = the twin's fixed proportions
        void MeasureBoneLengths(SkeletonDoc doc)
        {
            _luArm = MedianLen(doc, LSho, LElb); _lfArm = MedianLen(doc, LElb, LWri);
            _ruArm = MedianLen(doc, RSho, RElb); _rfArm = MedianLen(doc, RElb, RWri);
            _lThigh = MedianLen(doc, LHip, LKne); _lShin = MedianLen(doc, LKne, LAnk);
            _rThigh = MedianLen(doc, RHip, RKne); _rShin = MedianLen(doc, RKne, RAnk);
        }

        float MedianLen(SkeletonDoc doc, int a, int b)
        {
            var lens = new System.Collections.Generic.List<float>(doc.FrameCount / 5 + 1);
            for (int f = 0; f < doc.FrameCount; f += 5)
            {
                if (doc.JointConf(f, a) < 0.5f || doc.JointConf(f, b) < 0.5f) continue;
                lens.Add((doc.JointPos(f, a) - doc.JointPos(f, b)).magnitude);
            }
            if (lens.Count == 0) return 0f;
            lens.Sort();
            return lens[lens.Count / 2];
        }

        // ---------------- drive ----------------

        void DriveRoot(SkeletonDoc doc, int fLook, float dt)
        {
            if (doc.HasRoot)
            {
                if (doc.RootConf(fLook) >= _playback.rootConfidenceCutoff)
                    _lastRootTarget = doc.RootXZ(fLook);
                Vector3 goal = new Vector3(_lastRootTarget.x, _rootY, _lastRootTarget.y);
                Spring(ref _rootPos, ref _rootVel, goal, rootHalflife, dt);
            }
            transform.position = _rootPos; // overrides SkeletonPlayback's Lerp
        }

        void DriveJoints(SkeletonDoc doc, int fNow, int fLook, float dt)
        {
            for (int j = 0; j < SkeletonDoc.NumJoints; j++)
            {
                // low-confidence frames don't move the target; the spring holds
                if (doc.JointConf(fLook, j) >= confidenceCutoff)
                {
                    _lastTarget[j] = RawWorld(doc, fLook, j);
                    _seen[j] = true;
                }
                else if (doc.JointConf(fNow, j) >= confidenceCutoff)
                {
                    _lastTarget[j] = RawWorld(doc, fNow, j);
                    _seen[j] = true;
                }
                if (!_seen[j]) continue;
                Spring(ref _pos[j], ref _vel[j], _lastTarget[j], jointHalflife, dt);
            }
        }

        void ApplyFootLocks(SkeletonDoc doc, int fNow, float dt)
        {
            if (!footLock) { _lFoot.locked = false; _rFoot.locked = false; return; }
            UpdateFootPin(ref _lFoot, doc, fNow, LAnk, dt);
            UpdateFootPin(ref _rFoot, doc, fNow, RAnk, dt);
            if (_lFoot.locked) { _pos[LAnk] = _lFoot.pos; _vel[LAnk] = Vector3.zero; }
            if (_rFoot.locked) { _pos[RAnk] = _rFoot.pos; _vel[RAnk] = Vector3.zero; }
        }

        void UpdateFootPin(ref FootPin pin, SkeletonDoc doc, int fNow, int ankle, float dt)
        {
            if (doc.JointConf(fNow, ankle) < confidenceCutoff) return; // keep current state
            Vector3 target = RawWorld(doc, fNow, ankle); // pin decisions use CAUSAL data
            if (!pin.hasPrev) { pin.prevTarget = target; pin.hasPrev = true; return; }
            float speed = (target - pin.prevTarget).magnitude / Mathf.Max(dt, 1e-4f);
            pin.prevTarget = target;

            if (pin.locked)
            {
                if ((target - pin.pos).magnitude > unlockDistance) pin.locked = false;
            }
            else if (speed < lockBelowSpeed && target.y < lockBelowHeight)
            {
                pin.locked = true;
                pin.pos = new Vector3(_pos[ankle].x, Mathf.Min(_pos[ankle].y, lockBelowHeight), _pos[ankle].z);
            }
        }

        void SolveLimbs(SkeletonDoc doc, int fNow)
        {
            SolveChain(LSho, LElb, LWri, _luArm, _lfArm);
            SolveChain(RSho, RElb, RWri, _ruArm, _rfArm);
            SolveChain(LHip, LKne, LAnk, _lThigh, _lShin);
            SolveChain(RHip, RKne, RAnk, _rThigh, _rShin);
        }

        // Enforce segment lengths: clamp the end effector into reach, then place
        // the middle joint by two-bone IK using the sprung middle as pole hint.
        void SolveChain(int a, int mid, int end, float l1, float l2)
        {
            if (l1 <= 0f || l2 <= 0f) return;
            if (!_seen[a] || !_seen[mid] || !_seen[end]) return;

            Vector3 A = _pos[a];
            Vector3 dir = _pos[end] - A;
            float d = dir.magnitude;
            if (d < 1e-5f) return;
            float dClamped = Mathf.Clamp(d, Mathf.Abs(l1 - l2) + 1e-3f, l1 + l2 - 1e-3f);
            Vector3 end2 = A + dir / d * dClamped;

            Vector3 n = (end2 - A).normalized;
            Vector3 p = _pos[mid] - A;
            Vector3 w = p - n * Vector3.Dot(p, n);
            if (w.sqrMagnitude < 1e-8f) w = Vector3.Cross(n, Vector3.up);
            if (w.sqrMagnitude < 1e-8f) w = Vector3.Cross(n, Vector3.right);
            w.Normalize();

            float cosA = Mathf.Clamp((l1 * l1 + dClamped * dClamped - l2 * l2)
                                     / (2f * l1 * dClamped), -1f, 1f);
            float sinA = Mathf.Sqrt(Mathf.Max(0f, 1f - cosA * cosA));

            _pos[mid] = A + n * (l1 * cosA) + w * (l1 * sinA);
            _pos[end] = end2;
        }

        // hands/feet tip joints ride rigidly on the solved wrist/ankle
        void PlaceExtremities(SkeletonDoc doc, int fNow)
        {
            RideOn(doc, fNow, LWri, LHandExt);
            RideOn(doc, fNow, RWri, RHandExt);
            RideOn(doc, fNow, LAnk, LFootExt);
            RideOn(doc, fNow, RAnk, RFootExt);
        }

        void RideOn(SkeletonDoc doc, int fNow, int anchor, int[] riders)
        {
            if (!_seen[anchor]) return;
            Vector3 rawAnchor = RawWorld(doc, fNow, anchor);
            foreach (int r in riders)
            {
                if (doc.JointConf(fNow, r) < confidenceCutoff) continue;
                _pos[r] = _pos[anchor] + (RawWorld(doc, fNow, r) - rawAnchor);
                _seen[r] = true;
            }
        }

        // ---------------- helpers ----------------

        Vector3 RawWorld(SkeletonDoc doc, int frame, int j)
            => transform.TransformPoint(doc.JointPos(frame, j) + new Vector3(0, _lift, 0));

        // critically-damped spring (halflife form)
        static void Spring(ref Vector3 x, ref Vector3 v, Vector3 goal, float halflife, float dt)
        {
            float y = (2f * 0.69314718f) / Mathf.Max(halflife, 1e-3f);
            Vector3 j0 = x - goal;
            Vector3 j1 = v + j0 * y;
            float e = Mathf.Exp(-y * dt);
            x = e * (j0 + j1 * dt) + goal;
            v = e * (v - j1 * (y * dt));
        }

        bool TogglePressed()
        {
#if ENABLE_INPUT_SYSTEM
            var kb = Keyboard.current;
            if (kb == null) return false;
            Key k = System.Enum.TryParse(toggleKey.ToString(), out Key parsed) ? parsed : Key.T;
            return kb[k].wasPressedThisFrame;
#else
            return Input.GetKeyDown(toggleKey);
#endif
        }
    }
}
