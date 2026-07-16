using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using BadmintonVR.SkeletonPlayer;

/// <summary>
/// Tools > Badminton > Debug HUD
///
/// Adds/removes the runtime pipeline-debug view (confidence coloring, court
/// trail with clamp markers, live stats HUD) on the scene's twin(s).
/// Press Play to see it; H toggles at runtime.
/// </summary>
public static class DebugHUDSetup
{
    [MenuItem("Tools/Badminton/Debug HUD/Add To Twin")]
    public static void Add()
    {
        var playbacks = Object.FindObjectsByType<SkeletonPlayback>(
            FindObjectsInactive.Include, FindObjectsSortMode.None);
        if (playbacks.Length == 0)
        {
            EditorUtility.DisplayDialog("Debug HUD",
                "No SkeletonPlayback in the open scene. Open the 'badminton' scene first.", "OK");
            return;
        }
        int added = 0;
        foreach (var p in playbacks)
        {
            if (p.GetComponent<PipelineDebugHUD>() != null) continue;
            Undo.AddComponent<PipelineDebugHUD>(p.gameObject);
            EditorUtility.SetDirty(p.gameObject);
            added++;
        }
        EditorSceneManager.MarkSceneDirty(playbacks[0].gameObject.scene);
        Debug.Log($"[DebugHUD] added to {added} twin(s). Play mode: joints tint " +
                  "green→red by confidence, cyan floor trail with red clamp markers, " +
                  "stats box top-left. H toggles.");
    }

    [MenuItem("Tools/Badminton/Debug HUD/Remove")]
    public static void Remove()
    {
        var huds = Object.FindObjectsByType<PipelineDebugHUD>(
            FindObjectsInactive.Include, FindObjectsSortMode.None);
        foreach (var h in huds)
        {
            EditorSceneManager.MarkSceneDirty(h.gameObject.scene);
            Undo.DestroyObjectImmediate(h);
        }
        Debug.Log($"[DebugHUD] removed {huds.Length} debug HUD(s).");
    }
}
