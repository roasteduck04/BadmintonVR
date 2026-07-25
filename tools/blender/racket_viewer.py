"""Stage 3 — put the lifted racket on the Blender twin(s) in test_6_compare.blend.

Run it the same way as `twin_compare.py`: open the .blend, Scripting workspace, Alt+P.
Idempotent — re-running rebuilds the rackets and re-registers the panel.
Panel: View3D > N > **"Racket"** tab.

Getting from skeleton.json into this scene
------------------------------------------
The racket lives in `<id>.skeleton_racket.json` in **Unity** space, but the Blender bodies
were never built from that file — the SMPL add-on animates them straight from the npz, and
the twins play **in place** (their pelvis is pinned at the origin; only the pose moves).
So there is no single world transform between the two, and two things have to be right:

1. **Undo the Unity Y-flip first.** `skeleton.json` has been through
   `WORLD_TO_UNITY = diag(1,-1,1)`, which is a *reflection* — it turns the body into its
   mirror image, where left and right are swapped. Fitting labelled joint to labelled joint
   without undoing it makes Procrustes solve for a mirror and the residual explodes
   (measured on test_6: 0.21 m vs 0.026 m). Multiplying by diag(1,-1,1) again — it is its
   own inverse — puts the joints back in ROMP camera space, where the fit is a proper
   rotation with det = +1.
2. **Fit per frame, not once.** Because the twins play in place while the JSON carries the
   real root translation, a global fit cannot work. A per-frame Procrustes of the 24 SMPL
   joints onto the 24 bone heads absorbs that automatically, and its residual doubles as a
   live quality read-out.

The residual that remains (~2.6 cm raw / ~3.1 cm smooth on test_6) is the SMPL add-on's
template body against ROMP's regressed joints — a shape difference, not a bug. Limb lengths
agree to 3-7%. The racket therefore sits within a few cm of truth, which is the honest
precision of this viewer.

What gets built, per body
-------------------------
- **A racket**: shaft cylinder plus a filled elliptical bed, placed each frame from the
  three racket joints (`racket_grip` 24, `racket_head` 25, `racket_side` 26). The bed is a
  face, so its orientation is obvious on sight — that is the whole point of Stage 2b.
- **Two actions**, `act_racket_<key>_raw` and `_smooth`, so the Style toggle switches the
  racket exactly the way the body's Style toggle switches `act_raw`/`act_smooth`. Until this
  existed, the "smooth" twin carried a raw, jittery racket and the comparison was only half
  honest. Smoothing keeps the racket rigid (see `tools/racket_smoothing.py`) and is
  **zero-phase**, so the racket does not lag the hand during a smash.
- **Three joint spheres** (grip / head / side), parented to the racket so they need no
  keyframes of their own. They live in their own collection rather than the body's
  `*_joints` one, because `twin_compare.build_joints()` clears that collection on every run
  and would delete them.

**Colour carries confidence, because most frames do not have a measured racket.** Green =
both position and roll measured; amber = position measured but roll guessed; red = position
itself is the forearm prior. On test_6 that is 33% / 11% / 56% — if the viewer drew one
uniform colour it would imply three times more real data than exists.
"""

import json
import math
import pathlib
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

SKELETON_JSON = "data/skeleton/test_6.skeleton_racket.json"

# key -> (body collection, armature object, racket-joints collection)
BODIES = {
    "A": ("A_raw_left", "SMPL-male.001", "A_racket_joints"),
    "B": ("B_smooth_right", "SMPL-male", "B_racket_joints"),
}
DEFAULT_STYLE = {"A": "RAW", "B": "SMOOTH"}      # mirrors twin_compare's left/right split

# SMPL-24 order (skeleton.json `joint_names`) -> SMPL add-on bone names
BONES = ["Pelvis", "L_Hip", "R_Hip", "Spine1", "L_Knee", "R_Knee", "Spine2", "L_Ankle",
         "R_Ankle", "Spine3", "L_Foot", "R_Foot", "Neck", "L_Collar", "R_Collar", "Head",
         "L_Shoulder", "R_Shoulder", "L_Elbow", "R_Elbow", "L_Wrist", "R_Wrist",
         "L_Hand", "R_Hand"]

UNFLIP = np.array([1.0, -1.0, 1.0])      # inverse of WORLD_TO_UNITY (self-inverse)

