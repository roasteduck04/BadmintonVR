using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;

/// <summary>
/// Builds a simple, regulation-proportioned badminton court out of primitives.
/// Menu: Tools > Badminton > Build Court
/// Low-fidelity on purpose: flat colored surface, painted lines, a net, and two posts.
/// </summary>
public static class CourtBuilder
{
    // Doubles court dimensions (metres). Court runs along Z, width along X.
    const float LENGTH = 13.40f;         // full length (Z)
    const float WIDTH = 6.10f;           // full width (X)
    const float HALF_L = LENGTH / 2f;    // 6.70
    const float HALF_W = WIDTH / 2f;     // 3.05
    const float LINE = 0.04f;            // 40 mm line width
    const float SHORT_SERVICE = 1.98f;   // from net
    const float DOUBLES_BACK = 0.76f;    // doubles long-service inset from back line
    const float SINGLES_HALF_W = 2.59f;  // singles sideline
    const float NET_TOP = 1.524f;        // net height at centre
    const float NET_BOTTOM = 0.76f;      // bottom edge of the net mesh
    const float POST_HEIGHT = 1.55f;     // post height

    const float LINE_Y = 0.011f;         // lines sit just above the floor surface (top at y=0)

    [MenuItem("Tools/Badminton/Build Court")]
    public static void BuildCourt()
    {
        // Remove a previous build so re-running is clean.
        var existing = GameObject.Find("BadmintonCourt");
        if (existing != null) Undo.DestroyObjectImmediate(existing);

        var root = new GameObject("BadmintonCourt");
        Undo.RegisterCreatedObjectUndo(root, "Build Badminton Court");

        Material surface = MakeMat(new Color(0.16f, 0.42f, 0.22f)); // green
        Material white = MakeMat(Color.white);
        Material netMat = MakeMat(new Color(0.08f, 0.08f, 0.08f));
        Material postMat = MakeMat(new Color(0.20f, 0.20f, 0.20f));

        // Floor slab (slightly larger than the court so lines have a margin).
        var floor = Box(root, surface, "Floor",
            new Vector3(0f, -0.05f, 0f),
            new Vector3(WIDTH + 1.0f, 0.10f, LENGTH + 1.0f));

        // --- Painted lines ---
        // Outer boundary
        Box(root, white, "Sideline_R", new Vector3(HALF_W, LINE_Y, 0f), new Vector3(LINE, 0.02f, LENGTH));
        Box(root, white, "Sideline_L", new Vector3(-HALF_W, LINE_Y, 0f), new Vector3(LINE, 0.02f, LENGTH));
        Box(root, white, "Baseline_F", new Vector3(0f, LINE_Y, HALF_L), new Vector3(WIDTH, 0.02f, LINE));
        Box(root, white, "Baseline_B", new Vector3(0f, LINE_Y, -HALF_L), new Vector3(WIDTH, 0.02f, LINE));

        // Net centre line
        Box(root, white, "NetLine", new Vector3(0f, LINE_Y, 0f), new Vector3(WIDTH, 0.02f, LINE));

        // Short service lines
        Box(root, white, "ShortService_F", new Vector3(0f, LINE_Y, SHORT_SERVICE), new Vector3(WIDTH, 0.02f, LINE));
        Box(root, white, "ShortService_B", new Vector3(0f, LINE_Y, -SHORT_SERVICE), new Vector3(WIDTH, 0.02f, LINE));

        // Doubles long service lines
        float dbl = HALF_L - DOUBLES_BACK;
        Box(root, white, "DoublesLong_F", new Vector3(0f, LINE_Y, dbl), new Vector3(WIDTH, 0.02f, LINE));
        Box(root, white, "DoublesLong_B", new Vector3(0f, LINE_Y, -dbl), new Vector3(WIDTH, 0.02f, LINE));

        // Centre lines (short service -> back boundary, each half)
        float cLen = HALF_L - SHORT_SERVICE;
        Box(root, white, "CentreLine_F", new Vector3(0f, LINE_Y, (SHORT_SERVICE + HALF_L) / 2f), new Vector3(LINE, 0.02f, cLen));
        Box(root, white, "CentreLine_B", new Vector3(0f, LINE_Y, -(SHORT_SERVICE + HALF_L) / 2f), new Vector3(LINE, 0.02f, cLen));

        // Singles sidelines
        Box(root, white, "SinglesSide_R", new Vector3(SINGLES_HALF_W, LINE_Y, 0f), new Vector3(LINE, 0.02f, LENGTH));
        Box(root, white, "SinglesSide_L", new Vector3(-SINGLES_HALF_W, LINE_Y, 0f), new Vector3(LINE, 0.02f, LENGTH));

        // --- Net ---
        Box(root, netMat, "Net",
            new Vector3(0f, (NET_TOP + NET_BOTTOM) / 2f, 0f),
            new Vector3(WIDTH, NET_TOP - NET_BOTTOM, 0.02f));

        // --- Posts ---
        Post(root, postMat, "Post_R", new Vector3(HALF_W, 0f, 0f));
        Post(root, postMat, "Post_L", new Vector3(-HALF_W, 0f, 0f));

        Selection.activeGameObject = root;
        EditorSceneManager.MarkSceneDirty(floor.scene);
        Debug.Log("[CourtBuilder] Badminton court built.");
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

    static GameObject Box(GameObject parent, Material mat, string name, Vector3 pos, Vector3 scale)
    {
        var g = GameObject.CreatePrimitive(PrimitiveType.Cube);
        g.name = name;
        g.transform.SetParent(parent.transform);
        g.transform.localScale = scale;
        g.transform.position = pos;
        g.GetComponent<Renderer>().sharedMaterial = mat;
        return g;
    }

    static void Post(GameObject parent, Material mat, string name, Vector3 basePos)
    {
        var g = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
        g.name = name;
        g.transform.SetParent(parent.transform);
        // Default cylinder is 2 units tall, so scale Y = POST_HEIGHT / 2.
        g.transform.localScale = new Vector3(0.06f, POST_HEIGHT / 2f, 0.06f);
        g.transform.position = new Vector3(basePos.x, POST_HEIGHT / 2f, basePos.z);
        g.GetComponent<Renderer>().sharedMaterial = mat;
    }
}
