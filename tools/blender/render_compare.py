"""Render a twin from the compare scene to a video, headless.

    blender -b models/smpl/test_6_compare.blend -P tools/blender/render_compare.py

Everything after a bare `--` is passed to this script; see `parse_args`. By default it
renders the **smoothed** twin alone, which is the panel `tools/side_by_side_video.py` puts
next to the source footage. `--bodies A,B` still renders the raw and smoothed twins together
for a twin-to-twin comparison.

This script draws no text. Titles and the colour key belong to the composite, where they can
be placed against the finished frame instead of guessed at in 3D — see `side_by_side_video.py`.

Why headless
------------
The comparison scene is usually open in an interactive Blender, and a render there locks the
UI for the length of the clip. Running `blender -b` on the same .blend costs nothing but a
second process and leaves the live session alone. It also makes the render reproducible:
nothing about the output depends on where the user happened to leave the viewport, the
timeline, or the N-panel toggles.

The one thing the saved file does NOT contain is the racket. `racket_viewer.build()` writes
it from `data/skeleton/test_6.skeleton_racket.json` on every run and never needs saving, so
this script simply calls it — which also means the render always reflects the current lift,
not whatever was in the file when it was last saved. `--no-racket` skips it.

Framing
-------
The camera is computed, not authored. Every rendered body is sampled over every frame (bone
heads plus the racket's bounding box), and the camera is pushed back along the players' mean
facing direction until every sampled point projects inside the frame with a margin. A
hand-placed camera would silently crop the smash the moment the clip, the body offset, or the
racket length changed.

`--azimuth` swings the camera around the subject, `--elevation` raises it; both are relative
to that measured facing direction, so 0/0 is a true front view of whatever the player is doing.

Colour
------
The body is **blue** and only the racket uses green/amber/red. Those three are the racket's
confidence (measured / roll guessed / forearm prior, keyframed by `racket_viewer`), and while
the body was green too, the colour key had one colour standing for two unrelated things.
"""

import argparse
import json
import math
import pathlib
import sys

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

# Linear RGB, matching `racket_viewer`'s palette. The colour key in side_by_side_video.py
# converts these same values to sRGB for its swatches -- keep the two in step.
BODY_COLOUR = (0.42, 0.58, 0.85, 1.0)
# Workbench "Object" mode reads object.color and ignores materials, so the node colours
# have to be set here even though twin_compare gives the geometry a material too.
JOINT_COLOUR = (1.00, 0.95, 0.55, 1.0)      # warm cream: reads over blue skin and dark floor
BONE_COLOUR = (0.98, 0.98, 1.00, 1.0)

BODIES = {
    "A": {"armature": "SMPL-male.001", "mesh": "SMPL-mesh-male.001", "action": "act_raw",
          "collection": "A_raw_left", "joints": "A_joints_left", "bones": "A_bones_left",
          "racket_joints": "A_racket_joints"},
    "B": {"armature": "SMPL-male", "mesh": "SMPL-mesh-male", "action": "act_smooth",
          "collection": "B_smooth_right", "joints": "B_joints_right", "bones": "B_bones_right",
          "racket_joints": "B_racket_joints"},
}

# Blender bone name -> (SMPL index, the name skeleton.json uses). The rig orders its bones
# down each limb; the SMPL contract interleaves left/right and threads the spine between
# them, so the two orders genuinely differ and this table is not decoration.
SMPL_BONE_ORDER = [
    ("Pelvis", 0, "pelvis"), ("L_Hip", 1, "left_hip"), ("R_Hip", 2, "right_hip"),
    ("Spine1", 3, "spine1"), ("L_Knee", 4, "left_knee"), ("R_Knee", 5, "right_knee"),
    ("Spine2", 6, "spine2"), ("L_Ankle", 7, "left_ankle"), ("R_Ankle", 8, "right_ankle"),
    ("Spine3", 9, "spine3"), ("L_Foot", 10, "left_foot"), ("R_Foot", 11, "right_foot"),
    ("Neck", 12, "neck"), ("L_Collar", 13, "left_collar"), ("R_Collar", 14, "right_collar"),
    ("Head", 15, "head"), ("L_Shoulder", 16, "left_shoulder"),
    ("R_Shoulder", 17, "right_shoulder"), ("L_Elbow", 18, "left_elbow"),
    ("R_Elbow", 19, "right_elbow"), ("L_Wrist", 20, "left_wrist"),
    ("R_Wrist", 21, "right_wrist"), ("L_Hand", 22, "left_hand"), ("R_Hand", 23, "right_hand"),
]

