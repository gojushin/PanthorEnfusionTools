from typing import ClassVar

import bmesh
import bpy
import mathutils
from bpy.props import BoolProperty, CollectionProperty, IntProperty, PointerProperty
from bpy.types import Context, Object, Operator, PropertyGroup

from ..utils.constants import (
    COLLIDER_PREFIX_BOX,
    COLLIDER_PREFIX_CAPSULE,
    COLLIDER_PREFIX_CONVEX,
    COLLIDER_PREFIX_CYLINDER,
    COLLIDER_PREFIX_SPHERE,
    MAX_VERTS_COLLIDER,
)


def _rebuild_collider_geometry(obj: Object):
    """Rebuild collider geometry based on its prefix and vertex positions."""
    if obj.type != "MESH":
        return

    # 1. Get vertex positions in world space
    mw = obj.matrix_world
    verts_world = [mw @ v.co for v in obj.data.vertices]
    if not verts_world:
        return

    # Calculate basic bounding info
    xs = [v.x for v in verts_world]
    ys = [v.y for v in verts_world]
    zs = [v.z for v in verts_world]
    min_v = mathutils.Vector((min(xs), min(ys), min(zs)))
    max_v = mathutils.Vector((max(xs), max(ys), max(zs)))
    center = (min_v + max_v) / 2.0
    dims = max_v - min_v

    name = obj.name
    prefix = ""
    for p in (
        COLLIDER_PREFIX_BOX,
        COLLIDER_PREFIX_CONVEX,
        COLLIDER_PREFIX_SPHERE,
        COLLIDER_PREFIX_CAPSULE,
        COLLIDER_PREFIX_CYLINDER,
    ):
        if name.startswith(p):
            prefix = p
            break

    if not prefix:
        return

    # UCX to UBX conversion check
    if prefix == COLLIDER_PREFIX_CONVEX and len(obj.data.vertices) == 8:
        # Simple heuristic: if it has 8 verts, assume it's a box
        prefix = COLLIDER_PREFIX_BOX
        obj.name = name.replace(COLLIDER_PREFIX_CONVEX, COLLIDER_PREFIX_BOX, 1)

    # Create new mesh data
    bm = bmesh.new()

    if prefix == COLLIDER_PREFIX_BOX:
        bmesh.ops.create_cube(bm, size=1.0)
        # Scale to dimensions
        for v in bm.verts:
            v.co.x *= dims.x
            v.co.y *= dims.y
            v.co.z *= dims.z
    elif prefix == COLLIDER_PREFIX_SPHERE:
        # Sphere: uniform scale, max dimension used for radius
        radius = max(dims.x, dims.y, dims.z) / 2.0
        bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=16, radius=radius)
    elif prefix == COLLIDER_PREFIX_CYLINDER:
        # Cylinder: XY must be same scale
        radius = max(dims.x, dims.y) / 2.0
        bmesh.ops.create_cone(bm, segments=16, cap_ends=True, cap_tris=False, radius1=radius, radius2=radius, depth=dims.z)
    elif prefix == COLLIDER_PREFIX_CAPSULE:
        # Capsule: XY uniform, caps unscaled on Z
        radius = max(dims.x, dims.y) / 2.0
        height = dims.z
        bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=16, radius=radius)
        # Stretch sphere to capsule
        if height > radius * 2:
            move_amount = (height - radius * 2) / 2
            for v in bm.verts:
                if v.co.z > 0.001:
                    v.co.z += move_amount
                elif v.co.z < -0.001:
                    v.co.z -= move_amount
    elif prefix == COLLIDER_PREFIX_CONVEX:
        # Convex: Rebuild hull from original vertices
        for v_co in verts_world:
            bm.verts.new(v_co - center) # Localize to center
        bmesh.ops.convex_hull(bm, input=bm.verts)

    # Finalize mesh
    bm.to_mesh(obj.data)
    bm.free()

    # Apply translation and reset transforms
    # Move geometry to its world position but keep object at origin (Enfusion requirement)
    for v in obj.data.vertices:
        v.co += center

    obj.location = (0, 0, 0)
    obj.rotation_euler = (0, 0, 0)
    obj.scale = (1, 1, 1)
    obj.matrix_world = mathutils.Matrix.Identity(4)
    obj.data.update()


