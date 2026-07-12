using UnityEngine;

namespace BadmintonVR.SkeletonPlayer
{
    /// <summary>
    /// Minimal on-screen controls (IMGUI, zero setup): play/pause, scrub bar,
    /// speed, frame counter. Good enough to inspect the twin in Play mode.
    /// </summary>
    public class PlaybackUI : MonoBehaviour
    {
        public SkeletonPlayback player;

        void Reset() => player = GetComponent<SkeletonPlayback>();

        void OnGUI()
        {
            if (player == null || player.Doc == null) return;

            const float pad = 12f;
            float w = Screen.width - pad * 2f;
            var box = new Rect(pad, Screen.height - 96f, w, 84f);
            GUI.Box(box, GUIContent.none);

            GUILayout.BeginArea(new Rect(box.x + 10, box.y + 8, box.width - 20, box.height - 16));

            GUILayout.BeginHorizontal();
            if (GUILayout.Button(player.IsPlaying ? "|| Pause" : ">  Play", GUILayout.Width(90), GUILayout.Height(28)))
                player.TogglePlay();

            GUILayout.Space(10);
            GUILayout.Label($"Frame {player.CurrentFrame + 1}/{player.FrameCount}",
                GUILayout.Width(140), GUILayout.Height(28));

            GUILayout.Label("Speed", GUILayout.Width(46), GUILayout.Height(28));
            player.speed = GUILayout.HorizontalSlider(player.speed, 0.1f, 2f, GUILayout.Width(140));
            GUILayout.Label($"{player.speed:F1}x", GUILayout.Width(40), GUILayout.Height(28));
            GUILayout.EndHorizontal();

            GUILayout.Space(6);
            float t = GUILayout.HorizontalSlider(player.Normalized, 0f, 1f);
            if (Mathf.Abs(t - player.Normalized) > 0.0005f)
            {
                player.Pause();
                player.SeekNormalized(t);
            }
            GUILayout.EndArea();
        }
    }
}
