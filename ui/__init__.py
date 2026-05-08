"""UI Package init."""

from . import panel


def register():
    """Register UI classes."""
    panel.register()


def unregister():
    """Unregister UI classes."""
    panel.unregister()