def _get_collider_basename(obj: Object, prefix: str) -> str:
    """Get the stored basename for a collider, or derive and store it.

    The basename is stored as a custom property (``panthor_basename``) on the
    object so that numeric parts of the basename (e.g. ``mymesh_02``) are never
    accidentally stripped.  When no stored value exists, the full name after the
    prefix is taken as the basename (imported colliders have no enumeration
    suffix yet).
    """
    stored = obj.get("panthor_basename")
    if stored:
        return stored

    # First time: use everything after the prefix as the basename.
    # This is correct for freshly imported or newly created colliders
    # which have not yet been enumerated.
    remaining = obj.name[len(prefix):]
    obj["panthor_basename"] = remaining
    return remaining


def rename_and_enumerate_colliders():
    """Rename boxes from UCX to UBX and enumerate suffixes."""
    colliders = []
    prefixes = (
        COLLIDER_PREFIX_BOX,
        COLLIDER_PREFIX_CONVEX,
        COLLIDER_PREFIX_SPHERE,
        COLLIDER_PREFIX_CAPSULE,
        COLLIDER_PREFIX_CYLINDER,
    )

    for obj in bpy.context.scene.objects:
        if obj.type == "MESH" and any(obj.name.startswith(p) for p in prefixes):
            colliders.append(obj)

    # Dictionary to keep track of counts per base name
    base_counts = {}

    for obj in colliders:
        # Parse base name
        prefix = ""
        for p in prefixes:
            if obj.name.startswith(p):
                prefix = p
                break

        if prefix:
            base_name = _get_collider_basename(obj, prefix)
            key = f"{prefix}{base_name}"

            if key not in base_counts:
                base_counts[key] = 0
                obj.name = key
            else:
                base_counts[key] += 1
                obj.name = f"{key}_{base_counts[key]:02d}"


def _get_bounding_box_info(obj: Object) -> tuple[mathutils.Vector, mathutils.Vector]:
    """Return (center, dimensions) for *obj* in world space."""
    corners = [obj.matrix_world @ mathutils.Vector(c) for c in obj.bound_box]
    xs = [c.x for c in corners]
    ys = [c.y for c in corners]
    zs = [c.z for c in corners]

    min_v = mathutils.Vector((min(xs), min(ys), min(zs)))
    max_v = mathutils.Vector((max(xs), max(ys), max(zs)))
    center = (min_v + max_v) / 2.0
    dims = max_v - min_v
    return center, dims


class PanthorOTFixColliders(Operator):
    """Rebuild and clean up collider geometry."""

    bl_idname: ClassVar[str] = "panthor.fix_colliders"
    bl_label: ClassVar[str] = "Fix Colliders"
    bl_options: ClassVar[set[str]] = {"REGISTER", "UNDO"}

    def execute(self, context):
        """Execute fix colliders."""
        prefixes = (
            COLLIDER_PREFIX_BOX,
            COLLIDER_PREFIX_CONVEX,
            COLLIDER_PREFIX_SPHERE,
            COLLIDER_PREFIX_CAPSULE,
            COLLIDER_PREFIX_CYLINDER,
        )

        targets = [obj for obj in context.scene.objects if obj.type == "MESH" and any(obj.name.startswith(p) for p in prefixes)]

        for obj in targets:
            _rebuild_collider_geometry(obj)

        rename_and_enumerate_colliders()
        self.report({"INFO"}, "Colliders rebuilt and enumerated.")
        return {"FINISHED"}


