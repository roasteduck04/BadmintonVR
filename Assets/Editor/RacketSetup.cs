using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using BadmintonVR.SkeletonPlayer;

/// <summary>
/// Tools > Badminton > Racket
///
/// Adds/removes the arm-estimated racket visual on the scene's twin(s).
/// The racket only shows in Play mode, only for clips listed in
/// RacketVisual.clipsWithRacket (default: test_3, test_4, test_5), and hides
/// itself when the wrist/elbow confidence drops.
/// </summary>
public static class RacketSetup
{
    [MenuItem("Tools/Badminton/Racket/Add To Twin")]
    public static void Add()
    {
        var playbacks = Object.FindObjectsByType<SkeletonPlayback>(
            FindObjectsInactive.Include, FindObjectsSortMode.None);
        if (playbacks.Length == 0)
        {
            EditorUtility.DisplayDialog("Racket",
                "No SkeletonPlayback in the open scene. Open the 'badminton' scene first.", "OK");
            return;
        }
        int added = 0;
        foreach (var p in playbacks)
        {
            if (p.GetComponent<RacketVisual>() != null) continue;
            Undo.AddComponent<RacketVisual>(p.gameObject);
            EditorUtility.SetDirty(p.gameObject);
            added++;
        }
        EditorSceneManager.MarkSceneDirty(playbacks[0].gameObject.scene);
        Debug.Log($"[Racket] visual added to {added} twin(s) " +
                  $"({playbacks.Length - added} already had it). Orange racket appears in " +
                  "Play mode on racket clips (right hand, elbow→wrist direction).");
    }

    [MenuItem("Tools/Badminton/Racket/Remove")]
    public static void Remove()
    {
        var visuals = Object.FindObjectsByType<RacketVisual>(
            FindObjectsInactive.Include, FindObjectsSortMode.None);
        foreach (var v in visuals)
        {
            EditorSceneManager.MarkSceneDirty(v.gameObject.scene);
            Undo.DestroyObjectImmediate(v);
        }
        Debug.Log($"[Racket] removed {visuals.Length} racket visual(s).");
    }
}
