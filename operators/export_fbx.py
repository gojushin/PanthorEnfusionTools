"""FBX Export Operators."""

import os

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from ..utils.constants import (
    COLLIDER_PREFIX_BOX,
    COLLIDER_PREFIX_CAPSULE,
    COLLIDER_PREFIX_CONVEX,
    COLLIDER_PREFIX_CYLINDER,
    COLLIDER_PREFIX_SPHERE,
)


class PANTHOR_OT_export_fbx(Operator):
    """Export scene as FBX with textures for Enfusion."""

    bl_idname = "panthor.export_fbx"
    bl_label = "Export FBX for Enfusion"
    bl_options = {"REGISTER"}

    directory: StringProperty(subtype="DIR_PATH")

    def invoke(self, context, event):
        """Invoke file selector."""
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        """Execute FBX export."""
        if not self.directory:
            return {"CANCELLED"}

        prefixes = (
            COLLIDER_PREFIX_BOX,
            COLLIDER_PREFIX_CONVEX,
            COLLIDER_PREFIX_SPHERE,
            COLLIDER_PREFIX_CAPSULE,
            COLLIDER_PREFIX_CYLINDER,
            "UCX_",
            "UBX_",
            "USP_",
            "UCS_",
            "UCL_",
        )

        # Prepare objects
        for obj in bpy.context.scene.objects:
            if obj.type == "MESH":
                bpy.context.view_layer.objects.active = obj

                is_collider = any(obj.name.startswith(p) for p in prefixes)

                if is_collider:
                    # Apply rotation and scale
                    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
                    # Set origin to geometry
                    bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="MEDIAN")
                else:
                    # Apply modifiers
                    for mod in obj.modifiers:
                        bpy.ops.object.modifier_apply(modifier=mod.name)

        # Export FBX — derive base name by stripping any LODx_ prefix
        base_name = "ExportedModel"
        if context.active_object:
            raw = context.active_object.name
            # New convention: LODx_BaseName
            if raw.startswith("LOD") and "_" in raw[3:]:
                num_str, _, rest = raw[3:].partition("_")
                base_name = rest if num_str.isdigit() else raw
            else:
                base_name = raw

        fbx_path = os.path.join(self.directory, f"{base_name}.fbx")
        bpy.ops.export_scene.fbx(
            filepath=fbx_path, use_selection=False, apply_unit_scale=True, apply_scale_options="FBX_SCALE_ALL"
        )

        # Save Textures
        for img in bpy.data.images:
            if img.has_data and img.name.startswith("PTR_"):
                # Always save as PNG for Enfusion compatibility
                img_path = os.path.join(self.directory, f"{img.name}.png")
                img.filepath_raw = img_path
                img.file_format = "PNG"
                img.save()

        self.report({"INFO"}, f"FBX exported to {self.directory}")
        return {"FINISHED"}


class PANTHOR_OT_export_fbx_ebt(Operator):
    """Export scene using the Arma Reforger EBT export function."""

    bl_idname = "panthor.export_fbx_ebt"
    bl_label = "Export using EBT"
    bl_options = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        """Check if EBT is available."""
        return hasattr(bpy.ops, 'ebt') and hasattr(bpy.ops.ebt, 'export_fbx')

    def execute(self, context):
        """Execute FBX export using EBT."""
        if not self.poll(context):
            self.report({'ERROR'}, "Arma Reforger - Enfusion Tools plugin is required.")
            return {'CANCELLED'}
        
        col_name = context.scene.get("panthor_import_col_real", "")
        col = bpy.data.collections.get(col_name) if col_name else None
        
        if col:
            bpy.ops.object.select_all(action='DESELECT')
            for obj in col.objects:
                obj.select_set(True)
                if obj.type == 'MESH':
                    context.view_layer.objects.active = obj
        else:
            self.report({'WARNING'}, "No specific collection found, exporting current selection.")

        bpy.ops.ebt.export_fbx(quick_export=False)
        self.report({"INFO"}, "FBX exported using EBT")
        return {"FINISHED"}


def register():
    """Register export operators."""
    bpy.utils.register_class(PANTHOR_OT_export_fbx)
    bpy.utils.register_class(PANTHOR_OT_export_fbx_ebt)


def unregister():
    """Unregister export operators."""
    bpy.utils.unregister_class(PANTHOR_OT_export_fbx_ebt)
    bpy.utils.unregister_class(PANTHOR_OT_export_fbx)
