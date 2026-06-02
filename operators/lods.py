"""LOD Management Operators."""

from typing import ClassVar

import bpy
from bpy.props import CollectionProperty, FloatProperty, PointerProperty
from bpy.types import Object, Operator, PropertyGroup

# LOD suffix format: "_{base_name}_LOD{n}"
_LOD_SUFFIX = "_LOD"


def get_base_name(obj: Object) -> str:
    """Get the base name without LOD suffix (e.g. 'MyMesh_LOD0' → 'MyMesh')."""
    name = obj.name
    if _LOD_SUFFIX in name:
        base, _, suffix = name.rpartition(_LOD_SUFFIX)
        if suffix.isdigit():
            return base
    return name


def get_lod_objects(base_name):
    """
    Return all LOD objects for a base name, sorted by LOD number.

    Naming convention: ``{base_name}_LOD{n}``
    """
    lods = []
    for obj in bpy.context.scene.objects:
        name = obj.name
        if not name.startswith(base_name + _LOD_SUFFIX):
            continue
        suffix = name[len(base_name) + len(_LOD_SUFFIX):]  # e.g. "0"
        if suffix.isdigit():
            lods.append((int(suffix), obj))
    lods.sort(key=lambda x: x[0])
    return lods


def _refresh_lod_list(context):
    """Shared helper that populates the LOD UIList for the active object."""
    active = context.active_object
    if not active or active.type != "MESH":
        context.scene.panthor_lods.clear()
        return

    base_name = get_base_name(active)

    # LOD0 is the base / highest-quality mesh
    lod0_obj = bpy.data.objects.get(f"{base_name}_LOD0")
    base_obj = lod0_obj or bpy.data.objects.get(base_name) or active
    base_verts = len(base_obj.data.vertices)

    context.scene.panthor_lods.clear()

    # Collect all LODs in numeric order
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


class PanthorOTAddLOD(Operator):
    """Add a new LOD using LOD0 as the base."""

    bl_idname: ClassVar[str] = "panthor.add_lod"
    bl_label: ClassVar[str] = "Add LOD"
    bl_options: ClassVar[set[str]] = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        """Check if we can add a LOD."""
        if not context.scene.panthor_lods or not context.scene.panthor_lods[0].obj:
            cls.poll_message_set("A base mesh or LOD0 must be present in the LOD list.")
            return False
        return True

    def execute(self, context):
        """Execute add LOD."""
        scene = context.scene
        lod0_obj = scene.panthor_lods[0].obj

        base_name = get_base_name(lod0_obj)

        # Ensure the base object is named as {base_name}_LOD0
        if not lod0_obj.name.endswith("_LOD0"):
            lod0_obj.name = f"{base_name}_LOD0"

        # Find highest existing LOD number
        existing_lods = get_lod_objects(base_name)
        next_lod_num = (existing_lods[-1][0] + 1) if existing_lods else 1

        # Safely duplicate LOD0 without relying on previous selection state
        bpy.ops.object.select_all(action="DESELECT")
        lod0_obj.select_set(True)
        context.view_layer.objects.active = lod0_obj

        bpy.ops.object.duplicate(linked=False)
        new_obj = context.active_object
        new_obj.name = f"{base_name}_LOD{next_lod_num}"

        # Add decimate modifier with progressive reduction
        mod = new_obj.modifiers.new(name="Decimate", type="DECIMATE")
        mod.ratio = max(0.1, 1.0 - (0.25 * next_lod_num))

        # Auto-refresh the list
        _refresh_lod_list(context)

        return {"FINISHED"}