OVERLAY_COLLECTION = "Render_Overlay"
CAMERA_NAME = "RenderCam_Compare"
FLOOR_COLOUR = (0.16, 0.17, 0.19, 1.0)
DEFAULT_OUT = "data/render/test_6_twin.mp4"


def parse_args(argv):
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser(prog="render_compare")
    p.add_argument("--out", default=DEFAULT_OUT, help="output path, relative to the repo root")
    p.add_argument("--bodies", default="B",
                   help="comma-separated: B = smoothed twin (default), A = raw, A,B = both")
    p.add_argument("--res", default="1280x720", help="WIDTHxHEIGHT")
    p.add_argument("--azimuth", type=float, default=0.0,
                   help="degrees around the subject from the player's facing direction")
    p.add_argument("--elevation", type=float, default=8.0, help="degrees above eye level")
    p.add_argument("--margin", type=float, default=0.07,
                   help="fraction of the frame kept empty around the action")
    p.add_argument("--still", type=int, default=None,
                   help="render this single frame as a PNG instead of the animation")
    p.add_argument("--no-racket", action="store_true", help="skip the racket rebuild")
    p.add_argument("--joints", action="store_true", help="also show the 24 joint spheres")
    p.add_argument("--bones", action="store_true",
                   help="also show the SMPL bone arrows (parent joint -> child joint)")
    p.add_argument("--no-mesh", action="store_true",
                   help="hide the body mesh: nodes and bones alone, over the floor")
    p.add_argument("--xray", type=float, default=None,
                   help="make everything translucent (0-1); the only way nodes read "
                        "through a solid mesh")
    p.add_argument("--no-floor", action="store_true", help="skip the ground plane")
    p.add_argument("--samples", type=int, default=1,
                   help="frame stride when measuring the framing (1 = every frame)")
    p.add_argument("--rest", action="store_true",
                   help="show the armature's REST pose instead of the animation "
                        "(the clearest layout for a labelled reference diagram)")
    p.add_argument("--dump-joints", default=None,
                   help="write the 24 joints' pixel positions for --still to this json, "
                        "for an annotator to label")
    p.add_argument("--save-camera", default=None,
                   help="write the solved framing to this json (relative to the repo root)")
    p.add_argument("--camera", default=None,
                   help="reuse a --save-camera json instead of solving; keeps sibling "
                        "panels at one scale")
    return p.parse_args(args)


def selected_bodies(spec):
    keys = [k.strip().upper() for k in spec.split(",") if k.strip()]
    unknown = [k for k in keys if k not in BODIES]
    if unknown or not keys:
        raise RuntimeError(f"--bodies wants A and/or B, got {spec!r}")
    return keys


def repo_root():
    blend = pathlib.Path(bpy.data.filepath)
    if not blend.parts:
        raise RuntimeError("open the .blend first -- paths are resolved relative to it")
    return blend.parent.parent.parent


def build_racket():
    """Rebuild both rackets from the lift JSON. Returns the build summary, or None."""
    here = str(pathlib.Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import racket_viewer
    return racket_viewer.build()


def drop_racket():
    """Delete any racket the .blend was saved with.

    Skipping the rebuild is not enough: a scene saved after an interactive `racket_viewer`
    run still carries `Racket_A`/`Racket_B`, and their keyframed `hide_render` puts them
    back on screen the moment the render advances. Removing the objects is the only state
    the animation cannot undo, and costs nothing -- this process never saves the file.
    """
    removed = [o.name for o in list(bpy.data.objects) if o.name.startswith("Racket_")]
    for name in removed:
        bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)
    return removed


