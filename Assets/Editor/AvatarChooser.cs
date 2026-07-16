using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using BadmintonVR.SkeletonPlayer;

/// <summary>
/// Pick a rigged avatar, then place it at the center of one side of the court,
/// driven by a skeleton clip. Menu: Tools > Badminton > Choose Avatar.
///
/// The avatar is only spawned AFTER you choose one and click Place — nothing
/// appears just from opening the window.
/// </summary>
public class AvatarChooser : EditorWindow
{
    const string DefaultClip = "skeleton/20260715_clears_sideview.json";
    const float HALF_L = 13.40f / 2f;          // court half-length (Z)
    const float SIDE_CENTER = HALF_L / 2f;      // 3.35 m: middle of one half

    class Candidate { public string path; public GameObject asset; public bool humanoid; }

    List<Candidate> _found = new List<Candidate>();
    int _selected = -1;
    int _side = 0;                 // 0 = Front (+Z), 1 = Back (-Z)
    string _clip = DefaultClip;
    Vector2 _scroll;

    [MenuItem("Tools/Badminton/Choose Avatar")]
    public static void Open()
    {
        var w = GetWindow<AvatarChooser>(true, "Choose Avatar");
        w.minSize = new Vector2(420, 380);
        w.Refresh();
    }

    void Refresh()
    {
        _found.Clear();
        _selected = -1;
        foreach (var guid in AssetDatabase.FindAssets("t:GameObject"))
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            // Model files (.fbx/.glb/.obj) and character prefabs only.
            string ext = Path.GetExtension(path).ToLowerInvariant();
            bool isModel = ext == ".fbx" || ext == ".glb" || ext == ".gltf" || ext == ".obj";
            bool isPrefab = ext == ".prefab";
            if (!isModel && !isPrefab) continue;

            var asset = AssetDatabase.LoadAssetAtPath<GameObject>(path);
            if (asset == null) continue;

            bool humanoid = false;
            var importer = AssetImporter.GetAtPath(path) as ModelImporter;
            if (importer != null)
                humanoid = importer.animationType == ModelImporterAnimationType.Human;
            else
            {
                var anim = asset.GetComponentInChildren<Animator>();
                humanoid = anim != null && anim.avatar != null && anim.avatar.isHuman;
            }

            // Skip our own scene primitives / non-character models with no skinned mesh.
            bool hasSkin = asset.GetComponentInChildren<SkinnedMeshRenderer>() != null;
            if (!humanoid && !hasSkin) continue;

            _found.Add(new Candidate { path = path, asset = asset, humanoid = humanoid });
        }
        if (_found.Count > 0) _selected = 0;
        Repaint();
    }

    void OnGUI()
    {
        EditorGUILayout.LabelField("1. Pick an avatar", EditorStyles.boldLabel);
        EditorGUILayout.HelpBox(
            "Drop a rigged Humanoid model (e.g. a Mixamo FBX in T-pose) into " +
            "Assets/. If it's not yet set to Humanoid, this tool fixes that for " +
            "you when you place it.", MessageType.Info);

        if (GUILayout.Button("Refresh list")) Refresh();

        if (_found.Count == 0)
        {
            EditorGUILayout.HelpBox(
                "No character models found. Import an FBX/GLB with a skinned mesh " +
                "into the project, then Refresh.", MessageType.Warning);
        }
        else
        {
            _scroll = EditorGUILayout.BeginScrollView(_scroll, GUILayout.Height(150));
            for (int i = 0; i < _found.Count; i++)
            {
                var c = _found[i];
                EditorGUILayout.BeginHorizontal();
                bool sel = EditorGUILayout.Toggle(_selected == i, GUILayout.Width(20));
                if (sel) _selected = i;
                string tag = c.humanoid ? "  [Humanoid]" : "  [will convert]";
                EditorGUILayout.LabelField(Path.GetFileNameWithoutExtension(c.path) + tag);
                EditorGUILayout.EndHorizontal();
            }
            EditorGUILayout.EndScrollView();
        }

        EditorGUILayout.Space();
        EditorGUILayout.LabelField("2. Where to place it", EditorStyles.boldLabel);
        _side = EditorGUILayout.Popup("Court side", _side,
            new[] { "Front half (near +Z, faces net)", "Back half (near -Z, faces net)" });
        _clip = EditorGUILayout.TextField("Clip (StreamingAssets)", _clip);

        EditorGUILayout.Space();
        using (new EditorGUI.DisabledScope(_selected < 0))
        {
            if (GUILayout.Button("Place Avatar on Court", GUILayout.Height(32)))
                Place(_found[_selected]);
        }
    }

    void Place(Candidate c)
    {
        // Ensure a court exists.
        if (GameObject.Find("BadmintonCourt") == null)
            CourtBuilder.BuildCourt();

        // Convert to Humanoid if needed (Mixamo FBX often imports Generic).
        if (!c.humanoid)
        {
            var importer = AssetImporter.GetAtPath(c.path) as ModelImporter;
            if (importer != null)
            {
                importer.animationType = ModelImporterAnimationType.Human;
                importer.SaveAndReimport();
                AssetDatabase.Refresh();
                c.asset = AssetDatabase.LoadAssetAtPath<GameObject>(c.path);
                Debug.Log("[AvatarChooser] Converted '" + Path.GetFileName(c.path) +
                    "' to Humanoid rig.");
            }
        }

        var old = GameObject.Find("AvatarTwin");
        if (old != null) Undo.DestroyObjectImmediate(old);

        var inst = (GameObject)PrefabUtility.InstantiatePrefab(c.asset);
        if (inst == null) { Debug.LogError("[AvatarChooser] Could not instantiate avatar."); return; }
        inst.name = "AvatarTwin";
        Undo.RegisterCreatedObjectUndo(inst, "Place Avatar");

        float z = _side == 0 ? SIDE_CENTER : -SIDE_CENTER;
        inst.transform.position = new Vector3(0f, 0f, z);
        // Face the net (origin). Front half looks toward -Z, back half toward +Z.
        Vector3 look = new Vector3(0f, 0f, -z).normalized;
        inst.transform.rotation = Quaternion.LookRotation(look, Vector3.up);

        var anim = inst.GetComponent<Animator>();
        if (anim == null) anim = inst.AddComponent<Animator>();
        if (anim.avatar == null || !anim.avatar.isHuman)
            Debug.LogWarning("[AvatarChooser] '" + inst.name + "' has no Humanoid " +
                "avatar; retargeting will be disabled. Check the model's Rig settings.");

        var driver = inst.AddComponent<HumanoidPoseDriver>();
        driver.streamingAssetsPath = _clip;

        Selection.activeGameObject = inst;
        SceneView.FrameLastActiveSceneView();
        EditorSceneManager.MarkSceneDirty(inst.scene);
        Debug.Log("[AvatarChooser] Placed '" + inst.name + "' at " +
            (_side == 0 ? "front" : "back") + " side center. Press Play to animate. " +
            "If the body faces the wrong way, toggle 'Face Flip' on the " +
            "HumanoidPoseDriver.");
        Close();
    }
}
