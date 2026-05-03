"""LOD Management Operators."""

import bpy
from bpy.props import CollectionProperty, FloatProperty, PointerProperty
from bpy.types import Operator, PropertyGroup


def get_base_name(obj):
    """Get the base name without LOD suffix."""
    name = obj.name
    if "_LOD" in name:
        return name.split("_LOD")[0]
    return name


def get_lod_objects(base_name):
    """Return all LOD objects for a base name, sorted by LOD number."""
    lods = []
    for obj in bpy.context.scene.objects:
        if obj.name.startswith(f"{base_name}_LOD"):
            suffix = obj.name[len(base_name) + 4:]  # strip '{base_name}_LOD'
            if suffix.isdigit():
                lods.append((int(suffix), obj))
    lods.sort(key=lambda x: x[0])
    return lods


def _get_bounding_box_dims(obj):
    """Return (center, dimensions) of an object's world-space bounding box."""
    import mathutils

    bbox_corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
    xs = [c.x for c in bbox_corners]
    ys = [c.y for c in bbox_corners]
    zs = [c.z for c in bbox_corners]

    min_co = mathutils.Vector((min(xs), min(ys), min(zs)))
    max_co = mathutils.Vector((max(xs), max(ys), max(zs)))
    center = (min_co + max_co) / 2
    dims = max_co - min_co
    return center, dims


def _refresh_lod_list(context):
    """Shared helper that populates the LOD UIList for the active object."""
    active = context.active_object
    if not active or active.type != 'MESH':
        context.scene.panthor_lods.clear()
        return

    base_name = get_base_name(active)

    # Prefer the _LOD0 object as the base; fall back to a plain-named or active object
    lod0_obj = bpy.data.objects.get(f"{base_name}_LOD0")
    base_obj = lod0_obj or bpy.data.objects.get(base_name) or active
    base_verts = len(base_obj.data.vertices)

    context.scene.panthor_lods.clear()

    # Collect all LODs in order (LOD0 first, then LOD1, LOD2 ...)
    ordered_lods = get_lod_objects(base_name)

    # If the plain-named base exists and has no _LOD0 counterpart, show it first
    if not lod0_obj and bpy.data.objects.get(base_name):
        plain_obj = bpy.data.objects[base_name]
        item = context.scene.panthor_lods.add()
        item.obj = plain_obj
        item.has_modifier = False
        item.calc_ratio = 1.0

    for _num, obj in ordered_lods:
        item = context.scene.panthor_lods.add()
        item.obj = obj

        mod = obj.modifiers.get("Decimate")
        if mod:
            item.has_modifier = True
            item.ratio = mod.ratio
        else:
            item.has_modifier = False
            verts = len(obj.data.vertices)
            item.calc_ratio = verts / base_verts if base_verts > 0 else 1.0


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

class PANTHOR_OT_add_lod(Operator):
    """Add a new LOD to the active object."""

    bl_idname = "panthor.add_lod"
    bl_label = "Add LOD"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        """Execute add LOD."""
        active = context.active_object
        if not active or active.type != 'MESH':
            self.report({'WARNING'}, "Select a mesh object.")
            return {'CANCELLED'}

        base_name = get_base_name(active)

        # Ensure the base object is named as LOD0
        base_obj = bpy.data.objects.get(base_name)
        if base_obj and not base_obj.name.endswith("_LOD0"):
            base_obj.name = f"{base_name}_LOD0"

        # Find highest existing LOD number
        existing_lods = get_lod_objects(base_name)
        next_lod_num = (existing_lods[-1][0] + 1) if existing_lods else 1

        # Duplicate active object
        bpy.ops.object.duplicate(linked=False)
        new_obj = context.active_object
        new_obj.name = f"{base_name}_LOD{next_lod_num}"

        # Add decimate modifier with progressive reduction
        mod = new_obj.modifiers.new(name="Decimate", type='DECIMATE')
        mod.ratio = max(0.1, 1.0 - (0.25 * next_lod_num))

        # Auto-refresh the list
        _refresh_lod_list(context)

        return {'FINISHED'}


