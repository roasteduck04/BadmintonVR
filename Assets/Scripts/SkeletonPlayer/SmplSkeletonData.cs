using System;
using System.IO;
using UnityEngine;

namespace BadmintonVR.SkeletonPlayer
{
    // Mirrors skeleton.json v2 (SMPL-24). JsonUtility ignores fields we don't
    // declare (betas, per-frame smpl block). Joints are a flat float array
    // (96 = 24 x 4). Bone connectivity comes from `parents`, not a hard-coded table.
    [Serializable]
    public class SmplSource { public string type; public float fps; }

    [Serializable]
    public class SmplFrame
    {
        public int frame_id;
        public float time;
        public float[] joints_flat;   // 24 * [x, y, z, confidence]
        public float[] root_world;    // [x, y, z]
    }

    [Serializable]
    public class SmplSkeletonDoc
    {
        public string schema_version;
        public string video_id;
        public SmplSource source;
        public string skeleton;       // "smpl-24"
        public string[] joint_names;  // 24
        public int[] parents;         // 24, parent index or -1 for root
        public SmplFrame[] frames;

        public const int NumJoints = 24;
        public const int Stride = 4;

        public int FrameCount => frames != null ? frames.Length : 0;
        public float Fps => (source != null && source.fps > 1f) ? source.fps : 30f;

        public Vector3 JointPos(int frame, int joint)
        {
            int b = joint * Stride;
            var f = frames[frame].joints_flat;
            return new Vector3(f[b], f[b + 1], f[b + 2]);
        }

        public float JointConf(int frame, int joint) => frames[frame].joints_flat[joint * Stride + 3];

        public float MinY()
        {
            float min = float.MaxValue;
            for (int i = 0; i < FrameCount; i++)
                for (int j = 0; j < NumJoints; j++)
                    min = Mathf.Min(min, frames[i].joints_flat[j * Stride + 1]);
            return min == float.MaxValue ? 0f : min;
        }

        public static SmplSkeletonDoc Load(string streamingAssetsRelativePath)
        {
            string path = Path.Combine(Application.streamingAssetsPath, streamingAssetsRelativePath);
            if (!File.Exists(path))
            {
                Debug.LogError($"[SmplSkeleton] file not found: {path}");
                return null;
            }
            var doc = JsonUtility.FromJson<SmplSkeletonDoc>(File.ReadAllText(path));
            if (doc == null || doc.FrameCount == 0 || doc.parents == null || doc.parents.Length != NumJoints)
            {
                Debug.LogError($"[SmplSkeleton] failed to parse / wrong topology: {path}");
                return null;
            }
            return doc;
        }
    }
}
