using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using BadmintonVR.SkeletonPlayer;

/// <summary>
/// One-click scene setup for the Phase 1 twin.
/// Menu: Tools > Badminton > Build Skeleton Player
/// Builds the court (if missing), creates the twin object with playback +
/// renderer + on-screen UI, and frames the camera. Then press Play.
/// </summary>
public static class SkeletonPlayerSetup
{
    const string DefaultClip = "skeleton/20260715_clears_sideview.json";

    [MenuItem("Tools/Badminton/Build Skeleton Player")]
    public static void Build()
    {
        // Court (reuse the existing builder if the court isn't already there).
        if (GameObject.Find("BadmintonCourt") == null)
            CourtBuilder.BuildCourt();

        var existing = GameObject.Find("SkeletonTwin");
        if (existing != null) Undo.DestroyObjectImmediate(existing);

        var twin = new GameObject("SkeletonTwin");
        Undo.RegisterCreatedObjectUndo(twin, "Build Skeleton Player");
        twin.transform.position = Vector3.zero; // court center; plays in place (Phase 1)

        var renderer = twin.AddComponent<SkeletonRenderer>();
        var playback = twin.AddComponent<SkeletonPlayback>();
        var ui = twin.AddComponent<PlaybackUI>();
        playback.streamingAssetsPath = DefaultClip;
        ui.player = playback;

        FrameCamera();

        // Edit-mode preview so the twin is visible immediately (frame 0), without
        // entering Play. These preview objects use DontSave so they don't clutter
        // the saved scene; pressing Play rebuilds the skeleton live.
        var doc = SkeletonDoc.Load(DefaultClip);
        if (doc == null)
        {
            Debug.LogError("[SkeletonPlayerSetup] Could NOT load clip '" + DefaultClip +
                "'. Expected at Assets/StreamingAssets/" + DefaultClip +
                ". Run the Python extractor and copy the JSON there.");
        }
        else
        {
            renderer.Build(doc);
            renderer.ShowFrame(doc, 0);
            foreach (Transform child in twin.transform)
                child.gameObject.hideFlags = HideFlags.DontSave;
            Debug.Log("[SkeletonPlayerSetup] Twin built: " + doc.FrameCount +
                " frames, " + doc.Duration.ToString("F1") + "s. " +
                "Showing frame 0 in edit mode; press Play to animate.");
        }

        Selection.activeGameObject = twin;
        SceneView.FrameLastActiveSceneView();
        EditorSceneManager.MarkSceneDirty(twin.scene);
    }

    static void FrameCamera()
    {
        var cam = Camera.main;
        if (cam == null)
        {
            var go = new GameObject("Main Camera");
            go.tag = "MainCamera";
            cam = go.AddComponent<Camera>();
        }
        // A 3/4 view of a ~1.7 m twin standing at the origin.
        cam.transform.position = new Vector3(2.6f, 1.5f, 3.4f);
        cam.transform.rotation = Quaternion.LookRotation(
            (new Vector3(0f, 0.9f, 0f) - cam.transform.position).normalized, Vector3.up);
        cam.nearClipPlane = 0.1f;
    }
}
