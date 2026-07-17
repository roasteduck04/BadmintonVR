using UnityEngine;
#if ENABLE_INPUT_SYSTEM
using UnityEngine.InputSystem;
#endif

namespace BadmintonVR.SkeletonPlayer
{
    /// <summary>
    /// Subtitle track for the twin: shows the current move label (from the
    /// clip's `moves` block, schema 1.1) as a banner, plus a colored segment
    /// timeline with a playhead. Zero inference — labels come from
    /// tools/label_moves.py. M toggles. No child objects are added anywhere
    /// (OnGUI only), so the SkeletonRenderer.Clear() rule is not a concern.
    /// </summary>
    [RequireComponent(typeof(SkeletonPlayback))]
    public class MoveLabelHUD : MonoBehaviour
    {
        public KeyCode toggleKey = KeyCode.M;
        [Tooltip("Timeline bar height in pixels.")]
        public float barHeight = 14f;

        SkeletonPlayback _playback;
        bool _visible = true;
        Texture2D _white;

        void Awake()
        {
            _playback = GetComponent<SkeletonPlayback>();
            _white = Texture2D.whiteTexture;
        }

        void Update()
        {
            if (TogglePressed()) _visible = !_visible;
        }

        static Color LabelColor(string label)
        {
            switch (label)
            {
                case "overhead_smash": return new Color(0.95f, 0.25f, 0.2f);
                case "overhead_clear": return new Color(0.25f, 0.6f, 0.95f);
                case "drop":           return new Color(0.95f, 0.75f, 0.2f);
                case "underarm_lift":  return new Color(0.5f, 0.85f, 0.4f);
                case "net_shot":       return new Color(0.85f, 0.45f, 0.9f);
                case "drive":          return new Color(0.35f, 0.9f, 0.85f);
                case "moving":         return new Color(0.55f, 0.55f, 0.55f);
                case "idle":           return new Color(0.35f, 0.35f, 0.35f);
                default:               return Color.white;   // unknown label: still shown
            }
        }

        void OnGUI()
        {
            if (!_visible) return;
            var doc = _playback.Doc;
            if (doc == null || !doc.HasMoves) return;

            int f = _playback.CurrentFrame;
            var cur = doc.MoveAt(f);

            // banner, top-center
            string text = cur == null ? "-" :
                cur.confidence > 0f ? $"{cur.label}  ({cur.confidence:F2})" : cur.label;
            var style = new GUIStyle(GUI.skin.box)
            {
                fontSize = 28, alignment = TextAnchor.MiddleCenter,
                normal = { textColor = cur == null ? Color.white : LabelColor(cur.label) }
            };
            GUI.Box(new Rect(Screen.width / 2f - 180, 8, 360, 46), text, style);

            // timeline bar, bottom
            float y = Screen.height - barHeight - 8, w = Screen.width - 16f;
            int n = doc.FrameCount;
            for (int i = 0; i < doc.moves.Length; i++)
            {
                var m = doc.moves[i];
                float x0 = 8 + w * m.start / n, x1 = 8 + w * (m.end + 1) / n;
                GUI.color = LabelColor(m.label);
                GUI.DrawTexture(new Rect(x0, y, x1 - x0, barHeight), _white);
            }
            GUI.color = Color.white;   // playhead
            GUI.DrawTexture(new Rect(8 + w * f / n - 1, y - 3, 2, barHeight + 6), _white);
        }

        bool TogglePressed()
        {
#if ENABLE_INPUT_SYSTEM
            var kb = Keyboard.current;
            if (kb == null) return false;
            Key k = System.Enum.TryParse(toggleKey.ToString(), out Key parsed) ? parsed : Key.M;
            return kb[k].wasPressedThisFrame;
#else
            return Input.GetKeyDown(toggleKey);
#endif
        }
    }
}