SHAFT_RADIUS = 0.007
BED_SEGMENTS = 28
JOINT_RADIUS = 0.022
COLOUR_FULL = (0.15, 0.85, 0.25, 1.0)    # position + roll measured
COLOUR_NO_ROLL = (1.0, 0.65, 0.05, 1.0)  # position measured, roll guessed
COLOUR_PRIOR = (0.90, 0.15, 0.15, 1.0)   # position is the forearm prior
JOINT_COLOURS = {"grip": (0.20, 0.45, 1.0, 1.0),
                 "head": (0.15, 0.90, 0.30, 1.0),
                 "side": (1.00, 0.20, 0.85, 1.0)}


# ---------------------------------------------------------------------------- data

def repo_root():
    """The .blend lives at <root>/models/smpl/, so the repo root is two levels up."""
    blend = pathlib.Path(bpy.data.filepath)
    if not blend.parts:
        raise RuntimeError("save the .blend first -- the JSON path is resolved relative to it")
    return blend.parent.parent.parent


def import_smoothing():
    """`tools/racket_smoothing.py` is numpy-only precisely so it can be imported here."""
    tools = str(repo_root() / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import racket_smoothing
    return racket_smoothing


def load_document():
    path = repo_root() / SKELETON_JSON
    if not path.exists():
        raise RuntimeError(f"not found: {path}\nRun tools/lift_racket_3d.py first.")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def joints_array(doc):
    """(T, J, 3) in ROMP camera space, i.e. with the Unity reflection undone."""
    n = len(doc["joint_names"])
    arr = np.array([f["joints_flat"] for f in doc["frames"]], dtype=np.float64)
    return arr.reshape(len(doc["frames"]), n, 4)[..., :3] * UNFLIP


# ------------------------------------------------------------------------- geometry

def procrustes(src, dst):
    """Rigid (R, t) mapping src onto dst, restricted to proper rotations.

    Reflections are excluded deliberately: a mirrored fit would look numerically fine while
    swapping the body's left and right, and the racket would end up on the wrong arm.
    """
    sc, dc = src.mean(axis=0), dst.mean(axis=0)
    u, _, vt = np.linalg.svd((src - sc).T @ (dst - dc))
    rot = vt.T @ u.T
    if np.linalg.det(rot) < 0:
        rot = vt.T @ np.diag([1.0, 1.0, -1.0]) @ u.T
    return rot, dc - rot @ sc


def build_racket_mesh(name, length, width):
    """Racket in a canonical local frame: grip at origin, shaft +X, across +Y, normal +Z."""
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()

    bed_a = min(0.145, length * 0.30)               # bed half-length, along the shaft
    bed_b = max(width / 2.0, 1e-3)                  # bed half-width, across
    centre = length - bed_a
    shaft_len = max(centre - bed_a, 1e-3)

    ring_a, ring_b = [], []
    for i in range(12):
        ang = 2 * math.pi * i / 12
        y, z = SHAFT_RADIUS * math.cos(ang), SHAFT_RADIUS * math.sin(ang)
        ring_a.append(bm.verts.new((0.0, y, z)))
        ring_b.append(bm.verts.new((shaft_len, y, z)))
    for i in range(12):
        j = (i + 1) % 12
        bm.faces.new((ring_a[i], ring_a[j], ring_b[j], ring_b[i]))

    bed = [bm.verts.new((centre + bed_a * math.cos(2 * math.pi * i / BED_SEGMENTS),
                         bed_b * math.sin(2 * math.pi * i / BED_SEGMENTS), 0.0))
           for i in range(BED_SEGMENTS)]
    bm.faces.new(bed)                               # the string bed: a face, so the
    bm.to_mesh(mesh)                                # orientation reads at a glance
    bm.free()
    return mesh


def action_fcurves(obj, action=None):
    """F-curves of an object's action, across Blender's two action layouts.

    Blender 4.4+ (this scene is 5.2) moved them into layer/strip *channelbags*; older
    builds expose `action.fcurves` directly. Reading through both keeps the script usable
    on whatever Blender the next person opens the .blend with.
    """
    ad = obj.animation_data
    act = action or (ad.action if ad else None)
    if act is None:
        return []
    if hasattr(act, "fcurves"):
        return list(act.fcurves)
    slot = getattr(ad, "action_slot", None)
    out = []
    for layer in act.layers:
        for strip in layer.strips:
            bag = None
            if slot is not None and hasattr(strip, "channelbag"):
                bag = strip.channelbag(slot)
            if bag is None:
                bags = getattr(strip, "channelbags", None)
                bag = bags[0] if bags else None
            if bag is not None:
                out.extend(bag.fcurves)
    return out


def simple_material(name, rgba):
    """Flat viewport colour. `use_nodes` is only touched when it needs changing — the
    setter is deprecated in Blender 6.0 and warns on every assignment."""
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    if getattr(m, "use_nodes", False):
        m.use_nodes = False
    m.diffuse_color = rgba
    return m


def object_colour_material():
    """One material driven by each object's own colour, so status can be keyframed."""
    mat = bpy.data.materials.get("RacketStatus")
    if mat is None:
        mat = bpy.data.materials.new("RacketStatus")
    # Only assign when it is actually off: the setter is deprecated in Blender 6.0 and
    # warns on every call, while new materials already default to nodes.
    if hasattr(mat, "use_nodes") and not mat.use_nodes:
        mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfDiffuse")
    info = nodes.new("ShaderNodeObjectInfo")
    links.new(info.outputs["Color"], bsdf.inputs["Color"])
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return mat


def frame_matrix(grip, head, side):
    """World matrix for the racket from its three points, or None if degenerate."""
    x = Vector(head - grip)
    if x.length < 1e-6:
        return None
    x.normalize()
    across = Vector(side - head)
    y = across - across.dot(x) * x
    if y.length < 1e-6:
        return None
    y.normalize()
    z = x.cross(y)
    return Matrix(((x.x, y.x, z.x, grip[0]),
                   (x.y, y.y, z.y, grip[1]),
                   (x.z, y.z, z.z, grip[2]),
                   (0.0, 0.0, 0.0, 1.0)))


# ----------------------------------------------------------------------------- build

def clear_previous():
    """Drop rackets, their joints and their actions from a previous run.

    Without removing the actions too, every re-run leaves orphan `act_racket_*` datablocks
    behind and the file grows a little each time.
    """
    for key, (_, _, joints_coll) in BODIES.items():
        coll = bpy.data.collections.get(joints_coll)
        if coll is not None:
            for o in list(coll.objects):
                bpy.data.objects.remove(o, do_unlink=True)
        obj = bpy.data.objects.get(f"Racket_{key}")
        if obj is not None:
            mesh = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
        # Every action this script has ever made for this body, including Blender's
        # `.001` renames. The fake user has to be cleared first: it is set so both styles
        # survive a save, but it also means `users == 0` is never true and a naive cleanup
        # leaves the old action behind — then `actions.new()` renames the new one and the
        # file accumulates a duplicate set on every single run.
        prefix = f"act_racket_{key}_"
        for act in [a for a in bpy.data.actions if a.name.startswith(prefix)]:
            act.use_fake_user = False
            if act.users == 0:
                bpy.data.actions.remove(act)


def keyframe_action(obj, action_name, frames, points, records):
    """Write one action: pose + visibility + status colour, per frame."""
    ad = obj.animation_data or obj.animation_data_create()
    act = bpy.data.actions.new(action_name)
    act.use_fake_user = True            # both styles must survive a save/reload
    ad.action = act

    for i, f in enumerate(frames):
        grip, head, side = points[i]
        rec = records[i]
        mat4 = None if grip is None else frame_matrix(grip, head, side)
        visible = mat4 is not None and rec.get("racket_status") != "none"
        if visible:
            obj.matrix_world = mat4
        obj.hide_viewport = obj.hide_render = not visible
        obj.keyframe_insert("location", frame=f)
        obj.keyframe_insert("rotation_quaternion", frame=f)
        obj.keyframe_insert("hide_viewport", frame=f)
        obj.keyframe_insert("hide_render", frame=f)

        if rec.get("racket_status") == "prior":
            obj.color = COLOUR_PRIOR
        elif rec.get("racket_roll_status") == "measured":
            obj.color = COLOUR_FULL
        else:
            obj.color = COLOUR_NO_ROLL
        obj.keyframe_insert("color", frame=f)

    # Constant interpolation on visibility and colour: these are per-frame states, not
    # quantities to ease between. Bezier would fade a red prior frame through orange.
    for fc in action_fcurves(obj, act):
        if fc.data_path in {"hide_viewport", "hide_render", "color"}:
            for kp in fc.keyframe_points:
                kp.interpolation = "CONSTANT"
    return act


def build_racket_joints(key, racket_obj, length, width):
    """Three spheres parented to the racket, so they follow it with no keyframes at all."""
    _, _, coll_name = BODIES[key]
    coll = bpy.data.collections.get(coll_name)
    if coll is None:
        coll = bpy.data.collections.new(coll_name)
        bpy.context.scene.collection.children.link(coll)
    offsets = {"grip": (0.0, 0.0, 0.0),
               "head": (length, 0.0, 0.0),
               "side": (length, width / 2.0, 0.0)}
    for role, offset in offsets.items():
        mesh = bpy.data.meshes.new(f"rjoint_{key}_{role}")
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=2, radius=JOINT_RADIUS)
        bm.to_mesh(mesh)
        bm.free()
        mesh.materials.append(simple_material(f"rjmat_{role}", JOINT_COLOURS[role]))
        for poly in mesh.polygons:
            poly.use_smooth = True
        ob = bpy.data.objects.new(f"RacketJoint_{key}_{role}", mesh)
        # Both channels: the material colours it in Material/Rendered shading, `object.color`
        # in Solid/Workbench "Object" mode — which is the mode that makes the racket's own
        # confidence colours visible, so a sphere left unset would render plain white there.
        ob.color = JOINT_COLOURS[role]
        coll.objects.link(ob)
        ob.parent = racket_obj
        ob.matrix_parent_inverse = Matrix.Identity(4)
        ob.location = offset
        ob.hide_viewport = ob.hide_render = True     # off by default, like twin_compare's
    return len(offsets)


