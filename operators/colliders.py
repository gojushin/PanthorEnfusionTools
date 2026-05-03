"""Collider Setup and Validation Operators."""

import bpy
from bpy.types import Operator

from ..utils.constants import (
    COLLIDER_PREFIX_BOX,
    COLLIDER_PREFIX_CAPSULE,
    COLLIDER_PREFIX_CONVEX,
    COLLIDER_PREFIX_CYLINDER,
    COLLIDER_PREFIX_SPHERE,
    MAX_VERTS_COLLIDER,
)


def rename_and_enumerate_colliders():
    """Rename boxes from UCX to UBX and enumerate suffixes."""
    colliders = []
    prefixes = ("UBX_", "UCX_", "USP_", "UCS_", "UCL_")

    for obj in bpy.context.scene.objects:
        if obj.type == 'MESH' and any(obj.name.startswith(p) for p in prefixes):
            colliders.append(obj)

    # Dictionary to keep track of counts per base name
    base_counts = {}

    for obj in colliders:
        # Check if it's a box currently named UCX
        if obj.name.startswith("UCX_") and len(obj.data.vertices) == 8:
            obj.name = obj.name.replace("UCX_", "UBX_", 1)

        # Parse base name
        parts = obj.name.split('_')
        if len(parts) >= 2:
            prefix = parts[0] + "_"
            base_name = parts[1]

            key = f"{prefix}{base_name}"

            if key not in base_counts:
                base_counts[key] = 0
                obj.name = key
            else:
                base_counts[key] += 1
                obj.name = f"{key}_{base_counts[key]:02d}"

class PANTHOR_OT_fix_colliders(Operator):
    """Rename Box colliders and enumerate all colliders."""

    bl_idname = "panthor.fix_colliders"
    bl_label = "Fix Colliders"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        """Execute fix colliders."""
        rename_and_enumerate_colliders()
        self.report({'INFO'}, "Colliders fixed.")
        return {'FINISHED'}

class PANTHOR_OT_add_collider(Operator):
    """Add a primitive collider to the active object."""

    bl_idname = "panthor.add_collider"
    bl_label = "Add Collider"
    bl_options = {'REGISTER', 'UNDO'}

    collider_type: bpy.props.EnumProperty(
        items=[
            ('BOX', "Box", ""),
            ('CONVEX', "Convex", ""),
            ('SPHERE', "Sphere", ""),
            ('CAPSULE', "Capsule", ""),
            ('CYLINDER', "Cylinder", ""),
        ]
    )

    def execute(self, context):
        """Add primitive."""
        active = context.active_object
        if not active or active.type != 'MESH':
            self.report({'WARNING'}, "Please select a mesh object first.")
            return {'CANCELLED'}

        base_name = active.name
        # Remove LOD suffix if present
        if "_LOD" in base_name:
            base_name = base_name.split("_LOD")[0]

        if self.collider_type == 'BOX':
            bpy.ops.mesh.primitive_cube_add()
            prefix = COLLIDER_PREFIX_BOX
        elif self.collider_type == 'CONVEX':
            bpy.ops.mesh.primitive_cube_add() # Placeholder for convex
            prefix = COLLIDER_PREFIX_CONVEX
        elif self.collider_type == 'SPHERE':
            bpy.ops.mesh.primitive_uv_sphere_add()
            prefix = COLLIDER_PREFIX_SPHERE
        elif self.collider_type == 'CAPSULE':
            bpy.ops.mesh.primitive_cylinder_add() # Capsule is tricky without extra steps, using cylinder
            prefix = COLLIDER_PREFIX_CAPSULE
        elif self.collider_type == 'CYLINDER':
            bpy.ops.mesh.primitive_cylinder_add()
            prefix = COLLIDER_PREFIX_CYLINDER

        new_obj = context.active_object
        new_obj.name = f"{prefix}{base_name}"

        # Enumerate to ensure correct suffix
        rename_and_enumerate_colliders()

        return {'FINISHED'}

class PANTHOR_OT_validate_colliders(Operator):
    """Check colliders for errors."""

    bl_idname = "panthor.validate_colliders"
    bl_label = "Validate Colliders"
    bl_options = {'REGISTER'}

    def execute(self, context):
        """Validate all colliders."""
        prefixes = ("UBX_", "UCX_", "USP_", "UCS_", "UCL_")
        errors = []

        for obj in bpy.context.scene.objects:
            if obj.type == 'MESH' and any(obj.name.startswith(p) for p in prefixes):
                # Check origin
                if tuple(obj.location) != (0.0, 0.0, 0.0):
                    errors.append(f"{obj.name}: Origin not at center.")

                # Check rotation and scale
                if tuple(obj.scale) != (1.0, 1.0, 1.0):
                    errors.append(f"{obj.name}: Scale not applied.")
                if tuple(obj.rotation_euler) != (0.0, 0.0, 0.0):
                    errors.append(f"{obj.name}: Rotation not applied.")

                # Check vertices
                if len(obj.data.vertices) > MAX_VERTS_COLLIDER:
                    errors.append(f"{obj.name}: Vertices exceed {MAX_VERTS_COLLIDER}.")

        if errors:
            for e in errors:
                self.report({'ERROR'}, e)
        else:
            self.report({'INFO'}, "All colliders validated successfully.")

        return {'FINISHED'}

def register():
    """Register collider operators."""
    bpy.utils.register_class(PANTHOR_OT_fix_colliders)
    bpy.utils.register_class(PANTHOR_OT_add_collider)
    bpy.utils.register_class(PANTHOR_OT_validate_colliders)

def unregister():
    """Unregister collider operators."""
    bpy.utils.unregister_class(PANTHOR_OT_validate_colliders)
    bpy.utils.unregister_class(PANTHOR_OT_add_collider)
    bpy.utils.unregister_class(PANTHOR_OT_fix_colliders)
