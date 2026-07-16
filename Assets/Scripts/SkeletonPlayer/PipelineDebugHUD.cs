using System.IO;
using UnityEngine;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
#endif

namespace BadmintonVR.SkeletonPlayer
{
    /// <summary>
    /// "See what the pipeline sees" — runtime debug view for a SkeletonPlayback:
    ///
    /// 1. CONFIDENCE COLORING — every joint sphere is tinted by its MediaPipe
    ///    confidence (green = trusted, red = guessing). Where the twin looks
    ///    wrong AND is red, the POSE data is bad; where it looks wrong but is
    ///    green, the problem is downstream (calibration / smoothing).
    /// 2. COURT TRAIL — the clip's whole extracted path drawn on the floor,
    ///    with RED markers on frames that hit the extraction clamps
    ///    (|X| ≥ 4.55 or |Z| ≥ 8.20 — where Python cut off an overshoot),
    ///    and a magenta puck at the current frame's position.
    /// 3. HUD — live numbers: frame, time, root XZ (m), root confidence, mean
    ///    joint confidence, and whole-clip stats (% in court box, clamp hits).
    ///
    /// Toggle everything with H at runtime. Trail/markers live at the scene
    /// root (twin children are cleared on clip load).
    /// </summary>
    [RequireComponent(typeof(SkeletonPlayback))]
    public class PipelineDebugHUD : MonoBehaviour
    {
        [Header("Features")]
        public bool colorByConfidence = true;
        public bool showTrail = true;
        public bool showHud = true;
        public KeyCode toggleKey = KeyCode.H;

        [Header("Court thresholds (must match extract_skeleton.py)")]
        public float clampX = 4.55f;   // extraction clamp walls
        public float clampZ = 8.20f;
        public float courtHalfWidth = 3.05f; // doubles sideline
        public float courtLength = 6.70f;    // net (0) -> baseline

        SkeletonPlayback _playback;
        SkeletonDoc _builtFor;
        bool _visible = true;

        // confidence coloring
        Transform[] _joints;
        MaterialPropertyBlock _mpb;
        static readonly int BaseColorId = Shader.PropertyToID("_BaseColor");
        static readonly int ColorId = Shader.PropertyToID("_Color");

        // trail
        Transform _trailRoot;
        LineRenderer _line;

        // whole-clip stats (computed once per clip)
        int _clampHits, _framesWithRoot;
        float _inBoxPct;

        void Awake()
        {
            _playback = GetComponent<SkeletonPlayback>();
            _mpb = new MaterialPropertyBlock();
        }

        void OnDestroy() { if (_trailRoot != null) Destroy(_trailRoot.gameObject); }

        void Update()
        {
            if (TogglePressed()) _visible = !_visible;

            var doc = _playback.Doc;
            if (doc == null || doc.FrameCount == 0) return;

            if (_builtFor != doc) RebuildForClip(doc);

            if (_trailRoot != null)
                _trailRoot.gameObject.SetActive(_visible && showTrail && doc.HasRoot);

            if (_visible && colorByConfidence) TintJoints(doc, _playback.CurrentFrame);
        }

        // ---------- per-clip setup ----------

        void RebuildForClip(SkeletonDoc doc)
        {
            _builtFor = doc;
            CacheJoints();
            ComputeClipStats(doc);
            BuildTrail(doc);
        }

        void CacheJoints()
        {
            _joints = new Transform[SkeletonDoc.NumJoints];
            for (int j = 0; j < SkeletonDoc.NumJoints; j++)
                _joints[j] = transform.Find($"joint_{j}"); // SkeletonRenderer naming
        }

        void ComputeClipStats(SkeletonDoc doc)
        {
            _clampHits = 0; _framesWithRoot = 0;
            int inBox = 0;
            if (!doc.HasRoot) { _inBoxPct = 0f; return; }
            for (int f = 0; f < doc.FrameCount; f++)
            {
                Vector2 xz = doc.RootXZ(f);
                _framesWithRoot++;
                if (Mathf.Abs(xz.x) >= clampX - 0.01f || Mathf.Abs(xz.y) >= clampZ - 0.01f)
                    _clampHits++;
                if (Mathf.Abs(xz.x) <= courtHalfWidth && xz.y >= 0f && xz.y <= courtLength)
                    inBox++;
            }
            _inBoxPct = _framesWithRoot > 0 ? 100f * inBox / _framesWithRoot : 0f;
        }

