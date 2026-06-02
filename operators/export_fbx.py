"""FBX Export Operators."""

import os
from typing import ClassVar

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from ..utils.constants import (
    COLLIDER_PREFIX_BOX,
    COLLIDER_PREFIX_CAPSULE,
    COLLIDER_PREFIX_CONVEX,
    COLLIDER_PREFIX_CYLINDER,
    COLLIDER_PREFIX_SPHERE,
    TEXTURE_SUFFIX_ENFUSION_NMO,
)
from ..utils.texture_processing import is_nmo_default


class PanthorOTExportFbx(Operator):
    """Export scene as FBX with textures for Enfusion."""

    bl_idname: ClassVar[str] = "panthor.export_fbx"
    bl_label: ClassVar[str] = "Export FBX for Enfusion"
    bl_options: ClassVar[set[str]] = {"REGISTER"}

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

        # Export FBX — derive base name from collection or active object
        base_name = "ExportedModel"

        # 1. Try collection name first
        col_name = context.scene.get("panthor_import_col_real", "")
        if col_name:
            base_name = col_name
        elif context.scene.panthor_import_collection_name:
            base_name = context.scene.panthor_import_collection_name
        elif context.active_object:
            raw = context.active_object.name
            # New convention: BaseName_LODx
            if "_LOD" in raw:
                rest, _, lod_suffix = raw.rpartition("_LOD")
                base_name = rest if lod_suffix.isdigit() else raw
            else:
                base_name = raw

        fbx_path = os.path.join(self.directory, f"{base_name}.fbx")
        bpy.ops.export_scene.fbx(
            filepath=fbx_path, use_selection=False, apply_unit_scale=True, apply_scale_options="FBX_SCALE_ALL"
        )

        # Save Textures
        for img in list(bpy.data.images):
            if img.has_data and img.name.startswith("PTR_"):
                # Skip default/empty NMO maps (flat normal, no metal, no AO)
                if img.name.endswith(TEXTURE_SUFFIX_ENFUSION_NMO) and is_nmo_default(img):
                    continue

                # Always save as PNG for Enfusion compatibility
                img_path = os.path.join(self.directory, f"{img.name}.png")
                img.filepath_raw = img_path
                img.file_format = "PNG"
                img.save()

        self.report({"INFO"}, f"FBX exported to {self.directory}")
        return {"FINISHED"}


class PanthorOTExportFbxEbt(Operator):
    """Export scene using the Arma Reforger EBT export function."""

    bl_idname: ClassVar[str] = "panthor.export_fbx_ebt"
    bl_label: ClassVar[str] = "Export using EBT"
    bl_options: ClassVar[set[str]] = {"REGISTER"}

    @classmethod
    def poll(cls, context):
        """Check if EBT is available."""
        return hasattr(bpy.ops, "ebt") and hasattr(bpy.ops.ebt, "export_fbx")

    def execute(self, context):
        """Execute FBX export using EBT."""
        if not self.poll(context):
            self.report({"ERROR"}, "Arma Reforger - Enfusion Tools plugin is required.")
            return {"CANCELLED"}

        col_name = context.scene.get("panthor_import_col_real", "")
        col = bpy.data.collections.get(col_name) if col_name else None

        if col:
            bpy.ops.object.select_all(action="DESELECT")
            for obj in col.objects:
                obj.select_set(True)
                if obj.type == "MESH":
                    context.view_layer.objects.active = obj
        else:
            self.report({"WARNING"}, "No specific collection found, exporting current selection.")

        bpy.ops.ebt.export_fbx('INVOKE_DEFAULT', quick_export=False)
        self.report({"INFO"}, "FBX exported using EBT")
        return {"FINISHED"}


def register():
    """Register export operators."""
    bpy.utils.register_class(PanthorOTExportFbx)
    bpy.utils.register_class(PanthorOTExportFbxEbt)


def unregister():
    """Unregister export operators."""
    bpy.utils.unregister_class(PanthorOTExportFbxEbt)
    bpy.utils.unregister_class(PanthorOTExportFbx)
