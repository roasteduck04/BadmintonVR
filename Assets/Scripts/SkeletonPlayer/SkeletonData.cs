using System;
using System.IO;
using UnityEngine;

namespace BadmintonVR.SkeletonPlayer
{
    // Mirrors skeleton.json (schema v1). Only the fields Unity needs are declared;
    // JsonUtility ignores the rest. Joints are a flat float array (132 = 33 x 4).

    [Serializable]
    public class SkeletonSource { public string type; public float fps; public int[] resolution; }

    [Serializable]
    public class SkeletonFrame
    {
        public int frame_id;
        public float time;
        public float[] joints_flat; // 33 * [x, y, z, confidence]
    }

    [Serializable]
    public class SkeletonDoc
    {
        public string schema_version;
        public string video_id;
        public SkeletonSource source;
        public string coordinate_system;
        public string[] joint_names;
        public SkeletonFrame[] frames;

        public const int NumJoints = 33;
        public const int Stride = 4; // x, y, z, confidence

        public int FrameCount => frames != null ? frames.Length : 0;
        public float Fps => (source != null && source.fps > 1f) ? source.fps : 30f;
        public float Duration => FrameCount > 0 ? frames[FrameCount - 1].time : 0f;

        public Vector3 JointPos(int frame, int joint)
        {
            int b = joint * Stride;
            var f = frames[frame].joints_flat;
            return new Vector3(f[b], f[b + 1], f[b + 2]);
        }

        public float JointConf(int frame, int joint) => frames[frame].joints_flat[joint * Stride + 3];

        /// <summary>Lowest joint Y across the whole clip — used to stand the twin on the floor.</summary>
        public float MinY()
        {
            float min = float.MaxValue;
            for (int i = 0; i < FrameCount; i++)
                for (int j = 0; j < NumJoints; j++)
                    min = Mathf.Min(min, frames[i].joints_flat[j * Stride + 1]);
            return min == float.MaxValue ? 0f : min;
        }

        public static SkeletonDoc Load(string streamingAssetsRelativePath)
        {
            string path = Path.Combine(Application.streamingAssetsPath, streamingAssetsRelativePath);
            if (!File.Exists(path))
            {
                Debug.LogError($"[SkeletonPlayer] file not found: {path}");
                return null;
            }
            var doc = JsonUtility.FromJson<SkeletonDoc>(File.ReadAllText(path));
            if (doc == null || doc.FrameCount == 0)
            {
                Debug.LogError($"[SkeletonPlayer] failed to parse or empty: {path}");
                return null;
            }
            return doc;
        }
    }

    // MediaPipe 33-landmark bone connections (index pairs) for drawing the stick figure.
    public static class PoseTopology
    {
        public static readonly int[,] Bones =
        {
            {11,12},{11,23},{12,24},{23,24},        // torso
            {11,13},{13,15},{12,14},{14,16},        // arms
            {15,17},{15,19},{15,21},{16,18},{16,20},{16,22}, // hands
            {23,25},{25,27},{24,26},{26,28},        // legs
            {27,29},{29,31},{27,31},{28,30},{30,32},{28,32}, // feet
            {0,11},{0,12},                          // neck-ish (nose to shoulders)
        };
    }
}
