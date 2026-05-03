"""FBX Import Operators."""

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator

from ..utils.constants import (
    COLLIDER_PREFIX_BOX,
    COLLIDER_PREFIX_CAPSULE,
    COLLIDER_PREFIX_CONVEX,
    COLLIDER_PREFIX_CYLINDER,
    COLLIDER_PREFIX_SPHERE,
)


class PANTHOR_OT_import_fbx(Operator):
    """Import an FBX and process it for Enfusion."""

    bl_idname = "panthor.import_fbx"
    bl_label = "Import FBX"
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype="FILE_PATH")
    keep_lods: BoolProperty(
        name="Keep LODs",
        description="Keep LOD objects during import",
        default=True
    )
    keep_collisions: BoolProperty(
        name="Keep Collisions",
        description="Keep Collision objects during import",
        default=True
    )

    def invoke(self, context, event):
        """Invoke file selector."""
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        """Execute the import."""
        # Import FBX
        bpy.ops.import_scene.fbx(filepath=self.filepath)

        collider_prefixes = (
            COLLIDER_PREFIX_BOX, COLLIDER_PREFIX_CONVEX, COLLIDER_PREFIX_SPHERE,
            COLLIDER_PREFIX_CAPSULE, COLLIDER_PREFIX_CYLINDER, "UCX", "UBX", "USP", "UCS", "UCL"
        )

        objects_to_delete = []

        for obj in context.selected_objects:
            name_lower = obj.name.lower()

            is_lod = "lod" in name_lower
            is_collider = any(obj.name.startswith(p) for p in collider_prefixes)

            if is_lod and not self.keep_lods:
                objects_to_delete.append(obj)
                continue

            if is_collider:
                if not self.keep_collisions:
                    objects_to_delete.append(obj)
                    continue
                else:
                    # Apply rotation and scale only
                    bpy.context.view_layer.objects.active = obj
                    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
            else:
                # Apply all transforms for main meshes
                bpy.context.view_layer.objects.active = obj
                bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

        # Delete unwanted objects
        if objects_to_delete:
            bpy.ops.object.select_all(action='DESELECT')
            for obj in objects_to_delete:
                obj.select_set(True)
            bpy.ops.object.delete()

        return {'FINISHED'}

def register():
    """Register the import FBX operator."""
    bpy.utils.register_class(PANTHOR_OT_import_fbx)

def unregister():
    """Unregister the import FBX operator."""
    bpy.utils.unregister_class(PANTHOR_OT_import_fbx)