def build():
    smoothing = import_smoothing()
    doc = load_document()
    meta = doc.get("racket")
    if not meta:
        raise RuntimeError("no `racket` block -- was this file produced by lift_racket_3d.py?")
    joints = joints_array(doc)
    gi, hi, si = meta["grip_index"], meta["head_index"], meta["side_index"]
    length, width = meta["length_m"], (meta.get("head_width_m") or 0.02)
    fps = doc.get("fps") or bpy.context.scene.render.fps

    scene = bpy.context.scene
    original_frame = scene.frame_current
    n_frames = min(len(doc["frames"]), scene.frame_end - scene.frame_start + 1)
    frames = [scene.frame_start + i for i in range(n_frames)]
    records = doc["frames"][:n_frames]

    clear_previous()
    mat = object_colour_material()
    report = {}

    # Bone positions for every frame, read once. frame_set is expensive, so both bodies are
    # sampled per visit rather than sweeping the timeline once per body.
    bone_track = {key: [] for key in BODIES}
    for f in frames:
        scene.frame_set(f)
        bpy.context.view_layer.update()
        for key, (_, arm_name, _) in BODIES.items():
            arm = bpy.data.objects.get(arm_name)
            if arm is None:
                continue
            mw = arm.matrix_world
            bone_track[key].append(np.array([list(mw @ arm.pose.bones[b].head) for b in BONES]))

    for key, (coll_name, arm_name, _) in BODIES.items():
        if bpy.data.objects.get(arm_name) is None:
            report[key] = "armature missing"
            continue
        coll = bpy.data.collections.get(coll_name) or scene.collection
        obj = bpy.data.objects.new(f"Racket_{key}", build_racket_mesh(f"racket_{key}",
                                                                     length, width))
        obj.data.materials.append(mat)
        obj.rotation_mode = "QUATERNION"
        coll.objects.link(obj)

        # Map the racket into this body's space, frame by frame.
        grips, heads, sides, valid, residuals = [], [], [], [], []
        for i in range(n_frames):
            body = joints[i][:24]
            rot, trans = procrustes(body, bone_track[key][i])
            residuals.append(float(np.sqrt(
                (np.linalg.norm((rot @ body.T).T + trans - bone_track[key][i], axis=1) ** 2
                 ).mean())))
            pts = [(rot @ joints[i][j]) + trans for j in (gi, hi, si)]
            grips.append(pts[0]), heads.append(pts[1]), sides.append(pts[2])
            valid.append(records[i].get("racket_status") != "none")

        grips, heads, sides = np.array(grips), np.array(heads), np.array(sides)
        valid = np.array(valid, dtype=bool)
        sg, sh, ss = smoothing.smooth_racket(grips, heads, sides, fps=fps, valid=valid)

        raw_points = [(grips[i], heads[i], sides[i]) if valid[i] else (None, None, None)
                      for i in range(n_frames)]
        smooth_points = [(sg[i], sh[i], ss[i]) if valid[i] else (None, None, None)
                         for i in range(n_frames)]
        keyframe_action(obj, f"act_racket_{key}_raw", frames, raw_points, records)
        keyframe_action(obj, f"act_racket_{key}_smooth", frames, smooth_points, records)
        set_style(key, DEFAULT_STYLE[key])

        n_joints = build_racket_joints(key, obj, length, width)
        report[key] = {"frames": n_frames, "racket_joints": n_joints,
                       "fit_rms_median_m": round(float(np.median(residuals)), 4),
                       "fit_rms_max_m": round(float(np.max(residuals)), 4),
                       "smoothing_shift_median_m": round(
                           float(np.median(np.linalg.norm(sh[valid] - heads[valid], axis=1))), 4)}

    scene.frame_set(original_frame)
    bpy.context.view_layer.update()
    return {"racket": {k: meta[k] for k in ("length_m", "head_width_m", "handedness",
                                            "coverage", "roll_coverage") if k in meta},
            "smoothing": {"tau_s": smoothing.DEFAULT_TAU, "zero_phase": True},
            "bodies": report}


