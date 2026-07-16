using System.IO;
using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using BadmintonVR.SkeletonPlayer;

/// <summary>
/// One click: build the court and drop TWO avatars, one on each side, each
/// driven by its own clip. Menu: Tools > Badminton > Build Two-Player Scene.
///
/// Front half (near +Z) plays FrontClip; back half (near -Z) plays BackClip.
/// Both face the net. Uses the first Humanoid/skinned model it finds under
/// Assets (auto-converting it to a Humanoid rig if needed).
/// </summary>
public static class TwoPlayerSetup
{
    const float HALF_L = 13.40f / 2f;
    const float SIDE_CENTER = HALF_L / 2f;   // 3.35 m
    const string FrontClip = "skeleton/test_1.json";
    const string BackClip = "skeleton/test_2.json";

    [MenuItem("Tools/Badminton/Build Two-Player Scene")]
    public static void Build()
    {
        if (GameObject.Find("BadmintonCourt") == null)
            CourtBuilder.BuildCourt();

        string modelPath = FindHumanoidModel();
        if (modelPath == null)
        {
            Debug.LogError("[TwoPlayerSetup] No character model found under Assets/. " +
                "Import a rigged FBX/GLB (e.g. from Mixamo) and try again.");
            return;
        }
        var model = EnsureHumanoid(modelPath);
        if (model == null) return;

        SpawnPlayer(model, "Player_Front", +SIDE_CENTER, FrontClip);
        SpawnPlayer(model, "Player_Back", -SIDE_CENTER, BackClip);

        SceneView.FrameLastActiveSceneView();
        EditorSceneManager.MarkSceneDirty(
            UnityEngine.SceneManagement.SceneManager.GetActiveScene());
        Debug.Log("[TwoPlayerSetup] Two players placed (front = test_1, back = test_2). " +
            "Press Play. If a body faces the wrong way, tick 'Face Flip' on its " +
            "HumanoidPoseDriver.");
    }

    static void SpawnPlayer(GameObject model, string name, float z, string clip)
    {
        var old = GameObject.Find(name);
        if (old != null) Undo.DestroyObjectImmediate(old);

        var inst = (GameObject)PrefabUtility.InstantiatePrefab(model);
        if (inst == null) { Debug.LogError("[TwoPlayerSetup] instantiate failed."); return; }
        inst.name = name;
        Undo.RegisterCreatedObjectUndo(inst, "Build Two-Player Scene");

        inst.transform.position = new Vector3(0f, 0f, z);
        inst.transform.rotation = Quaternion.LookRotation(new Vector3(0f, 0f, -z).normalized, Vector3.up);

        if (inst.GetComponent<Animator>() == null) inst.AddComponent<Animator>();
        var driver = inst.AddComponent<HumanoidPoseDriver>();
        driver.streamingAssetsPath = clip;
    }

    /// <summary>First model with a skinned mesh (prefers one already Humanoid).</summary>
    static string FindHumanoidModel()
    {
        string firstSkinned = null;
        foreach (var guid in AssetDatabase.FindAssets("t:GameObject"))
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            string ext = Path.GetExtension(path).ToLowerInvariant();
            if (ext != ".fbx" && ext != ".glb" && ext != ".gltf" && ext != ".prefab") continue;

            var asset = AssetDatabase.LoadAssetAtPath<GameObject>(path);
            if (asset == null || asset.GetComponentInChildren<SkinnedMeshRenderer>() == null) continue;

            var importer = AssetImporter.GetAtPath(path) as ModelImporter;
            if (importer != null && importer.animationType == ModelImporterAnimationType.Human)
                return path; // already humanoid — best choice
            if (firstSkinned == null) firstSkinned = path;
        }
        return firstSkinned;
    }

    static GameObject EnsureHumanoid(string path)
    {
        var importer = AssetImporter.GetAtPath(path) as ModelImporter;
        if (importer != null && importer.animationType != ModelImporterAnimationType.Human)
        {
            importer.animationType = ModelImporterAnimationType.Human;
            importer.SaveAndReimport();
            AssetDatabase.Refresh();
            Debug.Log("[TwoPlayerSetup] Converted '" + Path.GetFileName(path) + "' to Humanoid.");
        }
        return AssetDatabase.LoadAssetAtPath<GameObject>(path);
    }
}