        void BuildTrail(SkeletonDoc doc)
        {
            if (_trailRoot != null) Destroy(_trailRoot.gameObject);
            if (!doc.HasRoot) return;

            _trailRoot = new GameObject("PipelineDebugTrail").transform;

            var lineGo = new GameObject("path");
            lineGo.transform.SetParent(_trailRoot, false);
            _line = lineGo.AddComponent<LineRenderer>();
            _line.useWorldSpace = true;
            _line.widthMultiplier = 0.03f;
            _line.material = MakeMat(new Color(0.1f, 0.9f, 0.9f)); // cyan path
            _line.positionCount = doc.FrameCount;
            for (int f = 0; f < doc.FrameCount; f++)
            {
                Vector2 xz = doc.RootXZ(f);
                _line.SetPosition(f, new Vector3(xz.x, 0.02f, xz.y));
            }

            // red markers where extraction hit the clamp walls (entry frames only)
            var redMat = MakeMat(Color.red);
            bool wasClamped = false;
            int markers = 0;
            for (int f = 0; f < doc.FrameCount && markers < 200; f++)
            {
                Vector2 xz = doc.RootXZ(f);
                bool clamped = Mathf.Abs(xz.x) >= clampX - 0.01f || Mathf.Abs(xz.y) >= clampZ - 0.01f;
                if (clamped && !wasClamped)
                {
                    var m = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                    m.name = $"clamp_f{f}";
                    m.transform.SetParent(_trailRoot, false);
                    m.transform.position = new Vector3(xz.x, 0.05f, xz.y);
                    m.transform.localScale = Vector3.one * 0.12f;
                    m.GetComponent<Renderer>().sharedMaterial = redMat;
                    Destroy(m.GetComponent<Collider>());
                    markers++;
                }
                wasClamped = clamped;
            }

            // magenta puck follows the current frame
            var puck = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
            puck.name = "current";
            puck.transform.SetParent(_trailRoot, false);
            puck.transform.localScale = new Vector3(0.25f, 0.01f, 0.25f);
            puck.GetComponent<Renderer>().sharedMaterial = MakeMat(Color.magenta);
            Destroy(puck.GetComponent<Collider>());
            _puck = puck.transform;
        }

        Transform _puck;

        void LateUpdate()
        {
            var doc = _playback.Doc;
            if (_puck != null && doc != null && doc.HasRoot)
            {
                Vector2 xz = doc.RootXZ(_playback.CurrentFrame);
                _puck.position = new Vector3(xz.x, 0.02f, xz.y);
            }
        }

        // ---------- confidence coloring ----------

        void TintJoints(SkeletonDoc doc, int frame)
        {
            if (_joints == null) return;
            for (int j = 0; j < SkeletonDoc.NumJoints; j++)
            {
                var t = _joints[j];
                if (t == null) { CacheJoints(); return; } // renderer rebuilt — re-find next frame
                if (!t.gameObject.activeSelf) continue;   // hidden by confidence cutoff
                var r = t.GetComponent<Renderer>();
                if (r == null) continue;
                float c = doc.JointConf(frame, j);
                Color col = Color.Lerp(Color.red, Color.green, Mathf.Clamp01(c));
                _mpb.Clear();
                _mpb.SetColor(BaseColorId, col);
                _mpb.SetColor(ColorId, col);
                r.SetPropertyBlock(_mpb);
            }
        }

        // ---------- HUD ----------

        void OnGUI()
        {
            if (!_visible || !showHud) return;
            var doc = _playback.Doc;
            if (doc == null || doc.FrameCount == 0) return;

            int f = _playback.CurrentFrame;
            float meanConf = 0f;
            for (int j = 0; j < SkeletonDoc.NumJoints; j++) meanConf += doc.JointConf(f, j);
            meanConf /= SkeletonDoc.NumJoints;

            string stem = Path.GetFileNameWithoutExtension(_playback.streamingAssetsPath);
            string root = doc.HasRoot
                ? $"root XZ  ({doc.RootXZ(f).x,6:F2}, {doc.RootXZ(f).y,6:F2}) m   conf {doc.RootConf(f):F2}"
                : "root      (no court data — Phase 1 clip)";

            string text =
                $"clip      {stem}\n" +
                $"frame     {f + 1}/{doc.FrameCount}   t={f / doc.Fps,6:F2}s\n" +
                $"{root}\n" +
                $"pose conf {meanConf:F2} (mean of 33 joints, green=1 red=0)\n" +
                $"clip      {_inBoxPct:F1}% in court box, {_clampHits} clamp frames\n" +
                $"[H] hide debug   [V] video compare";

            var style = new GUIStyle(GUI.skin.box)
            {
                alignment = TextAnchor.UpperLeft,
                fontSize = 13,
                richText = false
            };
            style.normal.textColor = Color.white;
            GUI.Box(new Rect(8, 8, 360, 118), text, style);
        }

        // ---------- helpers ----------

        static Material MakeMat(Color col)
        {
            var shader = Shader.Find("Universal Render Pipeline/Unlit");
            if (shader == null) shader = Shader.Find("Unlit/Color");
            var m = new Material(shader);
            if (m.HasProperty("_BaseColor")) m.SetColor("_BaseColor", col);
            else m.color = col;
            return m;
        }

        bool TogglePressed()
        {
#if ENABLE_INPUT_SYSTEM
            var kb = Keyboard.current;
            if (kb == null) return false;
            Key k = System.Enum.TryParse(toggleKey.ToString(), out Key parsed) ? parsed : Key.H;
            return kb[k].wasPressedThisFrame;
#else
            return Input.GetKeyDown(toggleKey);
#endif
        }
    }
}