def layer_collection(name, root=None):
    """The view-layer node for a collection, searched depth-first. None if absent."""
    root = root or bpy.context.view_layer.layer_collection
    if root.name == name:
        return root
    for child in root.children:
        found = layer_collection(name, child)
        if found is not None:
            return found
    return None


def ensure_nodes():
    """Build the joint spheres and bone arrows if this .blend predates them.

    `twin_compare` is the module that owns both, and it is idempotent, so calling it here
    costs nothing when the collections already exist and saves the caller from having to
    open the scene interactively once before the first render.
    """
    here = str(pathlib.Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import twin_compare
    for key, spec in BODIES.items():
        if bpy.data.collections.get(spec["joints"]) is None:
            twin_compare.build_joints(key)
        if bpy.data.collections.get(spec["bones"]) is None:
            twin_compare.build_bones(key)


def set_visibility(keys, show_joints, show_bones=False, show_mesh=True):
    """Pin exactly what renders: the chosen bodies and their rackets, nothing else.

    Unselected bodies are **excluded from the view layer**, not merely hidden. The racket
    keyframes its own `hide_render` on every frame (it hides itself where there is no racket
    to draw), so any value set here is overwritten the moment the render advances a frame —
    the unwanted racket sails through the render on its own animation. Exclusion is the one
    switch the action cannot reach. Excluding rather than deleting keeps a single .blend
    serving both the single-twin panel and the twin-to-twin comparison.
    """
    for key, spec in BODIES.items():
        on = key in keys
        for coll_name in (spec["collection"], spec["joints"], spec["bones"],
                          spec["racket_joints"]):
            node = layer_collection(coll_name)
            if node is not None:
                node.exclude = not on
        if not on:
            continue
        arm = bpy.data.objects.get(spec["armature"])
        mesh = bpy.data.objects.get(spec["mesh"])
        if arm is None or mesh is None:
            raise RuntimeError(f"{spec['armature']}/{spec['mesh']} missing -- "
                               "is this test_6_compare.blend?")
        arm.hide_render = True                  # armature bones never render anyway
        mesh.hide_render = not show_mesh
        mesh.color = BODY_COLOUR                # Workbench "Object" mode reads this

        action = bpy.data.actions.get(spec["action"])
        if action is None:
            raise RuntimeError(f"action {spec['action']} missing -- "
                               "the compare scene was never built in this file")
        ad = arm.animation_data or arm.animation_data_create()
        ad.action = action
        # Slotted actions (4.4+): assigning the action alone leaves it driving nothing.
        if hasattr(ad, "action_slot") and getattr(ad, "action_slot", None) is None:
            slots = getattr(action, "slots", None)
            if slots:
                ad.action_slot = slots[0]

        # The racket's own spheres duplicate what the racket already shows; the body's 24
        # joint spheres and its bone arrows are opt-in.
        for coll_name, visible, colour in (
                (spec["joints"], show_joints, JOINT_COLOUR),
                (spec["bones"], show_bones, BONE_COLOUR),
                (spec["racket_joints"], False, None)):
            coll = bpy.data.collections.get(coll_name)
            for o in (coll.objects if coll else []):
                o.hide_render = not visible
                if colour is not None:
                    o.color = colour


def overlay_collection(reset=False):
    """The camera and floor this script owns. `reset=True` empties it first.

    Only main() resets, and only once: the helpers below all add to the same collection, so
    a second reset partway through would delete what an earlier step just built.
    """
    coll = bpy.data.collections.get(OVERLAY_COLLECTION)
    if coll is None:
        coll = bpy.data.collections.new(OVERLAY_COLLECTION)
        bpy.context.scene.collection.children.link(coll)
    if reset:
        for o in list(coll.objects):
            bpy.data.objects.remove(o, do_unlink=True)
    return coll


def sample_scene(keys, stride):
    """(points, facing) over the whole timeline, in world space.

    Sampling every frame is cheap next to the render itself and is the only way to know the
    extent of a swing: at the top of the smash the racket head is a metre above the head that
    a rest-pose bounding box would report.
    """
    scene = bpy.context.scene
    original = scene.frame_current
    points, forwards = [], []
    frames = range(scene.frame_start, scene.frame_end + 1, max(1, stride))
    for f in frames:
        scene.frame_set(f)
        bpy.context.view_layer.update()
        for key in keys:
            arm = bpy.data.objects[BODIES[key]["armature"]]
            mw = arm.matrix_world
            heads = {b.name: mw @ b.head for b in arm.pose.bones}
            points.extend(heads.values())
            left, right = heads.get("L_Hip"), heads.get("R_Hip")
            if left is not None and right is not None:
                side = (left - right)
                side.z = 0.0
                if side.length > 1e-6:
                    # Right-handed: forward = left x up.
                    forwards.append(side.normalized().cross(Vector((0.0, 0.0, 1.0))))
            ob = bpy.data.objects.get(f"Racket_{key}")
            if ob is not None and not ob.hide_render:
                points.extend(ob.matrix_world @ Vector(c) for c in ob.bound_box)
    scene.frame_set(original)
    bpy.context.view_layer.update()

    facing = Vector((0.0, 0.0, 0.0))
    for f in forwards:
        facing += f
    if facing.length < 1e-6:
        facing = Vector((0.0, -1.0, 0.0))
    return points, facing.normalized()


def bounds(points):
    lo = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    hi = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    return lo, hi


def place_camera(points, facing, azimuth_deg, elevation_deg, margin):
    """Aim at the centre of the action, then back off until nothing is cropped.

    The distance is solved by projection rather than by a trigonometric estimate: the point
    cloud of a swing is wide and shallow, so a bounding-sphere formula overshoots badly and a
    bounding-box one undershoots at the corners of the frame.
    """
    scene = bpy.context.scene
    lo, hi = bounds(points)
    centre = (lo + hi) / 2.0

    cam_data = bpy.data.cameras.get(CAMERA_NAME) or bpy.data.cameras.new(CAMERA_NAME)
    cam_data.lens = 50.0
    cam = bpy.data.objects.get(CAMERA_NAME)
    if cam is None:
        cam = bpy.data.objects.new(CAMERA_NAME, cam_data)
        overlay_collection().objects.link(cam)
    else:
        cam.data = cam_data

    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    direction = Vector((facing.x * math.cos(az) - facing.y * math.sin(az),
                        facing.x * math.sin(az) + facing.y * math.cos(az),
                        0.0)).normalized()
    direction = Vector((direction.x * math.cos(el), direction.y * math.cos(el), math.sin(el)))

    distance = max((hi - lo).length, 1.0)
    for _ in range(24):
        cam.location = centre + direction * distance
        cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()
        bpy.context.view_layer.update()
        worst = 0.0
        for p in points:
            ndc = world_to_camera_view(scene, cam, p)
            worst = max(worst, abs(ndc.x - 0.5) * 2.0, abs(ndc.y - 0.5) * 2.0)
        target = 1.0 - margin
        if abs(worst - target) < 0.01:
            break
        distance *= max(0.5, min(2.0, worst / target))
    scene.camera = cam
    return cam, centre


def set_rest_pose(keys, on):
    """Swap the armatures between REST and POSE. The node geometry follows for free.

    The joint spheres and bone arrows are driven by constraints against the pose bones
    rather than by keyframes, so they land on the rest skeleton with nothing to rebuild.
    """
    for key in keys:
        bpy.data.objects[BODIES[key]["armature"]].data.pose_position = "REST" if on else "POSE"
    bpy.context.view_layer.update()


def dump_joints(path, key, cam):
    """Where each SMPL joint lands in the rendered image, in pixels, top-left origin.

    Projected here rather than guessed by the annotator: only Blender knows the solved
    camera, and `world_to_camera_view` is the same projection the render itself used, so a
    label can never drift off its node.
    """
    scene = bpy.context.scene
    arm = bpy.data.objects[BODIES[key]["armature"]]
    width = scene.render.resolution_x
    height = scene.render.resolution_y
    out = []
    for bone_name, index, smpl_name in SMPL_BONE_ORDER:
        bone = arm.pose.bones.get(bone_name)
        if bone is None:
            raise RuntimeError(f"bone {bone_name} missing from {arm.name}")
        world = arm.matrix_world @ bone.head
        ndc = world_to_camera_view(scene, cam, world)
        out.append({"index": index, "name": smpl_name, "bone": bone_name,
                    "x": ndc.x * width, "y": (1.0 - ndc.y) * height,
                    "world": [world.x, world.y, world.z]})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"resolution": [width, height], "joints": out}, indent=2),
                    encoding="utf-8")
    print(f"render_compare: joints -> {path}")


