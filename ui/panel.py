"""UI Panel for Panthor Enfusion Tools."""

import bpy
from bpy.types import Panel, UIList


class PANTHOR_UL_lod_list(UIList):
    """UIList for LODs."""

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        """Draw item in the list."""
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            if item.obj:
                row.label(text=item.obj.name, icon="OBJECT_DATAMODE")

                if item.has_modifier:
                    row.prop(item, "ratio", text="")
                else:
                    row.label(text=f"{item.calc_ratio:.2f}", icon="LOCKED")
                    
                row.prop(item.obj, "hide_viewport", text="", emboss=False)
            else:
                row.label(text="<Missing>", icon="ERROR")
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text="", icon="OBJECT_DATAMODE")


class PANTHOR_UL_collider_list(UIList):
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
            else:
                row.label(text="<Missing>", icon="ERROR")
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text="", icon="MESH_CUBE")


class PANTHOR_PT_main_panel(Panel):
    """Main Panel for Panthor Enfusion Tools."""

    bl_label = "Panthor Enfusion Tools"
    bl_idname = "PANTHOR_PT_main_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Panthor"

    def draw(self, context):
        """Draw the panel."""
        layout = self.layout

        # --- Import FBX ---
        box = layout.box()
        box.label(text="1. Import FBX", icon="IMPORT")
        box.operator("panthor.import_fbx", text="Import FBX")

        # Collection name field (only shown after an import)
        if context.scene.panthor_import_collection_name:
            box.prop(context.scene, "panthor_import_collection_name", text="Collection")

        # --- Import Textures ---
        box = layout.box()
        box.label(text="2. Textures", icon="TEXTURE")
        box.operator("panthor.import_textures", text="Import & Convert Textures")

        # --- Colliders ---
        box = layout.box()
        box.label(text="3. Colliders", icon="MESH_CUBE")
        row = box.row()
        row.operator("panthor.fix_colliders", text="Fix Colliders", icon="AUTO")
        row.operator("panthor.validate_colliders", text="Validate", icon="CHECKMARK")

        row = box.row()
        row.template_list(
            "PANTHOR_UL_collider_list", "", context.scene, "panthor_colliders", context.scene, "panthor_collider_index", rows=3
        )
        col = row.column(align=True)
        col.operator("panthor.remove_collider", text="", icon="REMOVE")
        col.separator()
        col.operator("panthor.refresh_colliders", text="", icon="FILE_REFRESH")
        
        box.prop(context.scene, "panthor_hide_colliders", text="Hide Colliders", icon="HIDE_ON")

        box.label(text="Add Primitive:")
        row = box.row(align=True)
        row.operator("panthor.add_collider", text="Box", icon="MESH_CUBE").collider_type = "BOX"
        row.operator("panthor.add_collider", text="Convex", icon="MESH_ICOSPHERE").collider_type = "CONVEX"
        row.operator("panthor.add_collider", text="Sphere", icon="MESH_UVSPHERE").collider_type = "SPHERE"
        row = box.row(align=True)
        row.operator("panthor.add_collider", text="Capsule", icon="MESH_CAPSULE").collider_type = "CAPSULE"
        row.operator("panthor.add_collider", text="Cylinder", icon="MESH_CYLINDER").collider_type = "CYLINDER"

        # --- LODs ---
        box = layout.box()
        box.label(text="4. LODs", icon="MOD_DECIM")

        row = box.row()
        row.template_list(
            "PANTHOR_UL_lod_list", "", context.scene, "panthor_lods", context.scene, "panthor_lod_index", rows=3
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
        
        has_ebt = hasattr(bpy.ops, 'ebt') and hasattr(bpy.ops.ebt, 'export_fbx')
        
        row = box.row()
        op = row.operator("panthor.export_fbx", text="Export FBX for Enfusion")
        
        row = box.row()
        if not has_ebt:
            row.enabled = False
            row.operator("panthor.export_fbx_ebt", text="Export using EBT (Arma Reforger plugin required)")
        else:
            row.operator("panthor.export_fbx_ebt", text="Export using EBT")


def register():
    """Register UI elements."""
    bpy.utils.register_class(PANTHOR_UL_lod_list)
    bpy.utils.register_class(PANTHOR_UL_collider_list)
    bpy.utils.register_class(PANTHOR_PT_main_panel)


def unregister():
    """Unregister UI elements."""
    bpy.utils.unregister_class(PANTHOR_PT_main_panel)
    bpy.utils.unregister_class(PANTHOR_UL_collider_list)
    bpy.utils.unregister_class(PANTHOR_UL_lod_list)
