"""Panthor Enfusion Tools Addon.

Toolbox for converting FBX and Textures to Enfusion engine standards.
"""

import bpy
from bpy.types import AddonPreferences

from . import operators, ui


class PanthorAddonPreferences(AddonPreferences):
    """Preferences for Panthor Enfusion Tools."""

    bl_idname = __package__

    def draw(self, context):
        """Draw preferences panel."""
        layout = self.layout
        layout.label(text="Uninstall Panthor Enfusion Tools:")

        op = layout.operator("preferences.addon_remove", text="Uninstall Addon", icon="TRASH")
        op.module = __package__


def register():
    """Register all addon classes."""
    bpy.utils.register_class(PanthorAddonPreferences)
    operators.register()
    ui.register()


def unregister():
    """Unregister all addon classes."""
    ui.unregister()
    operators.unregister()
    bpy.utils.unregister_class(PanthorAddonPreferences)


if __name__ == "__main__":
    register()