class PanthorOTAddCollider(Operator):
    """Add a primitive collider fitted to the active object's bounding box."""

    bl_idname: ClassVar[str] = "panthor.add_collider"
    bl_label: ClassVar[str] = "Add Collider"
    bl_options: ClassVar[set[str]] = {"REGISTER", "UNDO"}

    collider_type: bpy.props.EnumProperty(
        items=[
            ("BOX", "Box", ""),
            ("CONVEX", "Convex", ""),
            ("SPHERE", "Sphere", ""),
            ("CAPSULE", "Capsule", ""),
            ("CYLINDER", "Cylinder", ""),
        ]
    )

    def execute(self, context: Context):
        """Add primitive collider fitted to the target mesh."""
        active = context.active_object
        if not active or active.type != "MESH":
            self.report({"WARNING"}, "Please select a mesh object first.")
            return {"CANCELLED"}

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

        # Create a temp object and use our fix logic to build it
        mesh = bpy.data.meshes.new("TempCollider")
        new_obj = bpy.data.objects.new("TempCollider", mesh)
        context.collection.objects.link(new_obj)

        # Add a dummy vertex at the corners to define the bounds for the rebuilder
        bm = bmesh.new()
        half = dims / 2
        for x in (-half.x, half.x):
            for y in (-half.y, half.y):
                for z in (-half.z, half.z):
                    bm.verts.new(center + mathutils.Vector((x, y, z)))
        bm.to_mesh(mesh)
        bm.free()

        prefix = {
            "BOX": COLLIDER_PREFIX_BOX,
            "CONVEX": COLLIDER_PREFIX_CONVEX,
            "SPHERE": COLLIDER_PREFIX_SPHERE,
            "CAPSULE": COLLIDER_PREFIX_CAPSULE,
            "CYLINDER": COLLIDER_PREFIX_CYLINDER,
        }[self.collider_type]

        # Store the basename so rename_and_enumerate_colliders never strips it
        new_obj["panthor_basename"] = base_name

        new_obj.name = f"{prefix}{base_name}"
        _rebuild_collider_geometry(new_obj)

        # Link to the active object's collection
        active_cols = active.users_collection
        if active_cols:
            for c in new_obj.users_collection:
                if c != active_cols[0]:
                    c.objects.unlink(new_obj)
            if new_obj.name not in active_cols[0].objects:
                active_cols[0].objects.link(new_obj)

        rename_and_enumerate_colliders()
        _refresh_collider_list(context)

        return {"FINISHED"}


class PanthorOTValidateColliders(Operator):
    """Check colliders for errors."""

    bl_idname: ClassVar[str] = "panthor.validate_colliders"
    bl_label: ClassVar[str] = "Validate Colliders"
    bl_options: ClassVar[set[str]] = {"REGISTER"}

    def execute(self, context):
        """Validate all colliders."""
        prefixes = (
            COLLIDER_PREFIX_BOX,
            COLLIDER_PREFIX_CONVEX,
            COLLIDER_PREFIX_SPHERE,
            COLLIDER_PREFIX_CAPSULE,
            COLLIDER_PREFIX_CYLINDER,
        )
        errors = []

        for obj in bpy.context.scene.objects:
            if obj.type == "MESH" and any(obj.name.startswith(p) for p in prefixes):
                # 1. Check Transform
                if tuple(round(v, 4) for v in obj.location) != (0.0, 0.0, 0.0):
                    errors.append(f"{obj.name}: Origin not at (0,0,0).")
                if tuple(round(v, 4) for v in obj.scale) != (1.0, 1.0, 1.0):
                    errors.append(f"{obj.name}: Scale not applied.")
                if tuple(round(v, 4) for v in obj.rotation_euler) != (0.0, 0.0, 0.0):
                    errors.append(f"{obj.name}: Rotation not applied.")

                # 2. Check Vertex Count
                if len(obj.data.vertices) > MAX_VERTS_COLLIDER:
                    errors.append(f"{obj.name}: Vertices exceed {MAX_VERTS_COLLIDER}.")

                # 3. Check Geometry Specifics
                bm = bmesh.new()
                bm.from_mesh(obj.data)

                # UCX Specific checks
                if obj.name.startswith(COLLIDER_PREFIX_CONVEX):
                    # Manifold
                    non_manifold = [e for e in bm.edges if not e.is_manifold]
                    if non_manifold:
                        errors.append(f"{obj.name}: Contains {len(non_manifold)} non-manifold edges.")

                    # Planar and Convex faces
                    for f in bm.faces:
                        if not f.is_planar:
                            errors.append(f"{obj.name}: Non-planar face detected.")
                            break
                        if not f.is_convex:
                            errors.append(f"{obj.name}: Non-convex face detected.")
                            break

                # Primitive Specific checks (Simple dimension checks)
                verts_local = [v.co for v in bm.verts]
                if verts_local:
                    xs = [v.x for v in verts_local]
                    ys = [v.y for v in verts_local]
                    zs = [v.z for v in verts_local]
                    dx = max(xs) - min(xs)
                    dy = max(ys) - min(ys)
                    dz = max(zs) - min(zs)

                    if obj.name.startswith(COLLIDER_PREFIX_SPHERE):
                        if not (round(dx, 3) == round(dy, 3) == round(dz, 3)):
                            errors.append(f"{obj.name}: Sphere must have uniform dimensions (current: {dx:.2f}, {dy:.2f}, {dz:.2f}).")
                    elif obj.name.startswith(COLLIDER_PREFIX_CYLINDER) or obj.name.startswith(COLLIDER_PREFIX_CAPSULE):
                        if round(dx, 3) != round(dy, 3):
                            errors.append(f"{obj.name}: XY dimensions must be equal (current: X={dx:.2f}, Y={dy:.2f}).")

                bm.free()

        if errors:
            for e in errors:
                self.report({"ERROR"}, e)
        else:
            self.report({"INFO"}, "All colliders validated successfully.")

        return {"FINISHED"}


