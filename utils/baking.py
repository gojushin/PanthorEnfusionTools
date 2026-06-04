"""
Baking pipeline for Bake & Remap Materials.

Isolated from operators/textures.py so the core logic can be tested and
maintained independently of Blender operator boilerplate.

Key hardening: every bake run on a multi-material (joined) mesh uses
**material slot isolation** – all non-target slots are temporarily replaced
with a blank placeholder material that has zero image-texture nodes.  This
is the only reliable way to stop Blender from writing bake data into a
stray active image node that lives in another material's tree.

The previous mitigation (setting ``nodes.active = None``) was insufficient
because Blender may fall back to any selected or previously-active
``ShaderNodeTexImage`` node in the tree regardless of the ``nodes.active``
pointer.  Using a blank material eliminates the problem at the source.
"""

import os

import bpy
import numpy as np
from bpy.types import Material

from .constants import SOLID_IMAGE_SIZE


# ── UV helpers ────────────────────────────────────────────────────────────────


def _ensure_uv_map(obj: bpy.types.Object) -> bool:
    """
    Ensure *obj* has at least one UV map.

    When none exists, a Smart UV Project is performed so that baking has valid
    UV coordinates.  Returns True when a new map was created.
    """
    if obj.data.uv_layers:
        return False
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=66.0, island_margin=0.02)
    bpy.ops.object.mode_set(mode="OBJECT")
    return True


# ── Image helpers ─────────────────────────────────────────────────────────────


def _create_solid_image(name: str, color_rgba: tuple) -> bpy.types.Image:
    """Create a flat single-colour packed Image without baking."""
    existing = bpy.data.images.get(name)
    if existing:
        bpy.data.images.remove(existing)
    img = bpy.data.images.new(name, width=SOLID_IMAGE_SIZE, height=SOLID_IMAGE_SIZE, alpha=True)
    pix = np.tile(np.array(color_rgba, dtype=np.float32), SOLID_IMAGE_SIZE * SOLID_IMAGE_SIZE)
    img.pixels.foreach_set(pix)
    img.update()
    img.pack()
    return img


def _read_resized(src: bpy.types.Image, target_h: int, target_w: int) -> np.ndarray:
    """
    Read *src* pixels into a numpy array and resize to *(target_h, target_w)* via
    nearest-neighbour sampling when the source dimensions differ from the target.

    Guarantees that solid images created by ``_create_solid_image`` (which may
    have been generated at a smaller resolution) are always upscaled to match the
    packed map size before channels are extracted.
    """
    arr = np.empty(src.size[0] * src.size[1] * src.channels, dtype=np.float32)
    src.pixels.foreach_get(arr)
    arr = arr.reshape((src.size[1], src.size[0], src.channels))
    if arr.shape[0] != target_h or arr.shape[1] != target_w:
        ri = np.linspace(0, arr.shape[0] - 1, target_h).astype(int)
        ci = np.linspace(0, arr.shape[1] - 1, target_w).astype(int)
        arr = arr[ri[:, None], ci]
    return arr


def _pack_bcr_from_parts(
    name: str,
    res: int,
    base_color_img: bpy.types.Image | None,
    flat_base_color: list,
    roughness_img: bpy.types.Image | None,
    flat_roughness: float,
) -> bpy.types.Image:
    """
    Channel-pack a BCR image:
      - RGB = base colour (baked or flat *flat_base_color*)
      - A   = roughness   (baked or constant *flat_roughness*)

    Output resolution is the largest supplied image's width; falls back to *res*
    when no source images are provided.
    """
    existing = bpy.data.images.get(name)
    if existing:
        bpy.data.images.remove(existing)

    target = max(
        (img.size[0] for img in (base_color_img, roughness_img) if img is not None),
        default=res,
    )

    pix = np.empty((target, target, 4), dtype=np.float32)

    if base_color_img is not None:
        src = _read_resized(base_color_img, target, target)
        pix[:, :, 0] = src[:, :, 0]
        pix[:, :, 1] = src[:, :, 1]
        pix[:, :, 2] = src[:, :, 2]
    else:
        pix[:, :, 0] = flat_base_color[0]
        pix[:, :, 1] = flat_base_color[1]
        pix[:, :, 2] = flat_base_color[2]

    if roughness_img is not None:
        src_r = _read_resized(roughness_img, target, target)
        pix[:, :, 3] = src_r[:, :, 0]
    else:
        pix[:, :, 3] = flat_roughness

    img = bpy.data.images.new(name, width=target, height=target, alpha=True)
    img.pixels.foreach_set(pix.ravel())
    img.update()
    img.pack()
    return img


