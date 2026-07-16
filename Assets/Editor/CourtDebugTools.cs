using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text.RegularExpressions;
using UnityEngine;
using UnityEditor;
using BadmintonVR.SkeletonPlayer;

/// <summary>
/// Diagnostic tools for court/position mismatches — the Unity side.
/// (The video side is tools/check_position.py; run both and compare.)
///
///   Tools > Badminton > Debug > Show Court Corner Markers
///     Labeled markers at every point in data/calib/court_geometry.json.
///     Each marker MUST sit exactly on the matching floor-line intersection —
///     if one doesn't, the drawn court and the exported geometry disagree.
///
///   Tools > Badminton > Debug > Draw Clip Path
///     Draws the clip's root_court_xz path on the floor (green=start, red=end,
///     a timestamp every 5 s). Compare with data/calib/&lt;clip&gt;_check_topdown.png
///     from check_position.py: same path on both = Unity is faithful to the
///     data, and any offset the eye sees is upstream (calibration/extraction).
///
///   Tools > Badminton > Debug > Clear Debug Markers
/// Nothing is hardcoded: markers come from the exported geometry file, the
/// path comes from the skeleton clip.
/// </summary>
public static class CourtDebugTools
{
    const string RootName = "CourtDebugMarkers";

    // ------------------------------------------------------------ corner markers

    [MenuItem("Tools/Badminton/Debug/Show Court Corner Markers")]
    public static void ShowCornerMarkers()
    {
        var points = LoadGeometryPoints();
        if (points == null) return;

        // If the last court build drew only the tracked (+Z) half, near-half
        // points have no floor lines under them — skip them so every shown
        // marker is checkable. (Read from the file, not assumed.)
        string geoJson = File.ReadAllText(GeometryPath());
        bool halfOnly = geoJson.Contains("\"last_build_scope\": \"tracked_half\"");

        var root = GetDebugRoot("CornerMarkers");
        var mat = MakeMat(new Color(1f, 0.2f, 0.9f)); // magenta — visible on green
        int shown = 0;
        foreach (var kv in points)
        {
            if (halfOnly && kv.Value.y < 0f) continue;
            var g = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            g.name = "pt_" + kv.Key;
            g.transform.SetParent(root.transform);
            g.transform.localScale = Vector3.one * 0.1f;
            g.transform.position = new Vector3(kv.Value.x, 0.05f, kv.Value.y);
            Object.DestroyImmediate(g.GetComponent<Collider>());
            g.GetComponent<Renderer>().sharedMaterial = mat;
            Label(root, kv.Key, new Vector3(kv.Value.x, 0.25f, kv.Value.y), mat);
            shown++;
        }
        SetDontSave(root);
        Debug.Log($"[CourtDebug] {shown} corner markers from court_geometry.json. " +
                  "Every marker must sit ON its floor-line intersection — a marker off a " +
                  "line means the drawn court and the exported geometry disagree.");
        SceneView.RepaintAll();
    }

    // ------------------------------------------------------------ clip path

    [MenuItem("Tools/Badminton/Debug/Draw Clip Path")]
    public static void DrawClipPath()
    {
        // Use the clip the scene's twin is set to; fall back to the default clip.
        string clip = "skeleton/test_5.json";
        var playback = Object.FindFirstObjectByType<SkeletonPlayback>(FindObjectsInactive.Include);
        if (playback != null && !string.IsNullOrEmpty(playback.streamingAssetsPath))
            clip = playback.streamingAssetsPath;

        var doc = SkeletonDoc.Load(clip);
        if (doc == null)
        {
            Debug.LogError($"[CourtDebug] could not load clip '{clip}'.");
            return;
        }
        if (!doc.HasRoot)
        {
            Debug.LogError($"[CourtDebug] clip '{clip}' has no root_court_xz — " +
                           "extract it with --court first.");
            return;
        }

        var root = GetDebugRoot("ClipPath");

        // Path line, colored blue (start) -> red (end), floating just above the floor.
        var lineGo = new GameObject("path");
        lineGo.transform.SetParent(root.transform);
        var lr = lineGo.AddComponent<LineRenderer>();
        lr.useWorldSpace = true;
        lr.widthMultiplier = 0.04f;
        var lineShader = Shader.Find("Sprites/Default");
        lr.sharedMaterial = new Material(lineShader != null ? lineShader : Shader.Find("Universal Render Pipeline/Unlit"));
        lr.colorGradient = new Gradient
        {
            colorKeys = new[]
            {
                new GradientColorKey(new Color(0.2f, 0.4f, 1f), 0f),
                new GradientColorKey(new Color(1f, 0.2f, 0.2f), 1f),
            },
        };
        int n = doc.FrameCount;
        lr.positionCount = n;
        Vector2 min = new Vector2(float.MaxValue, float.MaxValue);
        Vector2 max = new Vector2(float.MinValue, float.MinValue);
        for (int i = 0; i < n; i++)
        {
            Vector2 xz = doc.RootXZ(i);
            lr.SetPosition(i, new Vector3(xz.x, 0.03f, xz.y));
            min = Vector2.Min(min, xz);
            max = Vector2.Max(max, xz);
        }

        // Start / end markers + a timestamp every 5 s (matches the panel times
        // in the check_position.py contact sheet).
        Vector2 s = doc.RootXZ(0), e = doc.RootXZ(n - 1);
        Marker(root, "start", new Vector3(s.x, 0.05f, s.y), new Color(0.1f, 0.9f, 0.1f), 0.14f);
        Marker(root, "end", new Vector3(e.x, 0.05f, e.y), new Color(0.9f, 0.1f, 0.1f), 0.14f);
        var tickMat = MakeMat(Color.white);
        for (float t = 5f; t < doc.Duration; t += 5f)
        {
            int i = Mathf.Clamp(Mathf.RoundToInt(t * doc.Fps), 0, n - 1);
            Vector2 xz = doc.RootXZ(i);
            Label(root, $"{t:0}s", new Vector3(xz.x, 0.2f, xz.y), tickMat);
        }
        SetDontSave(root);

        // Stats against the exported geometry box (not hardcoded numbers).
        string boxNote = "";
        var pts = LoadGeometryPoints(quiet: true);
        if (pts != null && pts.TryGetValue("ssl_fl", out var ssl) &&
            pts.TryGetValue("corner_fr", out var far))
        {
            int inside = 0;
            for (int i = 0; i < n; i++)
            {
                Vector2 xz = doc.RootXZ(i);
                if (xz.x >= ssl.x && xz.x <= far.x && xz.y >= ssl.y && xz.y <= far.y) inside++;
            }
            boxNote = $", {100f * inside / n:0}% inside the tracked box " +
                      $"[{ssl.x:0.00}..{far.x:0.00}]x[{ssl.y:0.00}..{far.y:0.00}]";
        }
        Debug.Log($"[CourtDebug] path '{clip}': {n} frames, start ({s.x:+0.00;-0.00},{s.y:+0.00;-0.00}), " +
                  $"end ({e.x:+0.00;-0.00},{e.y:+0.00;-0.00}), X [{min.x:0.00}..{max.x:0.00}], " +
                  $"Z [{min.y:0.00}..{max.y:0.00}]{boxNote}. Compare with " +
                  "data/calib/<clip>_check_topdown.png (tools/check_position.py).");
        SceneView.RepaintAll();
    }