class PanthorColliderItem(PropertyGroup):
    """Property group for UIList collider items."""

    obj: PointerProperty(type=bpy.types.Object)


def _update_hide_colliders(self, context):
    """Toggle visibility of collider objects."""
    scene = context.scene
    hide = scene.panthor_hide_colliders
    prefixes = ("UBX_", "UCX_", "USP_", "UCS_", "UCL_")

    for obj in scene.objects:
        if obj.type == "MESH" and any(obj.name.startswith(p) for p in prefixes):
            obj.hide_viewport = hide
            obj.hide_render = hide


def _refresh_collider_list(context):
    """Refresh the collider list UI."""
    scene = context.scene
    scene.panthor_colliders.clear()
    prefixes = ("UBX_", "UCX_", "USP_", "UCS_", "UCL_")

    for obj in scene.objects:
        if obj.type == "MESH" and any(obj.name.startswith(p) for p in prefixes):
            item = scene.panthor_colliders.add()
            item.obj = obj


class PanthorOTRefreshColliders(Operator):
    """Refresh the collider list."""

    bl_idname: ClassVar[str] = "panthor.refresh_colliders"
    bl_label: ClassVar[str] = "Refresh Colliders"
    bl_options: ClassVar[set[str]] = {"REGISTER"}

    def execute(self, context):
        """Execute refresh colliders."""
        _refresh_collider_list(context)
        return {"FINISHED"}


class PanthorOTRemoveCollider(Operator):
    """Remove the selected collider and delete the object."""

    bl_idname: ClassVar[str] = "panthor.remove_collider"
    bl_label: ClassVar[str] = "Remove Collider"
    bl_options: ClassVar[set[str]] = {"REGISTER", "UNDO"}

    def execute(self, context):
        """Execute remove collider."""
        scene = context.scene
        idx = scene.panthor_collider_index

        if idx < 0 or idx >= len(scene.panthor_colliders):
            self.report({"WARNING"}, "No collider selected.")
            return {"CANCELLED"}

        item = scene.panthor_colliders[idx]
        obj = item.obj

        if not obj:
            scene.panthor_colliders.remove(idx)
            return {"CANCELLED"}

        bpy.data.objects.remove(obj, do_unlink=True)
        _refresh_collider_list(context)

        scene.panthor_collider_index = min(idx, max(0, len(scene.panthor_colliders) - 1))

        return {"FINISHED"}


