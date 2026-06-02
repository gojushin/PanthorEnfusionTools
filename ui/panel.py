"""UI Panel for Panthor Enfusion Tools."""

from typing import ClassVar

import bpy
from bpy.types import Panel, UIList


class PanthorULLodList(UIList):
    """UIList for LODs."""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        """Draw item in the list."""
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            if item.obj:
                row.label(text=item.obj.name, icon="OBJECT_DATAMODE")

                mod = item.obj.modifiers.get("Decimate") if item.obj else None
                if mod:
                    row.prop(mod, "ratio", text="")
                else:
                    row.label(text=f"{item.calc_ratio:.2f}", icon="LOCKED")

                # Weighted Normal button
                wn_op = row.operator("panthor.add_weighted_normal_lod", text="", icon="MOD_NORMALEDIT")
                wn_op.lod_name = item.obj.name

                row.prop(item.obj, "hide_viewport", text="", emboss=False)
            else:
                row.label(text="<Missing>", icon="ERROR")
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text="", icon="OBJECT_DATAMODE")


class PanthorULTextureList(UIList):
    """UIList for Textures."""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        """Draw item in the list."""
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            if item.img:
                row.label(text=item.img.name, icon="IMAGE_DATA")
            else:
                row.label(text="<Missing>", icon="ERROR")
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text="", icon="IMAGE_DATA")


class PanthorULColliderList(UIList):
    """UIList for Colliders."""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        """Draw item in the list."""
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            if item.obj:
                name = item.obj.name
                c_icon = "MESH_CUBE"
                if name.startswith("UCX_"):
                    c_icon = "MESH_ICOSPHERE"
                elif name.startswith("USP_"):
                    c_icon = "MESH_UVSPHERE"
                elif name.startswith("UCS_"):
                    c_icon = "MESH_CAPSULE"
                elif name.startswith("UCL_"):
                    c_icon = "MESH_CYLINDER"

                row.label(text=name, icon=c_icon)

                # Check if EBT is available
                has_ebt = hasattr(bpy.ops, "ebt") and hasattr(bpy.ops.ebt, "collider_setup")
                op = row.operator("panthor.setup_collider", text="", icon="PROPERTIES")
                op.collider_name = name
                if not has_ebt:
                    op.enabled = False
            else:
                row.label(text="<Missing>", icon="ERROR")
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text="", icon="MESH_CUBE")


