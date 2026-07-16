using System.IO;
using UnityEngine;
using UnityEngine.UI;
using UnityEngine.Video;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
#endif

namespace BadmintonVR.SkeletonPlayer
{
    /// <summary>
    /// Shows the SOURCE phone video alongside the game view, time-synced to the
    /// twin, so you can compare the real footage with the twin walking the court.
    ///
    /// Default layout is SPLIT SCREEN: the video fills one half of the screen
    /// (letterboxed) and the game camera is shrunk to the other half, so the two
    /// sit side by side instead of overlapping. CornerPiP is also available.
    ///
    /// Add it to the same object as a <see cref="SkeletonPlayback"/> (Tools >
    /// Badminton > Video Compare > Add Overlay To Scene). It follows the Clip
    /// Switcher: whichever clip the twin plays, it loads data/raw/&lt;stem&gt;.mp4.
    /// Runs in Play mode; the UI is built at runtime and not saved into the scene.
    /// </summary>
    [RequireComponent(typeof(SkeletonPlayback))]
    public class VideoCompareOverlay : MonoBehaviour
    {
        public enum Layout { SplitScreen, CornerPiP }
        public enum Side { Right, Left }
        public enum PiPCorner { TopRight, TopLeft, BottomRight, BottomLeft }

        [Tooltip("Folder with the source clips, relative to the project root " +
                 "(the folder that contains Assets/).")]
        public string rawVideoDir = "data/raw";

        [Header("Layout")]
        public Layout layout = Layout.SplitScreen;

        [Tooltip("Split screen: which half shows the VIDEO (the game view takes the other half).")]
        public Side videoSide = Side.Right;

        [Tooltip("Camera to shrink for split screen. Empty = Camera.main.")]
        public Camera gameCamera;

        [Header("Corner PiP (when layout = CornerPiP)")]
        [Range(0.15f, 1f)] public float sizeFraction = 0.35f;
        public PiPCorner corner = PiPCorner.TopRight;

        [Header("Sync")]
        [Tooltip("Keep the video time locked to the twin's clock.")]
        public bool syncToPlayback = true;
        [Tooltip("Re-seek the video only when it drifts more than this many seconds.")]
        [Range(0.05f, 1f)] public float resyncThreshold = 0.15f;

        [Tooltip("Toggle the whole compare view on/off at runtime with this key.")]
        public KeyCode toggleKey = KeyCode.V;

        SkeletonPlayback _playback;
        GameObject _canvasGo;
        VideoPlayer _vp;
        RenderTexture _rt;
        Image _bg;          // black letterbox backing for split screen
        RawImage _img;      // the video
        Text _label;
        Camera _cam;
        Rect _origCamRect = new Rect(0, 0, 1, 1);
        bool _camRectSaved;
        bool _warnedNoCam;
        string _loadedClip;
        bool _visible = true;

        void Awake()
        {
            _playback = GetComponent<SkeletonPlayback>();
            BuildUI();
            BuildVideoPlayer();
        }

        void BuildUI()
        {
            // IMPORTANT: the canvas lives at the SCENE ROOT, not under the twin —
            // SkeletonRenderer.Clear() destroys every child of the twin when a
            // clip (re)loads, which used to wipe this UI (invisible video +
            // MissingReferenceException on the RawImage).
            var canvasGo = new GameObject("VideoCompareCanvas");
            _canvasGo = canvasGo;
            var canvas = canvasGo.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
            canvas.sortingOrder = 500;
            canvasGo.AddComponent<CanvasScaler>();       // ConstantPixelSize: 1 unit = 1 px
            canvasGo.AddComponent<GraphicRaycaster>();

            var bgGo = new GameObject("Letterbox");
            bgGo.transform.SetParent(canvasGo.transform, false);
            _bg = bgGo.AddComponent<Image>();
            _bg.color = Color.black;
            _bg.raycastTarget = false;

            var imgGo = new GameObject("VideoImage");
            imgGo.transform.SetParent(canvasGo.transform, false);
            _img = imgGo.AddComponent<RawImage>();
            _img.raycastTarget = false;

            var labelGo = new GameObject("ClipLabel");
            labelGo.transform.SetParent(imgGo.transform, false);
            _label = labelGo.AddComponent<Text>();
            _label.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            if (_label.font == null) _label.font = Resources.GetBuiltinResource<Font>("Arial.ttf");
            _label.fontSize = 16;
            _label.color = Color.white;
            _label.alignment = TextAnchor.UpperLeft;
            _label.raycastTarget = false;
            var lrt = _label.rectTransform;
            lrt.anchorMin = new Vector2(0, 1);
            lrt.anchorMax = new Vector2(1, 1);
            lrt.pivot = new Vector2(0, 1);
            lrt.anchoredPosition = new Vector2(6, -4);
            lrt.sizeDelta = new Vector2(0, 22);
        }

