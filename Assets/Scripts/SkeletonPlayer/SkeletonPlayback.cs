using System.IO;
using UnityEngine;

namespace BadmintonVR.SkeletonPlayer
{
    /// <summary>
    /// Loads a skeleton.json and plays it back on a SkeletonRenderer with a
    /// clock (play/pause/scrub/speed). Twin plays in place at this object's
    /// position (Phase 1: no court root translation).
    /// </summary>
    [RequireComponent(typeof(SkeletonRenderer))]
    public class SkeletonPlayback : MonoBehaviour
    {
        [Tooltip("Path under StreamingAssets, e.g. skeleton/clip.json")]
        public string streamingAssetsPath = "skeleton/20260715_clears_sideview.json";
        public bool playOnStart = true;
        public bool loop = true;
        [Range(0.1f, 2f)] public float speed = 1f;

        public SkeletonDoc Doc { get; private set; }
        public bool IsPlaying { get; private set; }
        public int CurrentFrame { get; private set; }
        public int FrameCount => Doc != null ? Doc.FrameCount : 0;

        SkeletonRenderer _renderer;
        float _clock; // seconds into the clip

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
            _renderer.ShowFrame(Doc, 0);
            Debug.Log($"[SkeletonPlayer] loaded {Path.GetFileName(path)}: " +
                      $"{Doc.FrameCount} frames, {Doc.Duration:F1}s @ {Doc.Fps:F0}fps");
            return true;
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
            _renderer.ShowFrame(Doc, CurrentFrame);
        }

        public void SeekNormalized(float t01) => SeekSeconds(t01 * (Doc != null ? Doc.Duration : 0f));
        public float Normalized => (Doc != null && Doc.Duration > 0f) ? _clock / Doc.Duration : 0f;
        public void Play() => IsPlaying = true;
        public void Pause() => IsPlaying = false;
        public void TogglePlay() => IsPlaying = !IsPlaying;
    }
}
