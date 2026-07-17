using UnityEngine;

namespace BadmintonVR.SkeletonPlayer
{
    /// <summary>
    /// Builds and updates the stick-figure "simple human model": a sphere per
    /// joint and a capsule per bone, driven from a SkeletonDoc frame.
    /// </summary>
    public class SkeletonRenderer : MonoBehaviour
    {
        [Range(0.01f, 0.12f)] public float jointRadius = 0.045f;
        [Range(0.01f, 0.08f)] public float boneRadius = 0.028f;
        public Color jointColor = new Color(0.95f, 0.85f, 0.2f);
        public Color boneColor = new Color(0.2f, 0.7f, 1f);
        [Tooltip("Joints below this confidence are hidden.")]
        [Range(0f, 1f)] public float confidenceCutoff = 0.3f;

        Transform[] _joints;
        Transform[] _bones;
        Material _jointMat, _boneMat;
        float _groundOffset;

        public void Build(SkeletonDoc doc)
        {
            Clear();
            _groundOffset = -doc.MinY(); // lift so lowest joint sits on the floor (y=0)

            _jointMat = MakeMat(jointColor);
            _boneMat = MakeMat(boneColor);

            _joints = new Transform[SkeletonDoc.NumJoints];
            for (int j = 0; j < SkeletonDoc.NumJoints; j++)
            {
                var s = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                s.name = $"joint_{j}";
                s.transform.SetParent(transform, false);
                s.transform.localScale = Vector3.one * (jointRadius * 2f);
                s.GetComponent<Renderer>().sharedMaterial = _jointMat;
                DestroyCollider(s);
                _joints[j] = s.transform;
            }

            int nBones = PoseTopology.Bones.GetLength(0);
            _bones = new Transform[nBones];
            for (int b = 0; b < nBones; b++)
            {
                var c = GameObject.CreatePrimitive(PrimitiveType.Capsule);
                c.name = $"bone_{b}";
                c.transform.SetParent(transform, false);
                c.GetComponent<Renderer>().sharedMaterial = _boneMat;
                DestroyCollider(c);
                _bones[b] = c.transform;
            }
        }

        public void ShowFrame(SkeletonDoc doc, int frame)
        {
            if (_joints == null) return;
            Vector3 lift = new Vector3(0, _groundOffset, 0);

            for (int j = 0; j < SkeletonDoc.NumJoints; j++)
            {
                bool ok = doc.JointConf(frame, j) >= confidenceCutoff;
                _joints[j].gameObject.SetActive(ok);
                if (ok) _joints[j].localPosition = doc.JointPos(frame, j) + lift;
            }

            int nBones = PoseTopology.Bones.GetLength(0);
            for (int b = 0; b < nBones; b++)
            {
                int a = PoseTopology.Bones[b, 0], c = PoseTopology.Bones[b, 1];
                bool ok = doc.JointConf(frame, a) >= confidenceCutoff &&
                          doc.JointConf(frame, c) >= confidenceCutoff;
                _bones[b].gameObject.SetActive(ok);
                if (!ok) continue;
                PlaceBone(_bones[b], doc.JointPos(frame, a) + lift, doc.JointPos(frame, c) + lift);
            }
        }

        /// <summary>
        /// Track B: override the figure with an externally DRIVEN pose given in
        /// WORLD space (TwinDriver). Call after ShowFrame each frame to replace
        /// the raw MediaPipe placement.
        /// </summary>
        public void ShowPoseWorld(Vector3[] world, bool[] visible)
        {
            if (_joints == null || world == null) return;

            for (int j = 0; j < SkeletonDoc.NumJoints; j++)
            {
                bool ok = visible == null || visible[j];
                _joints[j].gameObject.SetActive(ok);
                if (ok) _joints[j].position = world[j];
            }

            int nBones = PoseTopology.Bones.GetLength(0);
            for (int b = 0; b < nBones; b++)
            {
                int a = PoseTopology.Bones[b, 0], c = PoseTopology.Bones[b, 1];
                bool ok = (visible == null || (visible[a] && visible[c]));
                _bones[b].gameObject.SetActive(ok);
                if (!ok) continue;
                PlaceBoneWorld(_bones[b], world[a], world[c]);
            }
        }

        void PlaceBoneWorld(Transform bone, Vector3 p0, Vector3 p1)
        {
            Vector3 mid = (p0 + p1) * 0.5f;
            Vector3 dir = p1 - p0;
            float len = dir.magnitude;
            bone.position = mid;
            bone.localScale = new Vector3(boneRadius * 2f, Mathf.Max(len * 0.5f, 0.001f), boneRadius * 2f);
            bone.rotation = len > 1e-5f ? Quaternion.FromToRotation(Vector3.up, dir) : Quaternion.identity;
        }

        void PlaceBone(Transform bone, Vector3 p0, Vector3 p1)
        {
            Vector3 mid = (p0 + p1) * 0.5f;
            Vector3 dir = p1 - p0;
            float len = dir.magnitude;
            bone.localPosition = mid;
            // Default capsule is 2 units tall along local Y; scale Y by len/2.
            bone.localScale = new Vector3(boneRadius * 2f, Mathf.Max(len * 0.5f, 0.001f), boneRadius * 2f);
            bone.localRotation = len > 1e-5f ? Quaternion.FromToRotation(Vector3.up, dir) : Quaternion.identity;
        }

        public void Clear()
        {
            for (int i = transform.childCount - 1; i >= 0; i--)
            {
                var go = transform.GetChild(i).gameObject;
                if (Application.isPlaying) Destroy(go); else DestroyImmediate(go);
            }
            _joints = null;
            _bones = null;
        }

        static Material MakeMat(Color col)
        {
            var shader = Shader.Find("Universal Render Pipeline/Lit");
            if (shader == null) shader = Shader.Find("Standard");
            var m = new Material(shader);
            if (m.HasProperty("_BaseColor")) m.SetColor("_BaseColor", col);
            else m.color = col;
            return m;
        }

        static void DestroyCollider(GameObject go)
        {
            var col = go.GetComponent<Collider>();
            if (col != null)
            {
                if (Application.isPlaying) Destroy(col); else DestroyImmediate(col);
            }
        }
    }
}
