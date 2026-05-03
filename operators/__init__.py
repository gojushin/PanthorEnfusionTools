"""Operators package for Panthor Enfusion Tools."""

from . import colliders, export_fbx, import_fbx, lods, textures

modules = [
    import_fbx,
    textures,
    colliders,
    lods,
    export_fbx,
]


def register():
    """Register all operators."""
    for module in modules:
        if hasattr(module, "register"):
            module.register()


def unregister():
    """Unregister all operators."""
    for module in reversed(modules):
        if hasattr(module, "unregister"):
            module.unregister()
