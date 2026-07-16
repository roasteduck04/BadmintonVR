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
    // Phase-2 default: the court-position clip. It plays back as a stick figure
    // that WALKS the tracked half (joints + lines, no skinned model).
    const string DefaultClip = "skeleton/test_5.json";

    [MenuItem("Tools/Badminton/Build Skeleton Player")]
    public static void Build()
    {
        // Court (reuse the existing builder if the court isn't already there).
        // Build the tracked +Z half so the floor matches the recorded box.
        if (GameObject.Find("BadmintonCourt") == null)
            CourtBuilder.BuildCourt(CourtBuilder.Scope.TrackedHalf);

        var existing = GameObject.Find("SkeletonTwin");
        if (existing != null) Undo.DestroyObjectImmediate(existing);

        // Revert to joints + lines: remove any skinned-model twins driven by
        // HumanoidPoseDriver (AvatarTwin / Player_Front / Player_Back) so only the
        // stick figure remains.
        foreach (var d in Object.FindObjectsByType<HumanoidPoseDriver>(
                     FindObjectsInactive.Include, FindObjectsSortMode.None))
        {
            if (d != null) Undo.DestroyObjectImmediate(d.gameObject);
        }

        var twin = new GameObject("SkeletonTwin");
        Undo.RegisterCreatedObjectUndo(twin, "Build Skeleton Player");
        twin.transform.position = Vector3.zero; // start; SkeletonPlayback moves it to the court position

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
            // Preview at the clip's start court position (matches runtime).
            if (playback.driveRootPosition && doc.HasRoot)
            {
                Vector2 xz = doc.RootXZ(0);
                twin.transform.position = new Vector3(xz.x, 0f, xz.y);
            }
            renderer.Build(doc);
            renderer.ShowFrame(doc, 0);
            foreach (Transform child in twin.transform)
                child.gameObject.hideFlags = HideFlags.DontSave;
            Debug.Log("[SkeletonPlayerSetup] Stick-figure twin built: " + doc.FrameCount +
                " frames, " + doc.Duration.ToString("F1") + "s" +
                (doc.HasRoot ? " (walks the tracked half)" : " (plays in place)") +
                ". Showing frame 0 in edit mode; press Play to animate.");
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
        // View the tracked +Z half from above the net, looking down the court —
        // the same vantage as the capture camera. Frames the walking region
        // (z ~ 2..7 m).
        cam.transform.position = new Vector3(0f, 3.2f, -1.8f);
        cam.transform.rotation = Quaternion.LookRotation(
            (new Vector3(0f, 0.6f, 4.3f) - cam.transform.position).normalized, Vector3.up);
        cam.nearClipPlane = 0.1f;
    }
}
