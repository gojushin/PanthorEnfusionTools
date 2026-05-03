"""Panthor Enfusion Tools Addon.

Toolbox for converting FBX and Textures to Enfusion engine standards.
"""

from . import operators, ui


def register():
    """Register all addon classes."""
    operators.register()
    ui.register()

def unregister():
    """Unregister all addon classes."""
    ui.unregister()
    operators.unregister()

if __name__ == "__main__":
    register()