class PanthorPTMainPanel(Panel):
    """Main Panel for Panthor Enfusion Tools."""

    bl_label: ClassVar[str] = "Panthor Enfusion Tools"
    bl_idname: ClassVar[str] = "PANTHOR_PT_main_panel"
    bl_space_type: ClassVar[str] = "VIEW_3D"
    bl_region_type: ClassVar[str] = "UI"
    bl_category: ClassVar[str] = "Panthor"

    def draw(self, context):
        """Draw the panel."""
        layout = self.layout

        # --- Import FBX ---
        box = layout.box()
        box.label(text="1. Import FBX", icon="IMPORT")
        box.operator("panthor.import_fbx", text="Import FBX")

        # Collection name field (only shown after an import)
        if context.scene.get("panthor_import_col_real", ""):
            box.prop(context.scene, "panthor_import_collection_name", text="Collection")

        # --- Import Textures ---
        box = layout.box()
        box.label(text="2. Textures", icon="TEXTURE")

        row = box.row(align=True)
        row.operator("panthor.import_textures", text="Import & Remap Textures")

        row = box.row()
        row.template_list(
            "PanthorULTextureList",
            "",
            context.scene,
            "panthor_textures",
            context.scene,
            "panthor_texture_index",
            rows=3,
        )
        col = row.column(align=True)
        col.operator("panthor.refresh_textures", text="", icon="FILE_REFRESH")

        # --- Colliders ---
        box = layout.box()
        box.label(text="3. Colliders", icon="MESH_CUBE")

        # Always show: Add Primitive (needed to create the first collider)
        box.label(text="Add Primitive:")
        row = box.row(align=True)
        row.operator("panthor.add_collider", text="Box", icon="MESH_CUBE").collider_type = "BOX"
        row.operator("panthor.add_collider", text="Convex", icon="MESH_ICOSPHERE").collider_type = "CONVEX"
        row.operator("panthor.add_collider", text="Sphere", icon="MESH_UVSPHERE").collider_type = "SPHERE"
        row = box.row(align=True)
        row.operator("panthor.add_collider", text="Capsule", icon="MESH_CAPSULE").collider_type = "CAPSULE"
        row.operator("panthor.add_collider", text="Cylinder", icon="MESH_CYLINDER").collider_type = "CYLINDER"

        # Only show management options when colliders exist
        has_colliders = len(context.scene.panthor_colliders) > 0
        if has_colliders:
            row = box.row()
            row.operator("panthor.fix_colliders", text="Fix Colliders", icon="AUTO")
            row.operator("panthor.validate_colliders", text="Validate", icon="CHECKMARK")

            row = box.row()
            row.template_list(
                "PanthorULColliderList",
                "",
                context.scene,
                "panthor_colliders",
                context.scene,
                "panthor_collider_index",
                rows=3,
            )
            col = row.column(align=True)
            col.operator("panthor.remove_collider", text="", icon="REMOVE")

            # Setup operator next to the list
            idx = context.scene.panthor_collider_index
            has_selected = idx >= 0 and idx < len(context.scene.panthor_colliders)
            op = col.operator("panthor.setup_collider", text="", icon="PROPERTIES")
            if has_selected and context.scene.panthor_colliders[idx].obj:
                op.collider_name = context.scene.panthor_colliders[idx].obj.name
            else:
                op.collider_name = ""
                op.enabled = False

            col.separator()
            col.operator("panthor.refresh_colliders", text="", icon="FILE_REFRESH")

            box.prop(context.scene, "panthor_hide_colliders", text="Hide Colliders", icon="HIDE_ON")

        # --- LODs ---
        box = layout.box()
        box.label(text="4. LODs", icon="MOD_DECIM")

        row = box.row()
        row.template_list(
            "PanthorULLodList", "", context.scene, "panthor_lods", context.scene, "panthor_lod_index", rows=3
        )

        col = row.column(align=True)
        col.operator("panthor.add_lod", text="", icon="ADD")
        col.operator("panthor.remove_lod", text="", icon="REMOVE")
        col.separator()
        col.operator("panthor.refresh_lods", text="", icon="FILE_REFRESH")

        # Hide LODs toggle
        box.prop(context.scene, "panthor_hide_lods", text="Hide LODs", icon="HIDE_ON")

        # --- Export ---
        box = layout.box()
        box.label(text="5. Export FBX", icon="EXPORT")

        has_ebt = hasattr(bpy.ops, "ebt") and hasattr(bpy.ops.ebt, "export_fbx")

        row = box.row()
        row.operator("panthor.export_fbx", text="Export FBX for Enfusion")

        row = box.row()
        if not has_ebt:
            row.enabled = False
            row.operator("panthor.export_fbx_ebt", text="Export using EBT (Arma Reforger plugin required)")
        else:
            row.operator("panthor.export_fbx_ebt", text="Export using EBT")


def register():
    """Register UI elements."""
    bpy.utils.register_class(PanthorULLodList)
    bpy.utils.register_class(PanthorULTextureList)
    bpy.utils.register_class(PanthorULColliderList)
    bpy.utils.register_class(PanthorPTMainPanel)


def unregister():
    """Unregister UI elements."""
    bpy.utils.unregister_class(PanthorPTMainPanel)
    bpy.utils.unregister_class(PanthorULColliderList)
    bpy.utils.unregister_class(PanthorULTextureList)
    bpy.utils.unregister_class(PanthorULLodList)