    // ------------------------------------------------------------ clear

    [MenuItem("Tools/Badminton/Debug/Clear Debug Markers")]
    public static void Clear()
    {
        var root = GameObject.Find(RootName);
        if (root != null) Object.DestroyImmediate(root);
        SceneView.RepaintAll();
    }

    // ------------------------------------------------------------ helpers

    static string GeometryPath() => Path.GetFullPath(Path.Combine(
        Application.dataPath, "..", "data", "calib", "court_geometry.json"));

    /// Parse data/calib/court_geometry.json's "points" without hardcoding values.
    static Dictionary<string, Vector2> LoadGeometryPoints(bool quiet = false)
    {
        string path = GeometryPath();
        if (!File.Exists(path))
        {
            if (!quiet)
                Debug.LogError("[CourtDebug] " + path + " not found — run " +
                               "Tools > Badminton > Build Court first (it exports the geometry).");
            return null;
        }
        string json = File.ReadAllText(path);
        int at = json.IndexOf("\"points\"");
        if (at < 0)
        {
            if (!quiet) Debug.LogError("[CourtDebug] no \"points\" block in " + path);
            return null;
        }
        var points = new Dictionary<string, Vector2>();
        var rx = new Regex("\"(\\w+)\"\\s*:\\s*\\[\\s*(-?[\\d.]+)\\s*,\\s*(-?[\\d.]+)\\s*\\]");
        foreach (Match m in rx.Matches(json, at))
        {
            float x = float.Parse(m.Groups[2].Value, CultureInfo.InvariantCulture);
            float z = float.Parse(m.Groups[3].Value, CultureInfo.InvariantCulture);
            points[m.Groups[1].Value] = new Vector2(x, z);
        }
        if (points.Count == 0)
        {
            if (!quiet) Debug.LogError("[CourtDebug] could not parse points from " + path);
            return null;
        }
        return points;
    }

    static GameObject GetDebugRoot(string child)
    {
        var root = GameObject.Find(RootName);
        if (root == null) root = new GameObject(RootName);
        // rebuilding a group replaces it
        var old = root.transform.Find(child);
        if (old != null) Object.DestroyImmediate(old.gameObject);
        var g = new GameObject(child);
        g.transform.SetParent(root.transform);
        return g;
    }

    static void SetDontSave(GameObject group)
    {
        // Debug-only: keep it out of the saved scene.
        foreach (var t in group.GetComponentsInChildren<Transform>(true))
            t.gameObject.hideFlags = HideFlags.DontSave;
    }

    static void Marker(GameObject parent, string name, Vector3 pos, Color c, float size)
    {
        var g = GameObject.CreatePrimitive(PrimitiveType.Sphere);
        g.name = name;
        g.transform.SetParent(parent.transform);
        g.transform.localScale = Vector3.one * size;
        g.transform.position = pos;
        Object.DestroyImmediate(g.GetComponent<Collider>());
        g.GetComponent<Renderer>().sharedMaterial = MakeMat(c);
    }

    static void Label(GameObject parent, string text, Vector3 pos, Material mat)
    {
        var g = new GameObject("label_" + text);
        g.transform.SetParent(parent.transform);
        g.transform.position = pos;
        // default TextMesh orientation reads correctly from the -Z camera side,
        // where both the capture phone and the scene camera sit
        var tm = g.AddComponent<TextMesh>();
        tm.text = text;
        tm.characterSize = 0.06f;
        tm.fontSize = 48;
        tm.anchor = TextAnchor.LowerCenter;
        tm.color = mat.HasProperty("_BaseColor") ? mat.GetColor("_BaseColor") : mat.color;
    }

    static Material MakeMat(Color c)
    {
        var shader = Shader.Find("Universal Render Pipeline/Lit");
        if (shader == null) shader = Shader.Find("Standard");
        var m = new Material(shader);
        if (m.HasProperty("_BaseColor")) m.SetColor("_BaseColor", c);
        else m.color = c;
        return m;
    }
}
