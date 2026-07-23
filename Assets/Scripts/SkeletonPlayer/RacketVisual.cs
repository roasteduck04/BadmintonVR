using System.IO;
using UnityEngine;

namespace BadmintonVR.SkeletonPlayer
{
    /// <summary>
    /// Draws an ESTIMATED racket on the twin: anchored at the racket-hand wrist,
    /// oriented by the HAND landmarks (wrist -> knuckles) so wrist flexion and
    /// deviation articulate the racket instead of it being welded to the
    /// forearm. Falls back to the elbow -> wrist line when the hand landmarks
    /// are low-confidence. No detection yet — this is the visual baseline the
    /// future racket detector gets compared against
    /// (see docs/for-claude/ai-smoothing-plan.md and the roadmap).
    ///
    /// Distinct color (orange by default) so it can't be confused with the
    /// yellow joints / blue bones of the skeleton. Only shown for clips listed
    /// in <see cref="clipsWithRacket"/> (the player carried a racket in those).
    ///
    /// The racket geometry lives at the SCENE ROOT, not under the twin:
    /// SkeletonRenderer.Clear() destroys all twin children on clip load.
    /// </summary>
    [RequireComponent(typeof(SkeletonPlayback))]
    public class RacketVisual : MonoBehaviour
    {
        public enum Hand { Right, Left }

        [Tooltip("Clip stems (file name without .json) where the player holds a racket.")]
        public string[] clipsWithRacket = { "test_3", "test_4", "test_5" };

        public Hand hand = Hand.Right;
        public Color color = new Color(1f, 0.45f, 0.05f); // orange — nothing else uses it

        [Header("Dimensions (m, ~real racket = 0.68 total)")]
        [Range(0.2f, 0.6f)] public float shaftLength = 0.40f;
        [Range(0.15f, 0.4f)] public float headLength = 0.28f;
        [Range(0.1f, 0.35f)] public float headWidth = 0.22f;

        [Tooltip("Hide the racket when wrist/elbow confidence drops below this.")]
        [Range(0f, 1f)] public float confidenceCutoff = 0.3f;

        [Tooltip("0 = racket welded to the forearm line, 1 = fully follows the hand " +
                 "(wrist->knuckle) direction. Hand landmarks jitter more than the wrist, " +
                 "so a bit below 1 keeps it stable.")]
        [Range(0f, 1f)] public float handInfluence = 0.85f;

        // MediaPipe pose landmark indices
        const int RElbow = 14, RWrist = 16, LElbow = 13, LWrist = 15;
        const int RPinky = 18, RIndex = 20, LPinky = 17, LIndex = 19;

        SkeletonPlayback _playback;
        TwinDriver _driver; // optional Track B driver — racket follows the DRIVEN wrist
        Transform _root, _shaft, _head;
        SkeletonDoc _builtFor;
        float _lift; // same ground offset SkeletonRenderer applies (-doc.MinY())

        void Awake()
        {
            _playback = GetComponent<SkeletonPlayback>();
            _driver = GetComponent<TwinDriver>();
        }

        void OnDestroy() { if (_root != null) Destroy(_root.gameObject); }

        void BuildGeometry()
        {
            _root = new GameObject("RacketVisual").transform;

            var mat = MakeMat(color);

            var shaftGo = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            shaftGo.name = "shaft";
            shaftGo.transform.SetParent(_root, false);
            shaftGo.GetComponent<Renderer>().sharedMaterial = mat;
            Destroy(shaftGo.GetComponent<Collider>());
            // default cylinder is 2 units tall along Y; scale to shaftLength
            shaftGo.transform.localScale = new Vector3(0.024f, shaftLength * 0.5f, 0.024f);
            shaftGo.transform.localPosition = new Vector3(0, shaftLength * 0.5f, 0);
            _shaft = shaftGo.transform;

            var headGo = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            headGo.name = "head";
            headGo.transform.SetParent(_root, false);
            headGo.GetComponent<Renderer>().sharedMaterial = mat;
            Destroy(headGo.GetComponent<Collider>());
            // flattened ellipsoid = string bed
            headGo.transform.localScale = new Vector3(headWidth, headLength, 0.025f);
            headGo.transform.localPosition = new Vector3(0, shaftLength + headLength * 0.5f, 0);
            _head = headGo.transform;
        }