def _pack_nmo_from_parts(
    name: str,
    res: int,
    normal_img: bpy.types.Image | None,
    metallic_img: bpy.types.Image | None,
    flat_metallic: float,
) -> bpy.types.Image:
    """
    Channel-pack an NMO image:
      - RG  = normal map XY (baked or flat 0.5, 0.5)
      - B   = metallic      (baked or constant *flat_metallic*)
      - A   = 1.0           (AO default – not baked in this pass)

    Output resolution is the largest supplied image's width; falls back to *res*
    when no source images are provided.
    """
    existing = bpy.data.images.get(name)
    if existing:
        bpy.data.images.remove(existing)

    target = max(
        (img.size[0] for img in (normal_img, metallic_img) if img is not None),
        default=res,
    )

    pix = np.empty((target, target, 4), dtype=np.float32)
    pix[:, :, 3] = 1.0  # AO channel – default full white

    if normal_img is not None:
        src = _read_resized(normal_img, target, target)
        pix[:, :, 0] = src[:, :, 0]
        pix[:, :, 1] = src[:, :, 1]
    else:
        pix[:, :, 0] = 0.5
        pix[:, :, 1] = 0.5

    if metallic_img is not None:
        src_m = _read_resized(metallic_img, target, target)
        pix[:, :, 2] = src_m[:, :, 0]
    else:
        pix[:, :, 2] = flat_metallic

    img = bpy.data.images.new(name, width=target, height=target, alpha=True)
    img.pixels.foreach_set(pix.ravel())
    img.update()
    img.pack()
    return img


# ── Material slot isolation ───────────────────────────────────────────────────


def _make_blank_material() -> bpy.types.Material:
    """
    Create a throwaway material with only a Material Output node and no image nodes.

    When this material occupies a slot on the bake object, Blender finds no
    ``ShaderNodeTexImage`` to write into for polygons of that slot, so those
    polygons are skipped entirely during baking.  This is the hard guarantee
    that prevents cross-slot contamination on joined (multi-material) meshes.
    """
    mat = bpy.data.materials.new(name="_PTR_BlankBake_")
    mat.use_nodes = True
    mat.node_tree.nodes.clear()
    mat.node_tree.nodes.new("ShaderNodeOutputMaterial")
    return mat


def _save_and_isolate_slots(
    obj: bpy.types.Object,
    target_mat: Material,
    blank_mat: Material,
) -> dict[int, Material]:
    """
    Replace every material slot on *obj* that is NOT *target_mat* with *blank_mat*.

    Returns a dict mapping slot index → original material so the caller can
    restore them afterwards with ``_restore_slots``.
    """
    saved: dict[int, Material] = {}
    for i, slot in enumerate(obj.material_slots):
        if slot.material is not None and slot.material is not target_mat:
            saved[i] = slot.material
            slot.material = blank_mat
    return saved


def _restore_slots(obj: bpy.types.Object, saved: dict[int, Material]) -> None:
    """Restore material slots that were previously replaced by ``_save_and_isolate_slots``."""
    for i, original_mat in saved.items():
        obj.material_slots[i].material = original_mat


# ── Core bake channel ─────────────────────────────────────────────────────────


