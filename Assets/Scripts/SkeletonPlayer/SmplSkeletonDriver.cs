using UnityEngine;

namespace BadmintonVR.SkeletonPlayer
{
    /// <summary>
    /// Loads skeleton.json v2 (SMPL-24) and renders a procedural twin: a sphere
    /// per joint and a capsule per bone (bone = joint -> its parent, so the spine
    /// chain pelvis->spine1->spine2->spine3->neck->head is drawn). Plays back by
    /// advancing a frame cursor with time. Helper objects are children of THIS
    /// object; Clear() destroys them on reload (keep this object at scene root).
    /// </summary>
    public class SmplSkeletonDriver : MonoBehaviour
    {
        [Tooltip("Path under StreamingAssets, e.g. skeleton/demo.skeleton.json")]
        public string skeletonFile = "skeleton/demo.skeleton.json";
        public bool play = true;
        [Range(0.01f, 0.12f)] public float jointRadius = 0.045f;
        [Range(0.01f, 0.08f)] public float boneRadius = 0.028f;
        public Color jointColor = new Color(0.95f, 0.85f, 0.2f);
        public Color boneColor = new Color(0.2f, 0.7f, 1f);
        [Range(0f, 1f)] public float confidenceCutoff = 0.3f;

        SmplSkeletonDoc _doc;
        Transform[] _joints;
        Transform[] _bones;      // one per non-root joint (index j -> bone to parents[j])
        Material _jointMat, _boneMat;
        float _groundOffset;
        float _t;
        int _frame;

        void Start()
        {
            _doc = SmplSkeletonDoc.Load(skeletonFile);
            if (_doc != null) Build();
        }

        void Build()
        {
            Clear();
            _groundOffset = -_doc.MinY();
            _jointMat = MakeMat(jointColor);
            _boneMat = MakeMat(boneColor);

            _joints = new Transform[SmplSkeletonDoc.NumJoints];
            for (int j = 0; j < SmplSkeletonDoc.NumJoints; j++)
            {
                var s = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                s.name = $"joint_{j}_{_doc.joint_names[j]}";
                s.transform.SetParent(transform, false);
                s.transform.localScale = Vector3.one * (jointRadius * 2f);
                s.GetComponent<Renderer>().sharedMaterial = _jointMat;
                DestroyCollider(s);
                _joints[j] = s.transform;
            }

            _bones = new Transform[SmplSkeletonDoc.NumJoints];   // index 0 (root) unused
            for (int j = 1; j < SmplSkeletonDoc.NumJoints; j++)
            {
                var c = GameObject.CreatePrimitive(PrimitiveType.Capsule);
                c.name = $"bone_{j}";
                c.transform.SetParent(transform, false);
                c.GetComponent<Renderer>().sharedMaterial = _boneMat;
                DestroyCollider(c);
                _bones[j] = c.transform;
            }
            ShowFrame(0);
        }

        void Update()
        {
            if (_doc == null || _joints == null) return;
            if (play)
            {
                _t += Time.deltaTime;
                _frame = Mathf.FloorToInt(_t * _doc.Fps) % _doc.FrameCount;
            }
            ShowFrame(_frame);
        }

        void ShowFrame(int frame)
        {
            Vector3 lift = new Vector3(0, _groundOffset, 0);
            for (int j = 0; j < SmplSkeletonDoc.NumJoints; j++)
            {
                bool ok = _doc.JointConf(frame, j) >= confidenceCutoff;
                _joints[j].gameObject.SetActive(ok);
                if (ok) _joints[j].localPosition = _doc.JointPos(frame, j) + lift;
            }
            for (int j = 1; j < SmplSkeletonDoc.NumJoints; j++)
            {
                int p = _doc.parents[j];
                bool ok = _doc.JointConf(frame, j) >= confidenceCutoff &&
                          _doc.JointConf(frame, p) >= confidenceCutoff;
                _bones[j].gameObject.SetActive(ok);
                if (ok) PlaceBone(_bones[j], _doc.JointPos(frame, j) + lift, _doc.JointPos(frame, p) + lift);
            }
        }

        void PlaceBone(Transform bone, Vector3 p0, Vector3 p1)
        {
            Vector3 dir = p1 - p0;
            float len = dir.magnitude;
            bone.localPosition = (p0 + p1) * 0.5f;
            bone.localScale = new Vector3(boneRadius * 2f, Mathf.Max(len * 0.5f, 0.001f), boneRadius * 2f);
            bone.localRotation = len > 1e-5f ? Quaternion.FromToRotation(Vector3.up, dir) : Quaternion.identity;
        }

        [ContextMenu("Validate JSON (no Play)")]
        void Validate()
        {
            var d = SmplSkeletonDoc.Load(skeletonFile);
            if (d == null) { Debug.LogError("[SmplSkeleton] validate: load failed"); return; }
            Debug.Log($"[SmplSkeleton] OK: {d.FrameCount} frames, {d.joint_names.Length} joints, " +
                      $"skeleton={d.skeleton}, spine1 parent={d.parents[3]}, neck parent={d.parents[12]}");
        }

        void Clear()
        {
            for (int i = transform.childCount - 1; i >= 0; i--)
            {
                var go = transform.GetChild(i).gameObject;
                if (Application.isPlaying) Destroy(go); else DestroyImmediate(go);
            }
            _joints = null; _bones = null;
        }

        static Material MakeMat(Color col)
        {
            var shader = Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Standard");
            var m = new Material(shader);
            if (m.HasProperty("_BaseColor")) m.SetColor("_BaseColor", col); else m.color = col;
            return m;
        }

        static void DestroyCollider(GameObject go)
        {
            var col = go.GetComponent<Collider>();
            if (col != null) { if (Application.isPlaying) Destroy(col); else DestroyImmediate(col); }
        }
    }
}