# ----------------------------------------------------------------------------- panel

def set_style(key, style):
    obj = bpy.data.objects.get(f"Racket_{key}")
    if obj is None:
        return
    act = bpy.data.actions.get(f"act_racket_{key}_{'smooth' if style == 'SMOOTH' else 'raw'}")
    if act is None:
        return
    ad = obj.animation_data or obj.animation_data_create()
    ad.action = act
    # Slotted actions (4.4+) need the slot bound explicitly after a swap, or the action is
    # assigned but drives nothing and the racket silently freezes.
    if hasattr(ad, "action_slot") and getattr(ad, "action_slot", None) is None:
        slots = getattr(act, "slots", None)
        if slots:
            ad.action_slot = slots[0]


def _apply(key, style, racket_on, joints_on):
    set_style(key, style)
    coll = bpy.data.collections.get(BODIES[key][2])
    for o in (coll.objects if coll else []):
        o.hide_viewport = o.hide_render = not joints_on
    obj = bpy.data.objects.get(f"Racket_{key}")
    if obj is None:
        return
    # `hide_viewport` is keyframed per frame (the racket hides itself where there is no
    # racket), so the master switch uses the view-layer hide instead — a separate flag that
    # the action cannot overwrite on the next frame change.
    if bpy.context.view_layer.objects.get(obj.name) is not None:
        obj.hide_set(not racket_on)
    obj.hide_render = obj.hide_render or not racket_on