def _bake_channel(
    mat: Material,
    img: bpy.types.Image,
    bake_type: str,
    pass_filter: set | None = None,
    emit_source_socket=None,
) -> bool:
    """
    Bake *bake_type* from the currently active object's *mat* into *img*.

    A temporary ``ShaderNodeTexImage`` node is inserted and made active, the
    bake runs, and the node is removed — leaving the pixel data in *img*.

    When *emit_source_socket* is provided its upstream value is temporarily
    wired through an Emission shader so arbitrary sockets (e.g. Metallic,
    Alpha) can be captured via ``type='EMIT'``.

    This function does NOT perform slot isolation itself; callers must isolate
    the object's non-target material slots before calling (see
    ``_save_and_isolate_slots`` / ``_restore_slots``).
    """
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # Insert bake-target node
    bake_node = nodes.new("ShaderNodeTexImage")
    bake_node.image = img
    for n in nodes:
        n.select = False
    bake_node.select = True
    nodes.active = bake_node

    # Optional emit-trick setup
    emit_node = None
    output_node = None
    saved_output_from = None

    if emit_source_socket is not None:
        for n in nodes:
            if n.type == "OUTPUT_MATERIAL" and n.is_active_output:
                output_node = n
                break
        if output_node is None:
            nodes.remove(bake_node)
            return False
        if output_node.inputs[0].is_linked:
            saved_output_from = output_node.inputs[0].links[0].from_socket
        emit_node = nodes.new("ShaderNodeEmission")
        links.new(emit_source_socket, emit_node.inputs["Color"])
        links.new(emit_node.outputs[0], output_node.inputs[0])

    # Bake
    ok = False
    try:
        kwargs: dict = {"type": bake_type}
        if pass_filter:
            kwargs["pass_filter"] = pass_filter
        bpy.ops.object.bake(**kwargs)
        ok = True
    except Exception as exc:
        print(f"[PanthorTools] Bake '{bake_type}' failed for '{mat.name}': {exc}")
    finally:
        if emit_node:
            nodes.remove(emit_node)
        if output_node and saved_output_from:
            links.new(saved_output_from, output_node.inputs[0])
        nodes.remove(bake_node)

    return ok


# ── ENF / BSDF material assignment ───────────────────────────────────────────


def save_texture_to_workbench(img: bpy.types.Image, workbench_path: str) -> str:
    """Save a Blender image to the workbench path as PNG and return the absolute file path."""
    os.makedirs(workbench_path, exist_ok=True)
    file_path = os.path.join(workbench_path, f"{img.name}.png")
    img.filepath_raw = file_path
    img.file_format = "PNG"
    img.save()
    return os.path.abspath(file_path)


def setup_enf_material(material: Material, generated_textures: dict, workbench_path: str) -> bool:
    """Create an ENF MatPBRBasic material and assign BCR/NMO textures via EBT operators."""
    has_ebt = (
        hasattr(bpy.ops, "ebt")
        and hasattr(bpy.ops.ebt, "create_new_enfusion_material")
        and hasattr(bpy.ops.ebt, "load_shader_texture")
    )
    if not has_ebt:
        return False

    try:
        from EnfusionBlenderTools.core.workbench import call_workbench_func as _call_wb
        _wb_available = True
    except ImportError:
        _wb_available = False

    saved_paths: dict[str, str] = {}
    for map_name, img in generated_textures.items():
        saved_paths[map_name] = save_texture_to_workbench(img, workbench_path)

    if _wb_available:
        for saved_path in saved_paths.values():
            try:
                _call_wb("RegisterResource", {"path": [saved_path]})
            except Exception as exc:
                print(f"[PanthorTools] Warning: RegisterResource failed for {saved_path}: {exc}")

    override = bpy.context.copy()
    override["material"] = material

    with bpy.context.temp_override(**override):
        bpy.ops.ebt.create_new_enfusion_material("EXEC_DEFAULT", shader_class="MatPBRBasic")

    if "BCR" in saved_paths:
        try:
            with bpy.context.temp_override(**override):
                bpy.ops.ebt.load_shader_texture(
                    "EXEC_DEFAULT",
                    enf_texture_type="BCRMap",
                    filepath=saved_paths["BCR"],
                )
        except RuntimeError as exc:
            print(f"[PanthorTools] Warning: Could not assign BCRMap for {material.name}: {exc}")

    if "NMO" in saved_paths:
        try:
            with bpy.context.temp_override(**override):
                bpy.ops.ebt.load_shader_texture(
                    "EXEC_DEFAULT",
                    enf_texture_type="NMOMap",
                    filepath=saved_paths["NMO"],
                )
        except RuntimeError as exc:
            print(f"[PanthorTools] Warning: Could not assign NMOMap for {material.name}: {exc}")

    if "A" in saved_paths:
        try:
            with bpy.context.temp_override(**override):
                bpy.ops.ebt.load_shader_texture(
                    "EXEC_DEFAULT",
                    enf_texture_type="OpacityMap",
                    filepath=saved_paths["A"],
                )
        except RuntimeError as exc:
            print(f"[PanthorTools] Warning: Could not assign OpacityMap for {material.name}: {exc}")

    return True


