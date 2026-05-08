"""Collider Setup and Validation Operators."""

import bpy
from bpy.props import BoolProperty, CollectionProperty, IntProperty, PointerProperty
from bpy.types import Operator, PropertyGroup

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


def _get_bounding_box_info(obj):
    """Return (center, dimensions) for *obj* in world space."""
    import mathutils

    corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
    xs = [c.x for c in corners]
    ys = [c.y for c in corners]
    zs = [c.z for c in corners]

    min_v = mathutils.Vector((min(xs), min(ys), min(zs)))
    max_v = mathutils.Vector((max(xs), max(ys), max(zs)))
    center = (min_v + max_v) / 2.0
    dims = max_v - min_v
    return center, dims


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
    """Add a primitive collider fitted to the active object's bounding box."""

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
        """Add primitive collider fitted to the target mesh."""
        active = context.active_object
        if not active or active.type != 'MESH':
            self.report({'WARNING'}, "Please select a mesh object first.")
            return {'CANCELLED'}

        base_name = context.scene.panthor_import_collection_name
        if not base_name:
            base_name = active.name
            # Strip LODx_ prefix if present (e.g. "LOD0_MyMesh" → "MyMesh")
            if base_name.startswith("LOD") and "_" in base_name[3:]:
                num_str, _, rest = base_name[3:].partition("_")
                if num_str.isdigit():
                    base_name = rest

        # Get target bounding box
        center, dims = _get_bounding_box_info(active)
        dx, dy, dz = dims.x, dims.y, dims.z

        # Create the primitive and fit it into the bounding box
        if self.collider_type == 'BOX':
            bpy.ops.mesh.primitive_cube_add()
            prefix = COLLIDER_PREFIX_BOX
            new_obj = context.active_object
            # Default cube is 2×2×2 — scale to half-dims
            new_obj.scale = (dx / 2, dy / 2, dz / 2)
            new_obj.location = center

        elif self.collider_type == 'CONVEX':
            bpy.ops.mesh.primitive_cube_add()
            prefix = COLLIDER_PREFIX_CONVEX
            new_obj = context.active_object
            new_obj.scale = (dx / 2, dy / 2, dz / 2)
            new_obj.location = center

        elif self.collider_type == 'SPHERE':
            bpy.ops.mesh.primitive_uv_sphere_add()
            prefix = COLLIDER_PREFIX_SPHERE
            new_obj = context.active_object
            # Default UV sphere radius = 1 — uniform scale to fit the largest axis
            radius = max(dx, dy, dz) / 2
            new_obj.scale = (radius, radius, radius)
            new_obj.location = center

        elif self.collider_type == 'CAPSULE':
            bpy.ops.mesh.primitive_cylinder_add()
            prefix = COLLIDER_PREFIX_CAPSULE
            new_obj = context.active_object
            # Default cylinder: radius 1, depth 2 — scale Z only to match height
            z_scale = dz / 2
            uniform_r = max(dx, dy) / 2
            new_obj.scale = (uniform_r, uniform_r, z_scale)
            new_obj.location = center

        elif self.collider_type == 'CYLINDER':
            bpy.ops.mesh.primitive_cylinder_add()
            prefix = COLLIDER_PREFIX_CYLINDER
            new_obj = context.active_object
            z_scale = dz / 2
            uniform_r = max(dx, dy) / 2
            new_obj.scale = (uniform_r, uniform_r, z_scale)
            new_obj.location = center

        new_obj.name = f"{prefix}{base_name}"

        # Apply rotation and scale, then set origin to geometry
        bpy.context.view_layer.objects.active = new_obj
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        bpy.ops.object.origin_set(type="ORIGIN_GEOMETRY", center="MEDIAN")

        # Link to the active object's collection
        active_cols = active.users_collection
        if active_cols:
            for c in new_obj.users_collection:
                c.objects.unlink(new_obj)
            active_cols[0].objects.link(new_obj)

        # Enumerate to ensure correct suffix
        rename_and_enumerate_colliders()

        # Refresh UI list
        _refresh_collider_list(context)

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


