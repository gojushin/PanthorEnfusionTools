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


def _update_collection_name(self, _context):
    """Rename collection and all contained objects when the name changes.

    For each object, the existing suffix/prefix relative to the old base
    name is preserved and the new base name is substituted in.
    """
    scene = bpy.context.scene
    col = bpy.data.collections.get(scene.get("panthor_import_col_real", ""))
    if not col:
        return

    new_base = scene.panthor_import_collection_name
    old_name = col.name

    # Derive old base name (the collection name *is* the old base name)
    old_base = old_name

    # Rename objects inside the collection
    for obj in list(col.objects):
        if obj.name == old_base or obj.name.startswith(f"{old_base}_"):
            suffix = obj.name[len(old_base):]
            obj.name = f"{new_base}{suffix}"

            # Rename mesh data-block to match
            if obj.data:
                obj.data.name = obj.name

    # Rename the collection itself
    col.name = new_base
    scene["panthor_import_col_real"] = col.name


class PANTHOR_OT_import_fbx(Operator):
    """Import an FBX file and organise it into a collection for Enfusion."""

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
        """Execute the FBX import."""
        import os

        # Import FBX
        bpy.ops.import_scene.fbx(filepath=self.filepath)

        collider_prefixes = (
            COLLIDER_PREFIX_BOX, COLLIDER_PREFIX_CONVEX, COLLIDER_PREFIX_SPHERE,
            COLLIDER_PREFIX_CAPSULE, COLLIDER_PREFIX_CYLINDER, "UCX", "UBX", "USP", "UCS", "UCL"
        )

        objects_to_delete = []
        imported_objects = list(context.selected_objects)

        for obj in imported_objects:
            name = obj.name
            name_lower = name.lower()

            # Detect LOD prefix: LOD{n}_Name
            is_lod = (
                name_lower.startswith("lod")
                and len(name_lower) > 3
                and name_lower[3].isdigit()
                and "_" in name_lower[3:]
            )
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
            # Refresh the surviving list
            imported_objects = [o for o in imported_objects if o not in objects_to_delete]

        # --- Organise into a collection ---
        # Derive a base name from the filename
        base_name = os.path.splitext(os.path.basename(self.filepath))[0]

        col = bpy.data.collections.new(base_name)
        context.scene.collection.children.link(col)

        for obj in imported_objects:
            # Unlink from any existing collections, then link to ours
            for old_col in list(obj.users_collection):
                old_col.objects.unlink(obj)
            col.objects.link(obj)

        # Store reference so the rename callback can find the collection
        context.scene["panthor_import_col_real"] = col.name
        context.scene.panthor_import_collection_name = base_name

        # Make base mesh active so refresh_lods works, then refresh UI lists
        for obj in imported_objects:
            if obj.type == 'MESH':
                name_lower = obj.name.lower()
                is_lod = (
                    name_lower.startswith("lod")
                    and len(name_lower) > 3
                    and name_lower[3].isdigit()
                    and "_" in name_lower[3:]
                )
                is_collider = any(obj.name.startswith(p) for p in collider_prefixes)
                if not is_lod and not is_collider:
                    bpy.context.view_layer.objects.active = obj
                    break

        bpy.ops.panthor.refresh_lods()
        bpy.ops.panthor.refresh_colliders()

        self.report({'INFO'}, f"Imported FBX into collection '{base_name}'")
        return {'FINISHED'}


def register():
    """Register the import FBX operator."""
    bpy.utils.register_class(PANTHOR_OT_import_fbx)
    bpy.types.Scene.panthor_import_collection_name = StringProperty(
        name="Collection Name",
        description="Rename the import collection and all its objects",
        default="",
        update=_update_collection_name,
    )


def unregister():
    """Unregister the import FBX operator."""
    bpy.utils.unregister_class(PANTHOR_OT_import_fbx)
    del bpy.types.Scene.panthor_import_collection_name