def body_origin(key):
    return bpy.data.objects[BODIES[key]["armature"]].matrix_world.translation.copy()


def camera_state(cam, centre, key):
    """The solved framing, stored RELATIVE to the body it was solved for.

    The two twins stand 1.4 m apart in the scene, so an absolute camera reused on the
    other body would frame empty floor. Storing the offset lets a sibling panel inherit
    the distance and lens -- which is what keeps the twins the same size across a grid --
    while still centring on its own body.
    """
    origin = body_origin(key)
    return {"lens": cam.data.lens,
            "location_local": list(cam.location - origin),
            "centre_local": list(Vector(centre) - origin)}


def apply_camera(state, key):
    """Rebuild a camera from `camera_state`, re-anchored on this body."""
    origin = body_origin(key)
    cam_data = bpy.data.cameras.get(CAMERA_NAME) or bpy.data.cameras.new(CAMERA_NAME)
    cam_data.lens = state["lens"]
    cam = bpy.data.objects.get(CAMERA_NAME)
    if cam is None:
        cam = bpy.data.objects.new(CAMERA_NAME, cam_data)
        overlay_collection().objects.link(cam)
    else:
        cam.data = cam_data
    centre = origin + Vector(state["centre_local"])
    cam.location = origin + Vector(state["location_local"])
    cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.view_layer.update()
    bpy.context.scene.camera = cam
    return cam, centre