        void BuildVideoPlayer()
        {
            _vp = gameObject.AddComponent<VideoPlayer>();
            _vp.playOnAwake = false;
            _vp.source = VideoSource.Url;
            _vp.renderMode = VideoRenderMode.RenderTexture;
            _vp.audioOutputMode = VideoAudioOutputMode.None;
            _vp.isLooping = true;
            _vp.skipOnDrop = true;
            _vp.prepareCompleted += OnPrepared;
        }

        void OnDisable() => RestoreCamera();

        void OnDestroy()
        {
            RestoreCamera();
            if (_vp != null) _vp.prepareCompleted -= OnPrepared;
            if (_rt != null) _rt.Release();
            if (_canvasGo != null) Destroy(_canvasGo); // root-level UI is ours to clean up
        }

        Camera GameCam()
        {
            if (gameCamera != null) return gameCamera;
            if (_cam == null) _cam = Camera.main;
            return _cam;
        }

        void RestoreCamera()
        {
            if (_camRectSaved)
            {
                var cam = GameCam();
                if (cam != null) cam.rect = _origCamRect;
                _camRectSaved = false;
            }
        }

        string VideoPathFor(string clipPath)
        {
            string stem = Path.GetFileNameWithoutExtension(clipPath); // skeleton/x.json -> x
            return Path.GetFullPath(Path.Combine(
                Application.dataPath, "..", rawVideoDir, stem + ".mp4"));
        }

        void LoadVideoFor(string clipPath)
        {
            _loadedClip = clipPath;
            string path = VideoPathFor(clipPath);
            if (!File.Exists(path))
            {
                _img.enabled = false; _bg.enabled = false;
                Debug.LogWarning($"[VideoCompare] no source video for '{clipPath}' at {path}");
                return;
            }
            if (_label != null) _label.text = Path.GetFileName(path);
            _vp.Stop();
            _vp.url = new System.Uri(path).AbsoluteUri;
            _vp.Prepare();
        }

        void OnPrepared(VideoPlayer vp)
        {
            if (_img == null) return; // UI was destroyed (scene teardown)
            int w = (int)vp.width, h = (int)vp.height;
            if (w <= 0 || h <= 0) return;
            if (_rt == null || _rt.width != w || _rt.height != h)
            {
                if (_rt != null) _rt.Release();
                _rt = new RenderTexture(w, h, 0);
            }
            vp.targetTexture = _rt;
            _img.texture = _rt;
            if (_vp.length > 0)
                _vp.time = Mathf.Clamp01(_playback.Normalized) * _vp.length;
            if (_playback.IsPlaying) vp.Play();
        }

        void Update()
        {
            if (_img == null) return; // UI destroyed — nothing to drive
            if (TogglePressed()) _visible = !_visible;

            // follow the Clip Switcher: reload when the twin's clip changes
            if (_playback.streamingAssetsPath != _loadedClip)
                LoadVideoFor(_playback.streamingAssetsPath);

            bool ready = _vp != null && _vp.isPrepared && _img.texture != null;
            bool show = _visible && ready;

            _img.enabled = show;
            _bg.enabled = show && layout == Layout.SplitScreen;
            if (_label != null) _label.enabled = show;

            if (!ready) { if (!show) RestoreCamera(); return; }

            _vp.playbackSpeed = Mathf.Max(0.01f, _playback.speed);
            if (_playback.IsPlaying && !_vp.isPlaying) _vp.Play();
            else if (!_playback.IsPlaying && _vp.isPlaying) _vp.Pause();

            if (syncToPlayback && _vp.length > 0)
            {
                double target = Mathf.Clamp01(_playback.Normalized) * _vp.length;
                if (System.Math.Abs(_vp.time - target) > resyncThreshold)
                    _vp.time = target;
            }

            if (show && layout == Layout.SplitScreen) ApplySplit();
            else { RestoreCamera(); if (show) ApplyPiP(); }
        }

