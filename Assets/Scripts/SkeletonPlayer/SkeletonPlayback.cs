using System.IO;
using UnityEngine;

namespace BadmintonVR.SkeletonPlayer
{
    /// <summary>
    /// Loads a skeleton.json and plays it back on a SkeletonRenderer with a
    /// clock (play/pause/scrub/speed). If the clip carries court positions
    /// (extracted with --court, Phase 2) and driveRootPosition is on, the whole
    /// stick figure walks to root_court_xz each frame; otherwise it plays in
    /// place at this object's position (Phase 1).
    /// </summary>
    [RequireComponent(typeof(SkeletonRenderer))]
    public class SkeletonPlayback : MonoBehaviour
    {
        [Tooltip("Path under StreamingAssets, e.g. skeleton/clip.json")]
        public string streamingAssetsPath = "skeleton/20260715_clears_sideview.json";
        public bool playOnStart = true;
        public bool loop = true;
        [Range(0.1f, 2f)] public float speed = 1f;

        [Header("Court position (Phase 2)")]
        [Tooltip("Walk the stick figure to root_court_xz when the clip has it " +
                 "(extracted with --court). Off = play in place at court center.")]
        public bool driveRootPosition = true;
        [Tooltip("Frames whose root confidence is below this hold the last position.")]
        [Range(0f, 1f)] public float rootConfidenceCutoff = 0.2f;
        [Tooltip("Smoothing for the root position: 0 = raw, 1 = very smooth (laggy).")]
        [Range(0f, 0.95f)] public float rootSmoothing = 0.2f;

        public SkeletonDoc Doc { get; private set; }
        public bool IsPlaying { get; private set; }
        public int CurrentFrame { get; private set; }
        public int FrameCount => Doc != null ? Doc.FrameCount : 0;

        SkeletonRenderer _renderer;
        float _clock; // seconds into the clip
        float _rootY;          // spawn height, preserved while moving on XZ
        Vector3 _rootCurrent;  // last applied root position (for smoothing)
        bool _rootActive;

        void Awake() => _renderer = GetComponent<SkeletonRenderer>();

        void Start()
        {
            if (!Load(streamingAssetsPath)) return;
            IsPlaying = playOnStart;
        }

        public bool Load(string path)
        {
            Doc = SkeletonDoc.Load(path);
            if (Doc == null) return false;
            _renderer.Build(Doc);
            _clock = 0f;
            CurrentFrame = 0;

            _rootActive = driveRootPosition && Doc.HasRoot;
            _rootY = transform.position.y;
            _rootCurrent = transform.position;
            if (_rootActive)
            {
                // jump straight to the clip's start position (no lerp-in from spawn)
                Vector2 xz = Doc.RootXZ(0);
                _rootCurrent = new Vector3(xz.x, _rootY, xz.y);
                transform.position = _rootCurrent;
            }

            _renderer.ShowFrame(Doc, 0);
            Debug.Log($"[SkeletonPlayer] loaded {Path.GetFileName(path)}: " +
                      $"{Doc.FrameCount} frames, {Doc.Duration:F1}s @ {Doc.Fps:F0}fps" +
                      (_rootActive ? " (walking on court)" : " (in place)"));
            return true;
        }

        // Move the whole stick figure to the player's court position for this frame.
        void ApplyRoot(int frame)
        {
            if (!_rootActive) return;
            if (Doc.RootConf(frame) < rootConfidenceCutoff) return;
            Vector2 xz = Doc.RootXZ(frame);
            Vector3 target = new Vector3(xz.x, _rootY, xz.y);
            _rootCurrent = rootSmoothing <= 0f
                ? target
                : Vector3.Lerp(target, _rootCurrent, rootSmoothing);
            transform.position = _rootCurrent;
        }

        void Update()
        {
            if (Doc == null || !IsPlaying || Doc.FrameCount == 0) return;
            _clock += Time.deltaTime * speed;
            float dur = Doc.Duration;
            if (dur <= 0f) return;

            if (_clock >= dur)
            {
                if (loop) _clock %= dur;
                else { _clock = dur; IsPlaying = false; }
            }
            SeekSeconds(_clock);
        }

        public void SeekSeconds(float t)
        {
            if (Doc == null) return;
            _clock = Mathf.Clamp(t, 0f, Doc.Duration);
            CurrentFrame = Mathf.Clamp(Mathf.RoundToInt(_clock * Doc.Fps), 0, Doc.FrameCount - 1);
            ApplyRoot(CurrentFrame);
            _renderer.ShowFrame(Doc, CurrentFrame);
        }

        public void SeekNormalized(float t01) => SeekSeconds(t01 * (Doc != null ? Doc.Duration : 0f));
        public float Normalized => (Doc != null && Doc.Duration > 0f) ? _clock / Doc.Duration : 0f;
        public void Play() => IsPlaying = true;
        public void Pause() => IsPlaying = false;
        public void TogglePlay() => IsPlaying = !IsPlaying;
    }
}