def add_floor(lo, hi):
    """A plane at the lowest foot, so the render has a ground to read motion against."""
    coll = bpy.data.collections[OVERLAY_COLLECTION]
    mesh = bpy.data.meshes.new("compare_floor")
    span = max((hi - lo).length, 4.0)
    verts = [(-span, -span, 0.0), (span, -span, 0.0), (span, span, 0.0), (-span, span, 0.0)]
    mesh.from_pydata(verts, [], [(0, 1, 2, 3)])
    mesh.update()
    ob = bpy.data.objects.new("CompareFloor", mesh)
    coll.objects.link(ob)
    ob.location = ((lo.x + hi.x) / 2.0, (lo.y + hi.y) / 2.0, lo.z)
    ob.color = FLOOR_COLOUR


def configure_render(width, height, out_path, still, xray=None):
    """Workbench, not EEVEE: this render is a measurement read-out, not a beauty shot.

    Workbench's "Object" colour mode is also what makes the racket's confidence colours
    (green / amber / red, keyframed by racket_viewer) survive into the render at all.
    """
    scene = bpy.context.scene
    r = scene.render
    r.engine = "BLENDER_WORKBENCH"
    r.resolution_x, r.resolution_y = width, height
    r.resolution_percentage = 100
    r.film_transparent = False

    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "OBJECT"
    # Shadows off: with a body, a racket and a wide floor they overlap into silhouettes that
    # read as extra limbs. Cavity gives the depth instead.
    shading.show_shadows = False
    shading.show_cavity = True
    # X-ray is Workbench's only transparency and it is global -- there is no per-object
    # alpha to make just the skin see-through. Turning it on is what lets the joints and
    # bone arrows read at all in a panel that also renders the mesh; without it they are
    # sealed inside the body and the panel is indistinguishable from a plain mesh render.
    shading.show_xray = xray is not None
    if xray is not None:
        shading.xray_alpha = xray
    scene.display.render_aa = "8"
    r.use_stamp = False              # no burn-in: the composite owns all text

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Blender 5.x gates the video formats behind `media_type`: setting file_format to FFMPEG
    # while it still says IMAGE raises "enum FFMPEG not found", which reads like the build
    # has no ffmpeg at all. Older builds have no media_type and take FFMPEG directly.
    if hasattr(r.image_settings, "media_type"):
        r.image_settings.media_type = "IMAGE" if still is not None else "VIDEO"
    if still is not None:
        r.image_settings.file_format = "PNG"
        r.filepath = str(out_path)
        scene.frame_set(still)
    else:
        r.image_settings.file_format = "FFMPEG"
        r.ffmpeg.format = "MPEG4"
        r.ffmpeg.codec = "H264"
        r.ffmpeg.constant_rate_factor = "HIGH"
        r.ffmpeg.ffmpeg_preset = "GOOD"
        r.filepath = str(out_path)


