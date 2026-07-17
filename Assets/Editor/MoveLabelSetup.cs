using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using BadmintonVR.SkeletonPlayer;

/// <summary>
/// Tools > Badminton > Move Label
/// Adds/removes the move-label subtitle HUD (banner + segment timeline) on
/// the scene's twin(s). Labels come from the clip's `moves` block — run
/// tools/label_moves.py --write first. M toggles at runtime.
/// </summary>
public static class MoveLabelSetup
{
    [MenuItem("Tools/Badminton/Move Label/Add To Twin")]
    public static void Add()
    {
        var playbacks = Object.FindObjectsByType<SkeletonPlayback>(
            FindObjectsInactive.Include, FindObjectsSortMode.None);
        if (playbacks.Length == 0)
        {
            EditorUtility.DisplayDialog("Move Label",
                "No SkeletonPlayback in the open scene. Open the 'badminton' scene first.", "OK");
            return;
        }
        int added = 0;
        foreach (var p in playbacks)
        {
            if (p.GetComponent<MoveLabelHUD>() != null) continue;
            Undo.AddComponent<MoveLabelHUD>(p.gameObject);
            EditorUtility.SetDirty(p.gameObject);
            added++;
        }
        EditorSceneManager.MarkSceneDirty(playbacks[0].gameObject.scene);
        Debug.Log($"[MoveLabel] added to {added} twin(s). Play mode: banner top-center, " +
                  "timeline bottom. M toggles. Clips without a moves block show nothing.");
    }

    [MenuItem("Tools/Badminton/Move Label/Remove")]
    public static void Remove()
    {
        var huds = Object.FindObjectsByType<MoveLabelHUD>(
            FindObjectsInactive.Include, FindObjectsSortMode.None);
        foreach (var h in huds)
        {
            EditorSceneManager.MarkSceneDirty(h.gameObject.scene);
            Undo.DestroyObjectImmediate(h);
        }
        Debug.Log($"[MoveLabel] removed {huds.Length} move-label HUD(s).");
    }
}
