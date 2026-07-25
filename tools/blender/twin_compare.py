"""Twin Compare viewer for models/smpl/test_6_compare.blend  (Blender 5.x).

Run this inside Blender (Scripting workspace -> Open -> Run, or Alt+P) on the
compare scene. It is idempotent: re-running rebuilds the joint spheres and
re-registers the "Twin Compare" N-panel without duplicating anything.

Scene contract (built earlier, see docs/for-claude/PROGRESS.md):
  collection A_raw_left     -> armature SMPL-male.001 + mesh SMPL-mesh-male.001  (RAW,   left)
  collection B_smooth_right -> armature SMPL-male     + mesh SMPL-mesh-male      (SMOOTH,right)
  actions   act_raw / act_smooth   (per-body jitter vs spring-smoothed 0.12 s)

What this script adds/owns:
  - Renderable joint-sphere geometry: one icosphere per SMPL-24 joint, tracking
    its bone via a COPY_LOCATION constraint (so joints follow the animation AND
    show up in a final render -- stick-armature bones never render). Off by default.
  - The N-panel: per-body Style (Raw/Smooth) + Skeleton + Mesh + Joints toggles.

Panel: View3D > N > "TwinCompare" tab.
"""
import bpy
import bmesh

# SMPL-24 joints, in armature-bone order, excluding the extra "root" bone.
SMPL24 = ["Pelvis", "L_Hip", "L_Knee", "L_Ankle", "L_Foot", "R_Hip", "R_Knee",
          "R_Ankle", "R_Foot", "Spine1", "Spine2", "Spine3", "Neck", "Head",
          "L_Collar", "L_Shoulder", "L_Elbow", "L_Wrist", "L_Hand",
          "R_Collar", "R_Shoulder", "R_Elbow", "R_Wrist", "R_Hand"]

# prefix -> (body collection, joints collection, armature object, sphere color RGBA)
BODIES = {
    "A": ("A_raw_left",     "A_joints_left",  "SMPL-male.001", (0.95, 0.45, 0.10, 1.0)),  # raw    = orange
    "B": ("B_smooth_right", "B_joints_right", "SMPL-male",     (0.15, 0.80, 0.35, 1.0)),  # smooth = green
}
JOINT_RADIUS = 0.032


def _material(name, rgba):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = False
    m.diffuse_color = rgba
    return m


def build_joints(prefix):
    """(Re)build the 24 joint spheres for one body. Idempotent. Hidden by default."""
    body_col, joints_col, armname, rgba = BODIES[prefix]
    arm = bpy.data.objects[armname]
    coll = bpy.data.collections.get(joints_col)
    if coll is None:
        coll = bpy.data.collections.new(joints_col)
        bpy.context.scene.collection.children.link(coll)
    for o in list(coll.objects):                      # clear a previous build
        bpy.data.objects.remove(o, do_unlink=True)
    mat = _material("jmat_" + prefix, rgba)
    for bone in SMPL24:
        me = bpy.data.meshes.new(f"jsphere_{prefix}_{bone}")
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=2, radius=JOINT_RADIUS)
        bm.to_mesh(me)
        bm.free()
        me.materials.append(mat)
        for poly in me.polygons:
            poly.use_smooth = True
        ob = bpy.data.objects.new(f"JointSphere_{prefix}_{bone}", me)
        coll.objects.link(ob)
        c = ob.constraints.new('COPY_LOCATION')       # snap sphere to the posed bone head (= joint)
        c.target = arm
        c.subtarget = bone
        c.head_tail = 0.0
        ob.hide_viewport = True
        ob.hide_render = True
    return len(coll.objects)


# ---- N-panel -----------------------------------------------------------------
def _bodies(prefix):
    c = bpy.data.collections[BODIES[prefix][0]]
    return (next(o for o in c.objects if o.type == "ARMATURE"),
            next(o for o in c.objects if o.type == "MESH"))


def _joint_objs(prefix):
    c = bpy.data.collections.get(BODIES[prefix][1])
    return list(c.objects) if c else []


def _apply(prefix, style, skel, mesh_on, joints_on):
    arm, mesh = _bodies(prefix)
    arm.animation_data.action = bpy.data.actions["act_smooth" if style == "SMOOTH" else "act_raw"]
    arm.hide_viewport = not skel
    arm.hide_render = not skel
    mesh.hide_viewport = not mesh_on
    mesh.hide_render = not mesh_on
    for o in _joint_objs(prefix):
        o.hide_viewport = not joints_on
        o.hide_render = not joints_on


def _updA(self, ctx):
    _apply("A", self.A_style, self.A_skel, self.A_mesh, self.A_joints)


def _updB(self, ctx):
    _apply("B", self.B_style, self.B_skel, self.B_mesh, self.B_joints)


class TwinCmpProps(bpy.types.PropertyGroup):
    A_style: bpy.props.EnumProperty(name="Style", items=[("RAW", "Raw", ""), ("SMOOTH", "Smooth", "")], default="RAW", update=_updA)
    A_skel:   bpy.props.BoolProperty(name="Skeleton", default=False, update=_updA)
    A_mesh:   bpy.props.BoolProperty(name="Mesh", default=True, update=_updA)
    A_joints: bpy.props.BoolProperty(name="Joints", default=False, update=_updA)
    B_style: bpy.props.EnumProperty(name="Style", items=[("RAW", "Raw", ""), ("SMOOTH", "Smooth", "")], default="SMOOTH", update=_updB)
    B_skel:   bpy.props.BoolProperty(name="Skeleton", default=False, update=_updB)
    B_mesh:   bpy.props.BoolProperty(name="Mesh", default=True, update=_updB)
    B_joints: bpy.props.BoolProperty(name="Joints", default=False, update=_updB)


class TWINCMP_PT_panel(bpy.types.Panel):
    bl_label = "Twin Compare"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "TwinCompare"

    def draw(self, ctx):
        p = ctx.scene.twincmp
        L = self.layout
        L.label(text="RAW (left) vs SMOOTH (right) - spring 0.12s")
        for title, pre in (("Left body", "A_"), ("Right body", "B_")):
            b = L.box()
            b.label(text=title)
            b.prop(p, pre + "style", expand=True)
            r = b.row(align=True)
            r.prop(p, pre + "skel", toggle=True)
            r.prop(p, pre + "mesh", toggle=True)
            r.prop(p, pre + "joints", toggle=True)


_CLASSES = (TwinCmpProps, TWINCMP_PT_panel)


def register():
    for c in _CLASSES:
        try:
            bpy.utils.register_class(c)
        except Exception:
            pass
    bpy.types.Scene.twincmp = bpy.props.PointerProperty(type=TwinCmpProps)


def unregister():
    try:
        del bpy.types.Scene.twincmp
    except Exception:
        pass
    for c in reversed(_CLASSES):
        try:
            bpy.utils.unregister_class(c)
        except Exception:
            pass


if __name__ == "__main__":
    for prefix in BODIES:
        build_joints(prefix)
    try:
        unregister()
    except Exception:
        pass
    register()
    print("twin_compare: joint spheres built + panel registered")
