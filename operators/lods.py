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

        # Find highest LOD number
        lod_objs = [obj for obj in bpy.context.scene.objects if obj.name.startswith(f"{base_name}_LOD")]
        next_lod_num = 1
        if lod_objs:
            nums = []
            for o in lod_objs:
                parts = o.name.split("_LOD")
                if len(parts) > 1 and parts[1].isdigit():
                    nums.append(int(parts[1]))
            if nums:
                next_lod_num = max(nums) + 1

        # Duplicate active
        bpy.ops.object.duplicate(linked=False)
        new_obj = context.active_object
        new_obj.name = f"{base_name}_LOD{next_lod_num}"

        # Add decimate
        mod = new_obj.modifiers.new(name="Decimate", type='DECIMATE')
        mod.ratio = max(0.1, 1.0 - (0.25 * next_lod_num)) # Default reduction

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
        active = context.active_object
        if not active or active.type != 'MESH':
            context.scene.panthor_lods.clear()
            return {'CANCELLED'}

        base_name = get_base_name(active)

        # Get base object (LOD0 essentially, or just the base mesh)
        base_obj = bpy.data.objects.get(base_name)
        if not base_obj:
            base_obj = active

        base_verts = len(base_obj.data.vertices)

        context.scene.panthor_lods.clear()

        # Find all LODs
        lods = [base_obj]
        lods.extend(sorted(
            [obj for obj in bpy.context.scene.objects if obj.name.startswith(f"{base_name}_LOD")],
            key=lambda o: o.name
        ))

        for obj in lods:
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

        return {'FINISHED'}

def register():
    """Register LOD operators."""
    bpy.utils.register_class(PanthorLODItem)
    bpy.types.Scene.panthor_lods = CollectionProperty(type=PanthorLODItem)
    bpy.types.Scene.panthor_lod_index = bpy.props.IntProperty()

    bpy.utils.register_class(PANTHOR_OT_add_lod)
    bpy.utils.register_class(PANTHOR_OT_refresh_lods)

def unregister():
    """Unregister LOD operators."""
    bpy.utils.unregister_class(PANTHOR_OT_refresh_lods)
    bpy.utils.unregister_class(PANTHOR_OT_add_lod)

    del bpy.types.Scene.panthor_lods
    del bpy.types.Scene.panthor_lod_index
    bpy.utils.unregister_class(PanthorLODItem)