class PANTHOR_OT_remove_lod(Operator):
    """Remove the selected LOD from the list and delete the object."""

    bl_idname = "panthor.remove_lod"
    bl_label = "Remove LOD"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        """Execute remove LOD."""
        scene = context.scene
        idx = scene.panthor_lod_index

        if idx < 0 or idx >= len(scene.panthor_lods):
            self.report({'WARNING'}, "No LOD selected.")
            return {'CANCELLED'}

        item = scene.panthor_lods[idx]
        obj = item.obj

        if not obj:
            self.report({'WARNING'}, "LOD object no longer exists.")
            scene.panthor_lods.remove(idx)
            return {'CANCELLED'}

        # Prevent deleting LOD0 / base mesh
        if idx == 0:
            self.report({'WARNING'}, "Cannot delete the base mesh (LOD0).")
            return {'CANCELLED'}

        # Delete the Blender object
        bpy.data.objects.remove(obj, do_unlink=True)

        # Refresh the list
        _refresh_lod_list(context)

        # Clamp selected index
        scene.panthor_lod_index = min(idx, len(scene.panthor_lods) - 1)

        return {'FINISHED'}


def update_decimate_ratio(self, context):
    """Update modifier when UI property changes."""
    if not self.obj:
        return
    mod = self.obj.modifiers.get("Decimate")
    if mod:
        mod.ratio = self.ratio


class PanthorLODItem(PropertyGroup):
    """Property group for UIList LOD items."""

    obj: PointerProperty(type=bpy.types.Object)
    ratio: FloatProperty(
        name="Ratio",
        min=0.0, max=1.0,
        update=update_decimate_ratio
    )
    has_modifier: bpy.props.BoolProperty()
    calc_ratio: FloatProperty()


class PANTHOR_OT_refresh_lods(Operator):
    """Refresh the LOD list for the active object."""

    bl_idname = "panthor.refresh_lods"
    bl_label = "Refresh LOD List"
    bl_options = {'REGISTER'}

    def execute(self, context):
        """Execute refresh."""
        _refresh_lod_list(context)
        return {'FINISHED'}


def _update_hide_lods(self, _context):
    """Toggle visibility of all LOD objects (except LOD0) when the checkbox changes."""
    scene = bpy.context.scene
    hide = scene.panthor_hide_lods

    for item in scene.panthor_lods:
        obj = item.obj
        if not obj:
            continue
        # Never hide LOD0 / base mesh (first entry)
        if obj.name.endswith("_LOD0"):
            continue
        if "_LOD" in obj.name:
            obj.hide_viewport = hide
            obj.hide_render = hide


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register():
    """Register LOD operators."""
    bpy.utils.register_class(PanthorLODItem)
    bpy.types.Scene.panthor_lods = CollectionProperty(type=PanthorLODItem)
    bpy.types.Scene.panthor_lod_index = bpy.props.IntProperty()
    bpy.types.Scene.panthor_hide_lods = bpy.props.BoolProperty(
        name="Hide LODs",
        description="Hide all LOD objects (except LOD0) in the viewport",
        default=False,
        update=_update_hide_lods,
    )

    bpy.utils.register_class(PANTHOR_OT_add_lod)
    bpy.utils.register_class(PANTHOR_OT_remove_lod)
    bpy.utils.register_class(PANTHOR_OT_refresh_lods)


def unregister():
    """Unregister LOD operators."""
    bpy.utils.unregister_class(PANTHOR_OT_refresh_lods)
    bpy.utils.unregister_class(PANTHOR_OT_remove_lod)
    bpy.utils.unregister_class(PANTHOR_OT_add_lod)

    del bpy.types.Scene.panthor_hide_lods
    del bpy.types.Scene.panthor_lods
    del bpy.types.Scene.panthor_lod_index
    bpy.utils.unregister_class(PanthorLODItem)