def set_enf_base_color(material: Material, color_rgba: tuple) -> None:
    """
    Set the Base Color slot on an ENF MatPBRBasic material node group.

    EBT builds a node group inside the material where the inner node named
    "Main" holds the shader parameters.  This mirrors the SlotAccessor pattern:
        material.node_tree.nodes[0].node_tree.nodes["Main"].inputs[0]
    """
    try:
        inner_nodes = material.node_tree.nodes[0].node_tree.nodes
        main_node = inner_nodes.get("Main")
        if main_node and main_node.inputs:
            main_node.inputs[0].default_value = color_rgba
    except Exception as exc:
        print(f"[PanthorTools] Could not set ENF base color for '{material.name}': {exc}")


def rebuild_principled_nodes(
    mat: Material,
    generated_textures: dict,
    flat_bc: list,
    flat_r: float,
    flat_m: float,
) -> None:
    """
    Rebuild *mat*'s node tree as a Principled BSDF reading from the packed
    BCR / NMO / A images produced by the bake pipeline.

    Called when ENF materials are not in use.
    """
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    mat.blend_method = "OPAQUE"

    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    out_node = nodes.new("ShaderNodeOutputMaterial")
    out_node.location = (300, 0)
    links.new(bsdf.outputs[0], out_node.inputs[0])

    tex_bcr_node = None

    if "BCR" in generated_textures:
        tex_bcr_node = nodes.new("ShaderNodeTexImage")
        tex_bcr_node.image = generated_textures["BCR"]
        tex_bcr_node.location = (-600, 200)
        if "NMO" not in generated_textures:
            links.new(tex_bcr_node.outputs[0], bsdf.inputs["Base Color"])
        links.new(tex_bcr_node.outputs["Alpha"], bsdf.inputs["Roughness"])
    else:
        bsdf.inputs["Base Color"].default_value = (flat_bc[0], flat_bc[1], flat_bc[2], 1.0)
        bsdf.inputs["Roughness"].default_value = flat_r
        bsdf.inputs["Metallic"].default_value = flat_m

    if "NMO" in generated_textures:
        tex_nmo_node = nodes.new("ShaderNodeTexImage")
        tex_nmo_node.image = generated_textures["NMO"]
        tex_nmo_node.location = (-600, -100)
        tex_nmo_node.image.colorspace_settings.name = "Non-Color"

        sep = nodes.new("ShaderNodeSeparateColor")
        sep.location = (-400, -100)
        links.new(tex_nmo_node.outputs[0], sep.inputs[0])
        links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])

        comb = nodes.new("ShaderNodeCombineColor")
        comb.location = (-200, -100)
        links.new(sep.outputs["Red"], comb.inputs["Red"])
        links.new(sep.outputs["Green"], comb.inputs["Green"])
        comb.inputs["Blue"].default_value = 0.5

        norm_map = nodes.new("ShaderNodeNormalMap")
        norm_map.location = (0, -200)
        links.new(comb.outputs[0], norm_map.inputs["Color"])
        links.new(norm_map.outputs[0], bsdf.inputs["Normal"])

        if tex_bcr_node is not None:
            mix = nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.blend_type = "MULTIPLY"
            mix.inputs["Factor"].default_value = 1.0
            mix.location = (-200, 200)
            links.new(tex_bcr_node.outputs[0], mix.inputs["A"])
            links.new(tex_nmo_node.outputs["Alpha"], mix.inputs["B"])
            links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])

    if "A" in generated_textures:
        tex_a_node = nodes.new("ShaderNodeTexImage")
        tex_a_node.image = generated_textures["A"]
        tex_a_node.location = (-600, -400)
        tex_a_node.image.colorspace_settings.name = "Non-Color"
        links.new(tex_a_node.outputs[0], bsdf.inputs["Alpha"])
        mat.blend_method = "CLIP"


