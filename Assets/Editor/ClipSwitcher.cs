using System.IO;
using System.Linq;
using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using BadmintonVR.SkeletonPlayer;

/// <summary>
/// Tools > Badminton > Clip Switcher
///
/// One window to flip the scene's twin between the extracted testing clips
/// (test_3, test_4, test_5, ...) without hand-editing the scene or the
/// SkeletonPlayback component. It scans Assets/StreamingAssets/skeleton/*.json
/// (nothing hardcoded) and lists each as a button:
///   - in Edit mode: sets SkeletonPlayback.streamingAssetsPath and marks the
///     scene dirty (Ctrl+S to keep it), so the next Play uses that clip;
///   - in Play mode: calls Load() live so the twin swaps immediately.
/// The clip the twin currently points at is marked ● and disabled.
/// </summary>
public class ClipSwitcher : EditorWindow
{
    Vector2 _scroll;

    [MenuItem("Tools/Badminton/Clip Switcher")]
    public static void Open()
    {
        var w = GetWindow<ClipSwitcher>("Clip Switcher");
        w.minSize = new Vector2(320, 220);
        w.Show();
    }

    static string SkeletonDir =>
        Path.Combine(Application.streamingAssetsPath, "skeleton");

    void OnGUI()
    {
        EditorGUILayout.Space();
        EditorGUILayout.LabelField("Switch the twin's playback clip", EditorStyles.boldLabel);

        var playbacks = Object.FindObjectsByType<SkeletonPlayback>(
            FindObjectsInactive.Include, FindObjectsSortMode.None);
        if (playbacks.Length == 0)
        {
            EditorGUILayout.HelpBox(
                "No SkeletonPlayback in the open scene. Open the 'badminton' scene first.",
                MessageType.Warning);
            if (GUILayout.Button("Refresh")) Repaint();
            return;
        }
        var playback = playbacks[0];
        if (playbacks.Length > 1)
            EditorGUILayout.HelpBox(
                $"{playbacks.Length} SkeletonPlayback objects found — switching the first " +
                $"('{playback.gameObject.name}'). Select another below.", MessageType.Info);

        // let the user pick which player object to drive if there are several
        if (playbacks.Length > 1)
        {
            int idx = System.Array.IndexOf(playbacks, playback);
            int pick = EditorGUILayout.Popup("Target",
                Mathf.Max(0, idx), playbacks.Select(p => p.gameObject.name).ToArray());
            playback = playbacks[Mathf.Clamp(pick, 0, playbacks.Length - 1)];
        }

        EditorGUILayout.LabelField("Current", playback.streamingAssetsPath);
        EditorGUILayout.Space();

        if (!Directory.Exists(SkeletonDir))
        {
            EditorGUILayout.HelpBox("No StreamingAssets/skeleton/ folder yet.", MessageType.Warning);
            return;
        }

        var files = Directory.GetFiles(SkeletonDir, "*.json")
            .Select(Path.GetFileName).OrderBy(n => n).ToArray();
        if (files.Length == 0)
        {
            EditorGUILayout.HelpBox("No .json clips in StreamingAssets/skeleton/.", MessageType.Info);
            return;
        }

        _scroll = EditorGUILayout.BeginScrollView(_scroll);
        foreach (var file in files)
        {
            string rel = "skeleton/" + file;
            bool isCurrent = rel == playback.streamingAssetsPath;
            EditorGUILayout.BeginHorizontal();
            GUILayout.Label(isCurrent ? "●" : "", GUILayout.Width(16));
            using (new EditorGUI.DisabledScope(isCurrent))
            {
                if (GUILayout.Button(file, GUILayout.Height(22)))
                    SetClip(playback, rel);
            }
            EditorGUILayout.EndHorizontal();
        }
        EditorGUILayout.EndScrollView();

        EditorGUILayout.Space();
        EditorGUILayout.BeginHorizontal();
        if (GUILayout.Button("Refresh")) Repaint();
        if (!Application.isPlaying && GUILayout.Button("Enter Play Mode"))
            EditorApplication.isPlaying = true;
        EditorGUILayout.EndHorizontal();

        EditorGUILayout.HelpBox(
            Application.isPlaying
                ? "Play mode: clicking a clip swaps the twin immediately."
                : "Edit mode: clicking a clip sets it and marks the scene dirty (Ctrl+S to save).",
            MessageType.None);
    }

    static void SetClip(SkeletonPlayback playback, string rel)
    {
        if (Application.isPlaying)
        {
            playback.streamingAssetsPath = rel;
            playback.Load(rel);          // swap live
            Debug.Log($"[ClipSwitcher] now playing {rel}");
        }
        else
        {
            // serialized edit so Undo works and the scene records it
            var so = new SerializedObject(playback);
            so.FindProperty("streamingAssetsPath").stringValue = rel;
            so.ApplyModifiedProperties();
            EditorUtility.SetDirty(playback);
            EditorSceneManager.MarkSceneDirty(playback.gameObject.scene);
            Debug.Log($"[ClipSwitcher] set clip to {rel} (Ctrl+S to save; Play to view).");
        }
    }
}