        void ApplySplit()
        {
            var cam = GameCam();
            if (cam != null)
            {
                if (!_camRectSaved) { _origCamRect = cam.rect; _camRectSaved = true; }
                // game view takes the half OPPOSITE the video
                cam.rect = videoSide == Side.Right
                    ? new Rect(0f, 0f, 0.5f, 1f)
                    : new Rect(0.5f, 0f, 0.5f, 1f);
            }
            else if (!_warnedNoCam)
            {
                _warnedNoCam = true;
                Debug.LogWarning("[VideoCompare] no game camera found (tag one 'MainCamera' " +
                                 "or assign 'gameCamera') — the video half will overlap the view.");
            }

            float halfX = videoSide == Side.Right ? 0.5f : 0f;
            // black letterbox fills the whole video half
            SetAnchors(_bg.rectTransform, new Vector2(halfX, 0f), new Vector2(halfX + 0.5f, 1f));

            // video centered in that half, preserving aspect
            float halfW = Screen.width * 0.5f;
            float aspect = (_vp.height > 0) ? (float)_vp.width / _vp.height : 16f / 9f;
            float w = halfW, h = w / aspect;
            if (h > Screen.height) { h = Screen.height; w = h * aspect; }
            var rt = _img.rectTransform;
            rt.anchorMin = rt.anchorMax = new Vector2(0, 0);
            rt.pivot = new Vector2(0.5f, 0.5f);
            rt.sizeDelta = new Vector2(w, h);
            float cx = (videoSide == Side.Right ? Screen.width * 0.75f : Screen.width * 0.25f);
            rt.anchoredPosition = new Vector2(cx, Screen.height * 0.5f);
        }

        void ApplyPiP()
        {
            _bg.enabled = false;
            float aspect = (_vp.height > 0) ? (float)_vp.width / _vp.height : 16f / 9f;
            float w = Screen.width * sizeFraction;
            float h = w / aspect;
            var rt = _img.rectTransform;
            rt.sizeDelta = new Vector2(w, h);
            const float pad = 12f;
            switch (corner)
            {
                case PiPCorner.TopRight:
                    rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(1, 1);
                    rt.anchoredPosition = new Vector2(-pad, -pad); break;
                case PiPCorner.TopLeft:
                    rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(0, 1);
                    rt.anchoredPosition = new Vector2(pad, -pad); break;
                case PiPCorner.BottomRight:
                    rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(1, 0);
                    rt.anchoredPosition = new Vector2(-pad, pad); break;
                case PiPCorner.BottomLeft:
                    rt.anchorMin = rt.anchorMax = rt.pivot = new Vector2(0, 0);
                    rt.anchoredPosition = new Vector2(pad, pad); break;
            }
        }

        // Read the toggle key under whichever input backend the project uses.
        bool TogglePressed()
        {
#if ENABLE_INPUT_SYSTEM
            var kb = Keyboard.current;
            if (kb == null) return false;
            Key k = System.Enum.TryParse(toggleKey.ToString(), out Key parsed) ? parsed : Key.V;
            return kb[k].wasPressedThisFrame;
#else
            return Input.GetKeyDown(toggleKey);
#endif
        }

        static void SetAnchors(RectTransform rt, Vector2 min, Vector2 max)
        {
            rt.anchorMin = min;
            rt.anchorMax = max;
            rt.offsetMin = Vector2.zero;
            rt.offsetMax = Vector2.zero;
        }
    }
}