class PanthorOTRemoveLOD(Operator):
    """Remove the selected LOD from the list and delete the object."""

    bl_idname: ClassVar[str] = "panthor.remove_lod"
    bl_label: ClassVar[str] = "Remove LOD"
    bl_options: ClassVar[set[str]] = {"REGISTER", "UNDO"}

    def execute(self, context):
        """Execute remove LOD."""
        scene = context.scene
        idx = scene.panthor_lod_index

        if idx < 0 or idx >= len(scene.panthor_lods):
            self.report({"WARNING"}, "No LOD selected.")
            return {"CANCELLED"}

        # Prevent deleting LOD0 / base mesh
        if idx == 0:
            self.report({"WARNING"}, "Cannot delete the base mesh (LOD0).")
            return {"CANCELLED"}

        item = scene.panthor_lods[idx]
        obj = item.obj

        lod0_obj = scene.panthor_lods[0].obj

        if not obj:
            self.report({"WARNING"}, "LOD object no longer exists.")
            scene.panthor_lods.remove(idx)
            return {"CANCELLED"}

        # Fallback the active object to LOD0 to prevent Blender from losing context
        if context.view_layer.objects.active == obj:
            context.view_layer.objects.active = lod0_obj
            lod0_obj.select_set(True)

        # Delete the Blender object
        bpy.data.objects.remove(obj, do_unlink=True)

        # Refresh the list
        _refresh_lod_list(context)

        # Clamp selected index
        scene.panthor_lod_index = min(idx, len(scene.panthor_lods) - 1)

        return {"FINISHED"}


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
    ratio: FloatProperty(name="Ratio", min=0.0, max=1.0, update=update_decimate_ratio)
    has_modifier: bpy.props.BoolProperty()
    calc_ratio: FloatProperty()


class PanthorOTRefreshLODs(Operator):
    """Refresh the LOD list for the active object."""

    bl_idname: ClassVar[str] = "panthor.refresh_lods"
    bl_label: ClassVar[str] = "Refresh LOD List"
    bl_options: ClassVar[set[str]] = {"REGISTER"}

    def execute(self, context):
        """Execute refresh."""
        _refresh_lod_list(context)
        return {"FINISHED"}


class PanthorOTAddWeightedNormalToLOD(Operator):
    """Add a Weighted Normal modifier to LOD with Keep Sharp enabled and weight 100."""

    bl_idname: ClassVar[str] = "panthor.add_weighted_normal_lod"
    bl_label: ClassVar[str] = "Add Weighted Normal"
    bl_options: ClassVar[set[str]] = {"REGISTER", "UNDO"}

    lod_name: bpy.props.StringProperty()

    def execute(self, context):
        """Execute add weighted normal modifier to LOD."""
        obj = bpy.data.objects.get(self.lod_name)
        if not obj:
            self.report({"WARNING"}, f"LOD object {self.lod_name} not found.")
            return {"CANCELLED"}

        # Don't add duplicate
        if obj.modifiers.find("Weighted Normal") != -1:
            self.report({"INFO"}, f"{obj.name} already has a Weighted Normal modifier.")
            return {"CANCELLED"}

        mod = obj.modifiers.new(name="Weighted Normal", type="WEIGHTED_NORMAL")
        mod.keep_sharp = True
        mod.weight = 100

        self.report({"INFO"}, f"Added Weighted Normal modifier to {obj.name}.")
        return {"FINISHED"}


def _update_hide_lods(self, _context):
    """Toggle visibility of LOD1+ objects when the checkbox changes."""
    scene = bpy.context.scene
    hide = scene.panthor_hide_lods

    for item in scene.panthor_lods:
        obj = item.obj
        if not obj:
            continue
        # Never hide LOD0 / base mesh
        if obj.name.endswith("_LOD0"):
            continue
        # Hide any object that carries a LOD suffix
        name = obj.name
        if _LOD_SUFFIX in name:
            _, _, suffix = name.rpartition(_LOD_SUFFIX)
            if suffix.isdigit():
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

    bpy.utils.register_class(PanthorOTAddLOD)
    bpy.utils.register_class(PanthorOTRemoveLOD)
    bpy.utils.register_class(PanthorOTRefreshLODs)
    bpy.utils.register_class(PanthorOTAddWeightedNormalToLOD)


def unregister():
    """Unregister LOD operators."""
    bpy.utils.unregister_class(PanthorOTAddWeightedNormalToLOD)
    bpy.utils.unregister_class(PanthorOTRefreshLODs)
    bpy.utils.unregister_class(PanthorOTRemoveLOD)
    bpy.utils.unregister_class(PanthorOTAddLOD)

    del bpy.types.Scene.panthor_hide_lods
    del bpy.types.Scene.panthor_lods
    del bpy.types.Scene.panthor_lod_index
    bpy.utils.unregister_class(PanthorLODItem)
