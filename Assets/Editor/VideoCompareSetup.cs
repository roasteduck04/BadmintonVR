using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using BadmintonVR.SkeletonPlayer;

/// <summary>
/// Tools > Badminton > Video Compare
///
/// Adds/removes the picture-in-picture source-video overlay on the scene's twin.
/// The overlay only draws in Play mode (that's when the twin animates) and
/// follows the Clip Switcher: whichever clip the twin plays, it shows the
/// matching data/raw/&lt;stem&gt;.mp4 in sync.
/// </summary>
public static class VideoCompareSetup
{
    [MenuItem("Tools/Badminton/Video Compare/Add Overlay To Scene")]
    public static void Add()
    {
        var playbacks = Object.FindObjectsByType<SkeletonPlayback>(
            FindObjectsInactive.Include, FindObjectsSortMode.None);
        if (playbacks.Length == 0)
        {
            EditorUtility.DisplayDialog("Video Compare",
                "No SkeletonPlayback in the open scene. Open the 'badminton' scene first.", "OK");
            return;
        }
        int added = 0;
        foreach (var p in playbacks)
        {
            if (p.GetComponent<VideoCompareOverlay>() != null) continue;
            Undo.AddComponent<VideoCompareOverlay>(p.gameObject);
            EditorUtility.SetDirty(p.gameObject);
            added++;
        }
        if (playbacks.Length > 0)
            EditorSceneManager.MarkSceneDirty(playbacks[0].gameObject.scene);
        Debug.Log($"[VideoCompare] overlay added to {added} twin object(s) " +
                  $"({playbacks.Length - added} already had it). Press Play to see the " +
                  "source video in the corner; press V to toggle it.");
    }

    [MenuItem("Tools/Badminton/Video Compare/Remove Overlay")]
    public static void Remove()
    {
        var overlays = Object.FindObjectsByType<VideoCompareOverlay>(
            FindObjectsInactive.Include, FindObjectsSortMode.None);
        foreach (var o in overlays)
        {
            EditorSceneManager.MarkSceneDirty(o.gameObject.scene);
            Undo.DestroyObjectImmediate(o);
        }
        Debug.Log($"[VideoCompare] removed {overlays.Length} overlay(s).");
    }
}