# ── Public API ────────────────────────────────────────────────────────────────


def bake_and_remap_material(
    context: bpy.types.Context,
    obj: bpy.types.Object,
    mat: Material,
    bsdf: bpy.types.ShaderNode,
    res: int,
    can_use_enf: bool,
    workbench_path: str,
) -> None:
    """
    Full bake-and-remap pipeline for a single material.

    Steps:
    1. Inspect Principled BSDF inputs to determine what needs baking.
    2. Isolate the object's material slots (joined-mesh guard) then bake each
       linked input channel; create solid images for flat non-default values.
    3. Channel-pack intermediates into BCR (RGB + roughness) and
       NMO (normal XY + metallic + AO) images.
    4. Assign via ENF materials (if available) or rebuild a Principled BSDF
       node graph.

    Slot isolation (step 2) works by temporarily replacing every non-target
    material slot with a blank placeholder material that contains no
    ``ShaderNodeTexImage`` nodes.  Blender therefore has no image to write
    into for those slots, preventing normal / diffuse data from leaking into
    the wrong material's textures on multi-material (joined) meshes.
    """

    # ── 1. Inspect BSDF inputs ────────────────────────────────────────────────
    bc_socket = bsdf.inputs["Base Color"]
    r_socket  = bsdf.inputs["Roughness"]
    m_socket  = bsdf.inputs["Metallic"]
    n_socket  = bsdf.inputs["Normal"]
    a_socket  = bsdf.inputs["Alpha"]

    bc_linked = bc_socket.is_linked
    r_linked  = r_socket.is_linked
    m_linked  = m_socket.is_linked
    n_linked  = n_socket.is_linked
    a_linked  = a_socket.is_linked

    flat_bc = list(bc_socket.default_value)
    flat_r  = float(r_socket.default_value)
    flat_m  = float(m_socket.default_value)
    flat_a  = float(a_socket.default_value)

    r_is_default = (not r_linked) and abs(flat_r - 0.5) < 1e-3
    m_is_default = (not m_linked) and abs(flat_m - 0.0) < 1e-3
    a_is_default = (not a_linked) and abs(flat_a - 1.0) < 1e-3

    bcr_needed = bc_linked or (not r_is_default)
    nmo_needed = n_linked  or (not m_is_default)
    a_needed   = not a_is_default

    needs_baking = bc_linked or r_linked or m_linked or n_linked or a_linked

    # ── 2. Bake per-channel images ────────────────────────────────────────────
    baked_bc = baked_r = baked_m = baked_n = baked_a = None

    if needs_baking:
        # Set up bake object
        for o in bpy.data.objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode="OBJECT")
        _ensure_uv_map(obj)

        def _new_bake_img(suffix: str) -> bpy.types.Image:
            iname = f"PTR_{mat.name}_{suffix}"
            existing = bpy.data.images.get(iname)
            if existing:
                bpy.data.images.remove(existing)
            return bpy.data.images.new(iname, width=res, height=res, alpha=True)

        # ── Isolate non-target slots for the entire baking section ────────────
        # A single blank material is reused across all channel bakes for this
        # material.  Slots are restored once all passes are complete.
        blank_mat = None
        saved_slots: dict[int, Material] = {}
        other_slots = [
            s for s in obj.material_slots
            if s.material is not None and s.material is not mat
        ]
        if other_slots:
            blank_mat = _make_blank_material()
            saved_slots = _save_and_isolate_slots(obj, mat, blank_mat)

        try:
            # Base Colour
            if bc_linked:
                baked_bc = _new_bake_img("BakeBC")
                if _bake_channel(mat, baked_bc, "DIFFUSE", pass_filter={"COLOR"}):
                    baked_bc.pack()
                else:
                    bpy.data.images.remove(baked_bc)
                    baked_bc = None

            # Roughness
            if r_linked:
                baked_r = _new_bake_img("BakeR")
                if _bake_channel(mat, baked_r, "ROUGHNESS"):
                    baked_r.pack()
                else:
                    bpy.data.images.remove(baked_r)
                    baked_r = None

            # Metallic – no dedicated pass; use the Emission trick
            if m_linked:
                baked_m = _new_bake_img("BakeM")
                if _bake_channel(mat, baked_m, "EMIT",
                                 emit_source_socket=m_socket.links[0].from_socket):
                    baked_m.pack()
                else:
                    bpy.data.images.remove(baked_m)
                    baked_m = None

            # Normal Map
            if n_linked:
                baked_n = _new_bake_img("BakeN")
                if _bake_channel(mat, baked_n, "NORMAL"):
                    baked_n.pack()
                else:
                    bpy.data.images.remove(baked_n)
                    baked_n = None

            # Alpha – use the Emission trick
            if a_linked:
                baked_a = _new_bake_img("BakeA")
                if _bake_channel(mat, baked_a, "EMIT",
                                 emit_source_socket=a_socket.links[0].from_socket):
                    baked_a.pack()
                else:
                    bpy.data.images.remove(baked_a)
                    baked_a = None

        finally:
            # Always restore slots – even if a bake raised an exception
            if saved_slots:
                _restore_slots(obj, saved_slots)
            if blank_mat is not None:
                bpy.data.materials.remove(blank_mat)

    # Non-linked but non-default scalars → solid images for correct BCR/NMO encoding
    if (not r_linked) and (not r_is_default) and (baked_r is None):
        baked_r = _create_solid_image(f"PTR_{mat.name}_BakeR", (flat_r, flat_r, flat_r, 1.0))

    if (not m_linked) and (not m_is_default) and (baked_m is None):
        baked_m = _create_solid_image(f"PTR_{mat.name}_BakeM", (flat_m, flat_m, flat_m, 1.0))

    if (not a_linked) and (not a_is_default) and (baked_a is None):
        baked_a = _create_solid_image(f"PTR_{mat.name}_BakeA", (flat_a, flat_a, flat_a, 1.0))

    # ── 3. Channel-pack into BCR / NMO ───────────────────────────────────────
    generated_textures: dict = {}

    if bcr_needed:
        generated_textures["BCR"] = _pack_bcr_from_parts(
            f"PTR_{mat.name}_BCR", res, baked_bc, flat_bc, baked_r, flat_r
        )

    if nmo_needed:
        generated_textures["NMO"] = _pack_nmo_from_parts(
            f"PTR_{mat.name}_NMO", res, baked_n, baked_m, flat_m
        )

    if a_needed and baked_a is not None:
        generated_textures["A"] = baked_a

    # Remove intermediate bake / solid images – the packed BCR/NMO have absorbed them
    for tmp in (baked_bc, baked_r, baked_m, baked_n):
        if tmp is not None and bpy.data.images.get(tmp.name):
            bpy.data.images.remove(tmp)
    # baked_a is kept when stored under generated_textures["A"]

    # ── 4. Assign: ENF material path or Principled BSDF fallback ─────────────
    if can_use_enf:
        success = setup_enf_material(mat, generated_textures, workbench_path)
        if success:
            if not bc_linked and "BCR" not in generated_textures:
                set_enf_base_color(mat, (flat_bc[0], flat_bc[1], flat_bc[2], 1.0))
        return

    rebuild_principled_nodes(mat, generated_textures, flat_bc, flat_r, flat_m)