using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using BadmintonVR.SkeletonPlayer;

/// <summary>
/// Tools > Badminton > Twin Driver (Track B)
///
/// Adds/removes the persistent twin driver (springs + IK + foot locking +
/// lookahead) on the scene's stick twin, and wires any humanoid avatar
/// (HumanoidPoseDriver) to follow the same driven pose. Press Play, then T
/// toggles raw vs driven for a direct comparison.
/// </summary>
public static class TwinDriverSetup
{
    [MenuItem("Tools/Badminton/Twin Driver/Add To Twin")]
    public static void Add()
    {
        var playbacks = Object.FindObjectsByType<SkeletonPlayback>(
            FindObjectsInactive.Include, FindObjectsSortMode.None);
        if (playbacks.Length == 0)
        {
            EditorUtility.DisplayDialog("Twin Driver",
                "No SkeletonPlayback in the open scene. Open the 'badminton' scene first.", "OK");
            return;
        }

        TwinDriver first = null;
        int added = 0;
        foreach (var p in playbacks)
        {
            var d = p.GetComponent<TwinDriver>();
            if (d == null) { d = Undo.AddComponent<TwinDriver>(p.gameObject); added++; }
            if (first == null) first = d;
            EditorUtility.SetDirty(p.gameObject);
        }

        // humanoid avatars follow the same driven pose
        int wired = 0;
        foreach (var h in Object.FindObjectsByType<HumanoidPoseDriver>(
                     FindObjectsInactive.Include, FindObjectsSortMode.None))
        {
            if (h.poseSource == first) continue;
            Undo.RecordObject(h, "Wire pose source");
            h.poseSource = first;
            EditorUtility.SetDirty(h);
            wired++;
        }

        EditorSceneManager.MarkSceneDirty(playbacks[0].gameObject.scene);
        Debug.Log($"[TwinDriver] added to {added} twin(s), wired {wired} humanoid avatar(s). " +
                  "Play mode: T toggles RAW vs DRIVEN. Tune lookahead/halflife on the component.");
    }

    [MenuItem("Tools/Badminton/Twin Driver/Remove")]
    public static void Remove()
    {
        foreach (var h in Object.FindObjectsByType<HumanoidPoseDriver>(
                     FindObjectsInactive.Include, FindObjectsSortMode.None))
        {
            if (h.poseSource == null) continue;
            Undo.RecordObject(h, "Clear pose source");
            h.poseSource = null;
            EditorUtility.SetDirty(h);
        }
        var drivers = Object.FindObjectsByType<TwinDriver>(
            FindObjectsInactive.Include, FindObjectsSortMode.None);
        foreach (var d in drivers)
        {
            EditorSceneManager.MarkSceneDirty(d.gameObject.scene);
            Undo.DestroyObjectImmediate(d);
        }
        Debug.Log($"[TwinDriver] removed {drivers.Length} driver(s).");
    }
}