def main():
    args = parse_args(sys.argv)
    keys = selected_bodies(args.bodies)
    width, height = (int(v) for v in args.res.lower().split("x"))
    out = repo_root() / args.out

    # Before anything projects: `world_to_camera_view` reads the scene's aspect ratio, so
    # both the framing solve and the joint dump have to see the resolution we will render at,
    # not whatever the .blend was saved with.
    bpy.context.scene.render.resolution_x = width
    bpy.context.scene.render.resolution_y = height

    summary = None
    if args.no_racket:
        dropped = drop_racket()
        if dropped:
            print(f"render_compare: dropped saved racket {dropped}")
    else:
        summary = build_racket()
    ensure_nodes()
    set_visibility(keys, args.joints, args.bones, not args.no_mesh)
    set_rest_pose(keys, args.rest)
    overlay_collection(reset=True)
    # Sampled even when the camera is inherited: the floor still needs the extent.
    points, facing = sample_scene(keys, args.samples)
    lo, hi = bounds(points)
    if args.camera:
        state = json.loads((repo_root() / args.camera).read_text(encoding="utf-8"))
        cam, centre = apply_camera(state, keys[0])
    else:
        cam, centre = place_camera(points, facing, args.azimuth, args.elevation, args.margin)
    if args.save_camera:
        path = repo_root() / args.save_camera
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(camera_state(cam, centre, keys[0]), indent=2),
                        encoding="utf-8")
        print(f"render_compare: camera -> {path}")
    if not args.no_floor:
        add_floor(lo, hi)
    configure_render(width, height, out, args.still, args.xray)
    if args.dump_joints:
        dump_joints(repo_root() / args.dump_joints, keys[0], cam)

    scene = bpy.context.scene
    print(f"render_compare: bodies {','.join(keys)}, {len(points)} sample points, "
          f"camera at {tuple(round(v, 2) for v in cam.location)} "
          f"looking at {tuple(round(v, 2) for v in centre)}")
    if summary:
        print("render_compare: racket", summary["bodies"])
    print(f"render_compare: frames {scene.frame_start}-{scene.frame_end} @ {scene.render.fps} fps"
          if args.still is None else f"render_compare: still frame {args.still}")

    bpy.ops.render.render(animation=args.still is None, write_still=args.still is not None)
    print(f"render_compare: wrote {out}")


if __name__ == "__main__":
    main()