class PanthorOTSetupCollider(Operator):
    """Setup Enfusion game material and layer preset for the collider."""

    bl_idname: ClassVar[str] = "panthor.setup_collider"
    bl_label: ClassVar[str] = "Setup Collider"
    bl_options: ClassVar[set[str]] = {"REGISTER", "UNDO"}

    collider_name: bpy.props.StringProperty()

    def execute(self, context):
        """Execute collider setup operator."""
        obj = bpy.data.objects.get(self.collider_name)
        if not obj:
            self.report({"WARNING"}, f"Collider {self.collider_name} not found.")
            return {"CANCELLED"}

        # Check if EBT is available
        if not (hasattr(bpy.ops, "ebt") and hasattr(bpy.ops.ebt, "collider_setup")):
            self.report({"ERROR"}, "EBT (Arma Reforger Workbench addon) is not installed or enabled.")
            return {"CANCELLED"}

        # Select only this object and make it active
        if context.active_object and context.active_object.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT", toggle=False)

        # Unhide if hidden to prevent Blender select_set RuntimeError
        if obj.hide_viewport:
            obj.hide_viewport = False

        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        context.view_layer.objects.active = obj

        # Call the ebt.collider_setup operator
        try:
            bpy.ops.ebt.collider_setup("INVOKE_DEFAULT")
        except RuntimeError:
            self.report(
                {"ERROR"},
                "Enfusion Workbench is not running. Start the Workbench and try again.",
            )
            return {"CANCELLED"}
        return {"FINISHED"}


class PanthorOTAddWeightedNormal(Operator):
    """Add a Weighted Normal modifier with Keep Sharp enabled and weight 100."""

    bl_idname: ClassVar[str] = "panthor.add_weighted_normal"
    bl_label: ClassVar[str] = "Add Weighted Normal"
    bl_options: ClassVar[set[str]] = {"REGISTER", "UNDO"}

    collider_name: bpy.props.StringProperty()

    def execute(self, context):
        """Execute add weighted normal modifier."""
        obj = bpy.data.objects.get(self.collider_name)
        if not obj:
            self.report({"WARNING"}, f"Collider {self.collider_name} not found.")
            return {"CANCELLED"}

        # Don't add duplicate
        if obj.modifiers.find("Weighted Normal") != -1:
            self.report({"INFO"}, f"{obj.name} already has a Weighted Normal modifier.")
            return {"CANCELLED"}

        mod = obj.modifiers.new(name="Weighted Normal", type="WEIGHTED_NORMAL")
        mod.keep_sharp = True
        mod.weight = 100

        self.report({"INFO"}, f"Added Weighted Normal modifier to {obj.name}.")
        return {"FINISHED"}


def register():
    """Register collider operators."""
    bpy.utils.register_class(PanthorOTFixColliders)
    bpy.utils.register_class(PanthorOTAddCollider)
    bpy.utils.register_class(PanthorOTValidateColliders)
    bpy.utils.register_class(PanthorColliderItem)
    bpy.types.Scene.panthor_colliders = CollectionProperty(type=PanthorColliderItem)
    bpy.types.Scene.panthor_collider_index = IntProperty()
    bpy.types.Scene.panthor_hide_colliders = BoolProperty(
        name="Hide Colliders",
        description="Hide all collider objects in the viewport",
        default=False,
        update=_update_hide_colliders,
    )
    bpy.utils.register_class(PanthorOTRefreshColliders)
    bpy.utils.register_class(PanthorOTRemoveCollider)
    bpy.utils.register_class(PanthorOTSetupCollider)
    bpy.utils.register_class(PanthorOTAddWeightedNormal)


def unregister():
    """Unregister collider operators."""
    bpy.utils.unregister_class(PanthorOTAddWeightedNormal)
    bpy.utils.unregister_class(PanthorOTSetupCollider)
    bpy.utils.unregister_class(PanthorOTRemoveCollider)
    bpy.utils.unregister_class(PanthorOTRefreshColliders)
    del bpy.types.Scene.panthor_hide_colliders
    del bpy.types.Scene.panthor_collider_index
    del bpy.types.Scene.panthor_colliders
    bpy.utils.unregister_class(PanthorColliderItem)
    bpy.utils.unregister_class(PanthorOTValidateColliders)
    bpy.utils.unregister_class(PanthorOTAddCollider)
    bpy.utils.unregister_class(PanthorOTFixColliders)