def _updA(self, ctx):
    _apply("A", self.A_style, self.A_racket, self.A_joints)


def _updB(self, ctx):
    _apply("B", self.B_style, self.B_racket, self.B_joints)


_STYLE_ITEMS = [("RAW", "Raw", "Racket straight from the lift"),
                ("SMOOTH", "Smooth", "Spring-smoothed, zero-phase, still rigid")]


class RacketProps(bpy.types.PropertyGroup):
    A_style: bpy.props.EnumProperty(name="Style", items=_STYLE_ITEMS,
                                    default=DEFAULT_STYLE["A"], update=_updA)
    A_racket: bpy.props.BoolProperty(name="Racket", default=True, update=_updA)
    A_joints: bpy.props.BoolProperty(name="Joints", default=False, update=_updA)
    B_style: bpy.props.EnumProperty(name="Style", items=_STYLE_ITEMS,
                                    default=DEFAULT_STYLE["B"], update=_updB)
    B_racket: bpy.props.BoolProperty(name="Racket", default=True, update=_updB)
    B_joints: bpy.props.BoolProperty(name="Joints", default=False, update=_updB)


class RACKET_PT_panel(bpy.types.Panel):
    bl_label = "Racket"
    bl_idname = "RACKET_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Racket"

    def draw(self, ctx):
        p = getattr(ctx.scene, "racketview", None)
        layout = self.layout
        if p is None:
            layout.label(text="run racket_viewer.py", icon="ERROR")
            return
        layout.label(text="RAW (left) vs SMOOTH (right)")
        for title, pre in (("Left body", "A_"), ("Right body", "B_")):
            box = layout.box()
            box.label(text=title)
            if bpy.data.objects.get(f"Racket_{pre[0]}") is None:
                box.label(text="not built", icon="ERROR")
                continue
            box.prop(p, pre + "style", expand=True)
            row = box.row(align=True)
            row.prop(p, pre + "racket", toggle=True)
            row.prop(p, pre + "joints", toggle=True)
        box = layout.box()
        box.label(text="Colour = confidence", icon="INFO")
        box.label(text="green: position + roll measured")
        box.label(text="amber: roll is a guess")
        box.label(text="red: position is the forearm prior")


_CLASSES = (RacketProps, RACKET_PT_panel)


def register():
    for c in _CLASSES:
        try:
            bpy.utils.register_class(c)
        except Exception:
            pass
    bpy.types.Scene.racketview = bpy.props.PointerProperty(type=RacketProps)


def unregister():
    try:
        del bpy.types.Scene.racketview
    except Exception:
        pass
    for c in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(c)
        except Exception:
            pass


if __name__ == "__main__":
    summary = build()
    try:
        unregister()
    except Exception:
        pass
    register()
    print("racket viewer:", json.dumps(summary, indent=1))