        static Material MakeMat(Color col)
        {
            var shader = Shader.Find("Universal Render Pipeline/Lit");
            if (shader == null) shader = Shader.Find("Standard");
            var m = new Material(shader);
            if (m.HasProperty("_BaseColor")) m.SetColor("_BaseColor", col);
            else m.color = col;
            return m;
        }

        bool ClipHasRacket()
        {
            string stem = Path.GetFileNameWithoutExtension(_playback.streamingAssetsPath);
            foreach (var c in clipsWithRacket)
                if (string.Equals(c, stem, System.StringComparison.OrdinalIgnoreCase)) return true;
            return false;
        }

        // After SkeletonPlayback.Update has positioned the twin for this frame.
        void LateUpdate()
        {
            var doc = _playback.Doc;
            if (doc == null || doc.FrameCount == 0) { Hide(); return; }
            if (!ClipHasRacket()) { Hide(); return; }

            if (_root == null) BuildGeometry();
            if (_builtFor != doc) { _lift = -doc.MinY(); _builtFor = doc; }

            int f = _playback.CurrentFrame;
            bool right = hand == Hand.Right;
            int wrist = right ? RWrist : LWrist;
            int elbow = right ? RElbow : LElbow;
            int pinky = right ? RPinky : LPinky;
            int index = right ? RIndex : LIndex;

            if (doc.JointConf(f, wrist) < confidenceCutoff ||
                doc.JointConf(f, elbow) < confidenceCutoff) { Hide(); return; }

            bool handOk = handInfluence > 0f &&
                          doc.JointConf(f, pinky) >= confidenceCutoff &&
                          doc.JointConf(f, index) >= confidenceCutoff;

            Vector3 w, e, pk = default, ix = default;
            if (_driver != null && _driver.Active && _driver.JointOk(wrist) && _driver.JointOk(elbow))
            {
                // TwinDriver ran first (execution order) — follow the driven arm
                w = _driver.WorldJoint(wrist);
                e = _driver.WorldJoint(elbow);
                handOk = handOk && _driver.JointOk(pinky) && _driver.JointOk(index);
                if (handOk) { pk = _driver.WorldJoint(pinky); ix = _driver.WorldJoint(index); }
            }
            else
            {
                Vector3 liftV = new Vector3(0, _lift, 0);
                // same local->world mapping SkeletonRenderer uses for the joints
                w = transform.TransformPoint(doc.JointPos(f, wrist) + liftV);
                e = transform.TransformPoint(doc.JointPos(f, elbow) + liftV);
                if (handOk)
                {
                    pk = transform.TransformPoint(doc.JointPos(f, pinky) + liftV);
                    ix = transform.TransformPoint(doc.JointPos(f, index) + liftV);
                }
            }

            Vector3 forearm = w - e;
            if (forearm.sqrMagnitude < 1e-6f) { Hide(); return; }
            forearm.Normalize();

            // Shaft direction: blend forearm line toward wrist->knuckle-midpoint,
            // so wrist flexion/deviation actually swings the racket.
            Vector3 dir = forearm;
            Vector3 palmNormal = Vector3.zero;
            if (handOk)
            {
                Vector3 handDir = (pk + ix) * 0.5f - w;
                if (handDir.sqrMagnitude > 1e-6f)
                    dir = Vector3.Slerp(forearm, handDir.normalized, handInfluence);
                // two knuckle rays span the palm plane; its normal rolls the string bed
                palmNormal = Vector3.Cross(ix - w, pk - w);
            }

            _root.gameObject.SetActive(true);
            _root.position = w; // grip at the wrist

            Vector3 bedNormal = Vector3.ProjectOnPlane(palmNormal, dir);
            _root.rotation = bedNormal.sqrMagnitude > 1e-8f
                ? Quaternion.LookRotation(bedNormal, dir) // Y = shaft, Z = string bed facing
                : Quaternion.FromToRotation(Vector3.up, dir);
        }

        void Hide() { if (_root != null) _root.gameObject.SetActive(false); }
    }
}
