"""Texture operators."""

import bpy
from bpy.types import Operator


class PANTHOR_OT_import_textures(Operator):
    """Import and Convert Textures."""

    bl_idname = "panthor.import_textures"
    bl_label = "Import & Convert Textures"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        """Execute texture import."""
        self.report({"INFO"}, "Texture import & processing operator invoked.")
        return {"FINISHED"}


def register():
    """Register texture operators."""
    bpy.utils.register_class(PANTHOR_OT_import_textures)


def unregister():
    """Unregister texture operators."""
    bpy.utils.unregister_class(PANTHOR_OT_import_textures)