class PanthorColliderItem(PropertyGroup):
    """Property group for UIList collider items."""

    obj: PointerProperty(type=bpy.types.Object)


def _update_hide_colliders(self, context):
    """Toggle visibility of collider objects."""
    scene = context.scene
    hide = scene.panthor_hide_colliders
    prefixes = ("UBX_", "UCX_", "USP_", "UCS_", "UCL_")
    
    for obj in scene.objects:
        if obj.type == 'MESH' and any(obj.name.startswith(p) for p in prefixes):
            obj.hide_viewport = hide
            obj.hide_render = hide


def _refresh_collider_list(context):
    """Refresh the collider list UI."""
    scene = context.scene
    scene.panthor_colliders.clear()
    prefixes = ("UBX_", "UCX_", "USP_", "UCS_", "UCL_")
    
    for obj in scene.objects:
        if obj.type == 'MESH' and any(obj.name.startswith(p) for p in prefixes):
            item = scene.panthor_colliders.add()
            item.obj = obj


class PANTHOR_OT_refresh_colliders(Operator):
    """Refresh the collider list."""

    bl_idname = "panthor.refresh_colliders"
    bl_label = "Refresh Colliders"
    bl_options = {'REGISTER'}

    def execute(self, context):
        """Execute refresh colliders."""
        _refresh_collider_list(context)
        return {'FINISHED'}


class PANTHOR_OT_remove_collider(Operator):
    """Remove the selected collider and delete the object."""

    bl_idname = "panthor.remove_collider"
    bl_label = "Remove Collider"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        """Execute remove collider."""
        scene = context.scene
        idx = scene.panthor_collider_index

        if idx < 0 or idx >= len(scene.panthor_colliders):
            self.report({'WARNING'}, "No collider selected.")
            return {'CANCELLED'}

        item = scene.panthor_colliders[idx]
        obj = item.obj

        if not obj:
            scene.panthor_colliders.remove(idx)
            return {'CANCELLED'}

        bpy.data.objects.remove(obj, do_unlink=True)
        _refresh_collider_list(context)

        scene.panthor_collider_index = min(idx, max(0, len(scene.panthor_colliders) - 1))

        return {'FINISHED'}


def register():
    """Register collider operators."""
    bpy.utils.register_class(PANTHOR_OT_fix_colliders)
    bpy.utils.register_class(PANTHOR_OT_add_collider)
    bpy.utils.register_class(PANTHOR_OT_validate_colliders)
    bpy.utils.register_class(PanthorColliderItem)
    bpy.types.Scene.panthor_colliders = CollectionProperty(type=PanthorColliderItem)
    bpy.types.Scene.panthor_collider_index = IntProperty()
    bpy.types.Scene.panthor_hide_colliders = BoolProperty(
        name="Hide Colliders",
        description="Hide all collider objects in the viewport",
        default=False,
        update=_update_hide_colliders,
    )
    bpy.utils.register_class(PANTHOR_OT_refresh_colliders)
    bpy.utils.register_class(PANTHOR_OT_remove_collider)


def unregister():
    """Unregister collider operators."""
    bpy.utils.unregister_class(PANTHOR_OT_remove_collider)
    bpy.utils.unregister_class(PANTHOR_OT_refresh_colliders)
    del bpy.types.Scene.panthor_hide_colliders
    del bpy.types.Scene.panthor_collider_index
    del bpy.types.Scene.panthor_colliders
    bpy.utils.unregister_class(PanthorColliderItem)
    bpy.utils.unregister_class(PANTHOR_OT_validate_colliders)
    bpy.utils.unregister_class(PANTHOR_OT_add_collider)
    bpy.utils.unregister_class(PANTHOR_OT_fix_colliders)
