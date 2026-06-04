"""Texture operators."""

import os
from typing import ClassVar

import bpy
import numpy as np
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Material, Operator, PropertyGroup

from ..utils.constants import TEXTURE_SUFFIXES, SOLID_IMAGE_SIZE
from ..utils.texture_presets import TEXTURE_PRESETS
from ..utils.texture_processing import generate_texture


class PanthorTextureImportItem(PropertyGroup):
    """Property group for a texture import item."""

    filename: StringProperty(name="Texture")
    filepath: StringProperty()

    texture_type: EnumProperty(
        name="Texture Type",
        items=[
            ("BASECOLOR", "BASECOLOR", "Base color/Albedo"),
            ("NORMAL", "NORMAL", "Normal Map"),
            ("ORM", "ORM", "Occlusion Roughness Metallic"),
            ("ROUGHNESS", "ROUGHNESS", "Roughness Map"),
            ("METALNESS", "METALNESS", "Metalness Map"),
            ("OPACITY", "OPACITY", "Opacity/Alpha Map"),
            ("MASK", "MASK", "Mask Map"),
            ("AO", "AO", "Ambient Occlusion"),
        ],
    )

    def get_source_preset_items(self, context):
        """Get preset items for the source dropdown."""
        from ..utils.texture_presets import get_preset_items

        return get_preset_items(self, context)

    source_preset: EnumProperty(
        name="Source",
        items=get_source_preset_items,
    )

    def get_material_items(self, context):
        """Get material items for the target dropdown."""
        items = [("NONE", "None", "Do not assign")]
        for mat in bpy.data.materials:
            items.append((mat.name, mat.name, f"Assign to {mat.name}"))
        return items

    target_material: EnumProperty(
        name="Target Material",
        items=get_material_items,
    )


class PanthorTextureItem(PropertyGroup):
    """Property group for a texture item."""

    img: PointerProperty(type=bpy.types.Image)


def _refresh_texture_list(context):
    """Refresh the list of relevant textures (embedded and generated)."""
    context.scene.panthor_textures.clear()
    for img in bpy.data.images:
        # Ignore rendering results and viewer nodes to only show actual texture data
        if img.has_data and img.type != "RENDER_RESULT" and img.name != "Render Result":
            item = context.scene.panthor_textures.add()
            item.img = img


def _save_texture_to_workbench(img: bpy.types.Image, workbench_path: str) -> str:
    """Save a Blender image to the workbench path as PNG and return the absolute file path."""
    os.makedirs(workbench_path, exist_ok=True)
    file_path = os.path.join(workbench_path, f"{img.name}.png")
    img.filepath_raw = file_path
    img.file_format = "PNG"
    img.save()
    return os.path.abspath(file_path)


def _setup_enf_material(material: Material, generated_textures: dict, workbench_path: str):
    """Create an ENF MatPBRBasic material and assign BCR/NMO textures via EBT operators."""
    has_ebt = (
        hasattr(bpy.ops, "ebt")
        and hasattr(bpy.ops.ebt, "create_new_enfusion_material")
        and hasattr(bpy.ops.ebt, "load_shader_texture")
    )
    if not has_ebt:
        return False

    # Guard import of Workbench API — only available when EBT (EnfusionBlenderTools) is installed
    try:
        from EnfusionBlenderTools.core.workbench import call_workbench_func as _call_wb
        _wb_available = True
    except ImportError:
        _wb_available = False

    # Save textures to workbench path first
    saved_paths = {}
    for map_name, img in generated_textures.items():
        saved_paths[map_name] = _save_texture_to_workbench(img, workbench_path)

    # Register each saved texture with Workbench so it is known to the running project
    if _wb_available:
        for saved_path in saved_paths.values():
            try:
                _call_wb("RegisterResource", {"path": [saved_path]})
            except Exception as exc:
                print(f"[PanthorTools] Warning: RegisterResource failed for {saved_path}: {exc}")

    # Set context material so EBT operators can find it
    # EBT operators read from context.material — we override via an override context
    override = bpy.context.copy()
    override["material"] = material

    # Create ENF material (MatPBRBasic)
    with bpy.context.temp_override(**override):
        bpy.ops.ebt.create_new_enfusion_material("EXEC_DEFAULT", shader_class="MatPBRBasic")

    # Assign BCR texture
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

    # Assign NMO texture
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

    # Assign Opacity/Alpha texture
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


def process_material_textures_explicit(material: Material, mapping_items: list[PanthorTextureImportItem]):
    """Generate textures based on explicit mapping and set up the material."""
    if not mapping_items:
        return

    from ..utils.texture_processing import is_image_color

    # Use the source preset from the first item as the master preset for this material
    preset_key = mapping_items[0].source_preset
    preset = TEXTURE_PRESETS.get(preset_key)
    if not preset:
        return

    # Determine whether to use ENF materials
    scene = bpy.context.scene
    use_enf = getattr(scene, "panthor_use_enf_materials", False)
    workbench_path = getattr(scene, "panthor_workbench_path", "")
    can_use_enf = use_enf and workbench_path and hasattr(bpy.ops, "ebt")

    # Prepare available images for the generator
    tex_bcr = None
    available_images = {}
    for item in mapping_items:
        if not os.path.exists(item.filepath):
            continue
        try:
            # Load the image if not already loaded
            img = bpy.data.images.load(item.filepath, check_existing=True)
            available_images[item.texture_type] = img
        except Exception:
            continue

    generated_textures = {}
    for map_config in preset["maps"]:
        map_name = map_config["name"]
        tex_name = f"PTR_{material.name}_{map_name}"

        # Determine fallback color based on typical use
        # BCR/A fallback to white (1,1,1,1)
        # NMO fallbacks to flat normal/no metal/no AO (0.5, 0.5, 0, 1)
        fallback = (0.5, 0.5, 0.0, 1.0) if map_name == "NMO" else (1.0, 1.0, 1.0, 1.0)

        # Generate the texture
        img = generate_texture(tex_name, map_config, available_images, fallback_color=fallback)

        # Rule: If the generated texture is entirely the fallback color, do not create/assign it.
        if is_image_color(img, fallback):
            bpy.data.images.remove(img)
            continue

        generated_textures[map_name] = img

    # --- ENF Material path ---
    if can_use_enf:
        success = _setup_enf_material(material, generated_textures, workbench_path)
        if success:
            return

    # --- Principled BSDF fallback path ---
    # Set up material nodes
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    # Reset blend mode to OPAQUE by default, will be changed if Alpha is present
    material.blend_method = "OPAQUE"

    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (300, 0)
    links.new(bsdf.outputs[0], out.inputs[0])

    if "BCR" in generated_textures:
        tex_bcr = nodes.new("ShaderNodeTexImage")
        tex_bcr.image = generated_textures["BCR"]
        tex_bcr.location = (-600, 200)

        # Link base color only if NMO is not there to multiply it with AO
        if "NMO" not in generated_textures:
            links.new(tex_bcr.outputs[0], bsdf.inputs["Base Color"])

        # Alpha channel of BCR is Roughness
        links.new(tex_bcr.outputs["Alpha"], bsdf.inputs["Roughness"])

    if "NMO" in generated_textures:
        tex_nmo = nodes.new("ShaderNodeTexImage")
        tex_nmo.image = generated_textures["NMO"]
        tex_nmo.location = (-600, -100)
        if tex_nmo.image:
            tex_nmo.image.colorspace_settings.name = "Non-Color"

        # NMO: (RG + Grey Channel for Blue = Normal), (B is Metallic), (A is Ambient Occlusion)
        sep = nodes.new("ShaderNodeSeparateColor")
        sep.location = (-400, -100)
        links.new(tex_nmo.outputs[0], sep.inputs[0])

        # Metallic is now B (Blue)
        links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])

        # Normal Map reconstruction (Red -> Red, Green -> Green, Blue -> constant 0.5)
        comb = nodes.new("ShaderNodeCombineColor")
        comb.location = (-200, -100)
        links.new(sep.outputs["Red"], comb.inputs["Red"])
        links.new(sep.outputs["Green"], comb.inputs["Green"])
        comb.inputs["Blue"].default_value = 0.5

        norm_map = nodes.new("ShaderNodeNormalMap")
        norm_map.location = (0, -200)
        links.new(comb.outputs[0], norm_map.inputs["Color"])
        links.new(norm_map.outputs[0], bsdf.inputs["Normal"])

        # Multiply AO (Alpha of NMO) over BaseColor Map (BCR) before it goes to the base color output
        if "BCR" in generated_textures:
            mix = nodes.new("ShaderNodeMix")
            mix.data_type = 'RGBA'
            mix.blend_type = 'MULTIPLY'
            mix.inputs["Factor"].default_value = 1.0
            mix.location = (-200, 200)

            links.new(tex_bcr.outputs[0], mix.inputs["A"])
            links.new(tex_nmo.outputs["Alpha"], mix.inputs["B"])
            links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])

    if "A" in generated_textures:
        tex_a = nodes.new("ShaderNodeTexImage")
        tex_a.image = generated_textures["A"]
        tex_a.location = (-600, -400)
        if tex_a.image:
            tex_a.image.colorspace_settings.name = "Non-Color"

        links.new(tex_a.outputs[0], bsdf.inputs["Alpha"])
        # Set blend mode to Alpha Clip or Blend if opacity is present
        material.blend_method = "CLIP"


class PanthorOTImportTextures(Operator):
    """Import textures from a directory with a configuration dialogue."""

    bl_idname: ClassVar[str] = "panthor.import_textures"
    bl_label: ClassVar[str] = "Import & Remap Textures"
    bl_options: ClassVar[set[str]] = {"REGISTER", "UNDO"}

    directory: StringProperty(subtype="DIR_PATH")
    is_configured: bpy.props.BoolProperty(default=False, options={"SKIP_SAVE"})

    def invoke(self, context, event):
        """Invoke the folder selector."""
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def draw(self, context):
        """Draw the configuration dialogue."""
        layout = self.layout
        layout.label(text="Configure Texture Mapping")

        # Table-like header
        row = layout.row()
        row.label(text="Texture")
        row.label(text="Texture Type")
        row.label(text="Source")
        row.label(text="Target Material")

        for item in context.scene.panthor_texture_import_list:
            row = layout.row()
            row.label(text=item.filename)
            row.prop(item, "texture_type", text="")
            row.prop(item, "source_preset", text="")
            row.prop(item, "target_material", text="")

    def execute(self, context):
        """Execute the remapping or show dialogue."""
        if not self.directory:
            return {"CANCELLED"}

        if not self.is_configured:
            # Step 1: Scan directory and populate import list
            context.scene.panthor_texture_import_list.clear()

            # Detect materials in scene
            mats = [m.name for m in bpy.data.materials]

            for file in os.listdir(self.directory):
                if file.lower().endswith((".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff")):
                    item = context.scene.panthor_texture_import_list.add()
                    item.filename = file
                    item.filepath = os.path.join(self.directory, file)

                    # Best guess detection
                    name_lower = file.lower()

                    # 1. Detect Type
                    for tex_type, suffixes in TEXTURE_SUFFIXES.items():
                        if any(name_lower.endswith(s + os.path.splitext(name_lower)[1]) or f"_{s}" in name_lower for s in suffixes):
                            item.texture_type = tex_type
                            break

                    # 2. Detect Material
                    best_mat = "NONE"
                    for mat_name in mats:
                        if mat_name.lower() in name_lower:
                            best_mat = mat_name
                            break
                    item.target_material = best_mat

                    # 3. Default Source
                    item.source_preset = context.scene.panthor_texture_preset

            self.is_configured = True
            return context.window_manager.invoke_props_dialog(self, width=800)

        # Step 2: Perform remapping based on configured items
        mapping_by_material = {}
        for item in context.scene.panthor_texture_import_list:
            if item.target_material == "NONE":
                continue

            if item.target_material not in mapping_by_material:
                mapping_by_material[item.target_material] = []
            mapping_by_material[item.target_material].append(item)

        for mat_name, items in mapping_by_material.items():
            mat = bpy.data.materials.get(mat_name)
            if mat:
                process_material_textures_explicit(mat, items)

        _refresh_texture_list(context)
        self.is_configured = False
        self.report({"INFO"}, "Textures imported and remapped.")
        return {"FINISHED"}


class PanthorOTRefreshTextures(Operator):
    """Refresh the list of imported textures."""

    bl_idname: ClassVar[str] = "panthor.refresh_textures"
    bl_label: ClassVar[str] = "Refresh Textures"
    bl_options: ClassVar[set[str]] = {"REGISTER", "UNDO"}

    def execute(self, context):
        """Execute refresh."""
        _refresh_texture_list(context)
        return {"FINISHED"}


# ── Bake & Remap Materials – helper functions ─────────────────────────────────


def _find_principled_bsdf(material: Material):
    """Return the first Principled BSDF node found in *material*'s node tree, or None."""
    if not material.use_nodes:
        return None
    for node in material.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            return node
    return None


def _set_enf_base_color(material: Material, color_rgba: tuple) -> None:
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


def _bake_channel(
    mat: Material,
    img: bpy.types.Image,
    bake_type: str,
    pass_filter: set | None = None,
    emit_source_socket=None,
) -> bool:
    """
    Bake *bake_type* from the currently active object's *mat* into *img*.

    A temporary ``ShaderNodeTexImage`` node is inserted, made active, the bake
    runs, and the node is removed – leaving the pixel data in *img*.

    When *emit_source_socket* is provided its upstream value is temporarily
    wired through an Emission shader so arbitrary sockets (e.g. Metallic,
    Alpha) can be captured via ``type='EMIT'``.
    """
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    # ── Insert bake-target node ───────────────────────────────────────────────
    bake_node = nodes.new("ShaderNodeTexImage")
    bake_node.image = img
    for n in nodes:
        n.select = False
    bake_node.select = True
    nodes.active = bake_node

    # ── Optional emit-trick setup ─────────────────────────────────────────────
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

    # ── Bake ──────────────────────────────────────────────────────────────────
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
        # ── Restore and clean up temporary nodes ──────────────────────────────
        if emit_node:
            nodes.remove(emit_node)
        if output_node and saved_output_from:
            links.new(saved_output_from, output_node.inputs[0])
        nodes.remove(bake_node)

    return ok


def _read_resized(src: bpy.types.Image, target_h: int, target_w: int) -> np.ndarray:
    """
    Read *src* pixels into a numpy array and resize to *(target_h, target_w)* via
    nearest-neighbour sampling when the source dimensions differ from the target.

    This guarantees that solid images created by ``_create_solid_image`` (which may
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

    The output resolution is determined by the **largest** input image.  This
    means:
    - If at least one source is a full-resolution baked image, the output is
      packed at that resolution and any smaller images (e.g. solid images from
      ``_create_solid_image``) are upscaled to match.
    - If every source is a solid image (``SOLID_IMAGE_SIZE × SOLID_IMAGE_SIZE``),
      the packed output is also ``SOLID_IMAGE_SIZE × SOLID_IMAGE_SIZE`` — no
      needless upscaling.
    - *res* is used as a fallback only when no source images are provided at all.
    """
    existing = bpy.data.images.get(name)
    if existing:
        bpy.data.images.remove(existing)

    # Derive target resolution from the largest supplied image; fall back to res.
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

    The output resolution is determined by the **largest** input image.  This
    means:
    - If at least one source is a full-resolution baked image, the output is
      packed at that resolution and any smaller images (e.g. solid images from
      ``_create_solid_image``) are upscaled to match.
    - If every source is a solid image (``SOLID_IMAGE_SIZE × SOLID_IMAGE_SIZE``),
      the packed output is also ``SOLID_IMAGE_SIZE × SOLID_IMAGE_SIZE`` — no
      needless upscaling.
    - *res* is used as a fallback only when no source images are provided at all.
    """
    existing = bpy.data.images.get(name)
    if existing:
        bpy.data.images.remove(existing)

    # Derive target resolution from the largest supplied image; fall back to res.
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
        pix[:, :, 2] = src_m[:, :, 0]  # R channel holds the baked scalar
    else:
        pix[:, :, 2] = flat_metallic

    img = bpy.data.images.new(name, width=target, height=target, alpha=True)
    img.pixels.foreach_set(pix.ravel())
    img.update()
    img.pack()
    return img


def _bake_and_remap_material(
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

    1. Inspect Principled BSDF inputs.
    2. Bake linked inputs to textures; build solid images for flat non-default values.
    3. Channel-pack intermediate results into BCR (RGB + roughness) and
       NMO (normal + metallic + AO) images.
    4. Hand *generated_textures* to the existing ENF / Principled BSDF setup path.
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

    flat_bc = list(bc_socket.default_value)   # [R, G, B, A]
    flat_r  = float(r_socket.default_value)
    flat_m  = float(m_socket.default_value)
    flat_a  = float(a_socket.default_value)

    r_is_default = (not r_linked) and abs(flat_r - 0.5) < 1e-3
    m_is_default = (not m_linked) and abs(flat_m - 0.0) < 1e-3
    a_is_default = (not a_linked) and abs(flat_a - 1.0) < 1e-3

    # BCR is needed when base colour is procedural OR roughness is non-default
    bcr_needed = bc_linked or (not r_is_default)
    # NMO is needed when normal is procedural OR metallic is non-default
    nmo_needed = n_linked  or (not m_is_default)
    # Opacity texture needed when alpha is non-default or procedural
    a_needed   = not a_is_default

    # ── 2. Bake / create intermediate per-channel images ─────────────────────
    baked_bc = baked_r = baked_m = baked_n = baked_a = None

    needs_baking = bc_linked or r_linked or m_linked or n_linked or a_linked

    if needs_baking:
        # Configure the object as the bake source
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

        # Base Colour – use the Emission trick so bump/normal nodes cannot
        # influence the bake (DIFFUSE/COLOR is evaluated with surface normals
        # in context, which causes bump-perturbed normal XY data to bleed into
        # the BCR RGB channels).
        if bc_linked:
            baked_bc = _new_bake_img("BakeBC")
            if _bake_channel(mat, baked_bc, "EMIT",
                             emit_source_socket=bc_socket.links[0].from_socket):
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

        # Metallic – no dedicated bake pass; use the Emission trick
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

    # Non-linked but non-default scalars → create solid images so they are
    # encoded into the packed BCR/NMO output correctly
    if (not r_linked) and (not r_is_default) and (baked_r is None):
        baked_r = _create_solid_image(
            f"PTR_{mat.name}_BakeR", (flat_r, flat_r, flat_r, 1.0)
        )

    if (not m_linked) and (not m_is_default) and (baked_m is None):
        baked_m = _create_solid_image(
            f"PTR_{mat.name}_BakeM", (flat_m, flat_m, flat_m, 1.0)
        )

    if (not a_linked) and (not a_is_default) and (baked_a is None):
        baked_a = _create_solid_image(
            f"PTR_{mat.name}_BakeA", (flat_a, flat_a, flat_a, 1.0)
        )

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
    # baked_a is intentionally kept when stored under generated_textures["A"]

    # ── 4. Assign: ENF material path or Principled BSDF fallback ─────────────
    if can_use_enf:
        success = _setup_enf_material(mat, generated_textures, workbench_path)
        if success:
            # When base colour is flat and no BCR texture was generated, set it
            # directly on the ENF material colour slot
            if not bc_linked and "BCR" not in generated_textures:
                _set_enf_base_color(mat, (flat_bc[0], flat_bc[1], flat_bc[2], 1.0))
        return

    # ── Principled BSDF fallback node graph ───────────────────────────────────
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    mat.blend_method = "OPAQUE"

    bsdf_new = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf_new.location = (0, 0)
    out_node = nodes.new("ShaderNodeOutputMaterial")
    out_node.location = (300, 0)
    links.new(bsdf_new.outputs[0], out_node.inputs[0])

    tex_bcr_node = None

    if "BCR" in generated_textures:
        tex_bcr_node = nodes.new("ShaderNodeTexImage")
        tex_bcr_node.image = generated_textures["BCR"]
        tex_bcr_node.location = (-600, 200)
        # Link base colour only when NMO is absent (NMO path uses AO-multiply)
        if "NMO" not in generated_textures:
            links.new(tex_bcr_node.outputs[0], bsdf_new.inputs["Base Color"])
        # BCR Alpha channel encodes roughness
        links.new(tex_bcr_node.outputs["Alpha"], bsdf_new.inputs["Roughness"])
    else:
        # Everything is flat – set values directly on the BSDF
        bsdf_new.inputs["Base Color"].default_value = (
            flat_bc[0], flat_bc[1], flat_bc[2], 1.0
        )
        bsdf_new.inputs["Roughness"].default_value = flat_r
        bsdf_new.inputs["Metallic"].default_value = flat_m

    if "NMO" in generated_textures:
        tex_nmo_node = nodes.new("ShaderNodeTexImage")
        tex_nmo_node.image = generated_textures["NMO"]
        tex_nmo_node.location = (-600, -100)
        tex_nmo_node.image.colorspace_settings.name = "Non-Color"

        sep = nodes.new("ShaderNodeSeparateColor")
        sep.location = (-400, -100)
        links.new(tex_nmo_node.outputs[0], sep.inputs[0])
        links.new(sep.outputs["Blue"], bsdf_new.inputs["Metallic"])

        comb = nodes.new("ShaderNodeCombineColor")
        comb.location = (-200, -100)
        links.new(sep.outputs["Red"], comb.inputs["Red"])
        links.new(sep.outputs["Green"], comb.inputs["Green"])
        comb.inputs["Blue"].default_value = 0.5

        norm_map = nodes.new("ShaderNodeNormalMap")
        norm_map.location = (0, -200)
        links.new(comb.outputs[0], norm_map.inputs["Color"])
        links.new(norm_map.outputs[0], bsdf_new.inputs["Normal"])

        # AO-multiply: BCR colour × NMO alpha before feeding Base Color
        if tex_bcr_node is not None:
            mix = nodes.new("ShaderNodeMix")
            mix.data_type = "RGBA"
            mix.blend_type = "MULTIPLY"
            mix.inputs["Factor"].default_value = 1.0
            mix.location = (-200, 200)
            links.new(tex_bcr_node.outputs[0], mix.inputs["A"])
            links.new(tex_nmo_node.outputs["Alpha"], mix.inputs["B"])
            links.new(mix.outputs["Result"], bsdf_new.inputs["Base Color"])

    if "A" in generated_textures:
        tex_a_node = nodes.new("ShaderNodeTexImage")
        tex_a_node.image = generated_textures["A"]
        tex_a_node.location = (-600, -400)
        tex_a_node.image.colorspace_settings.name = "Non-Color"
        links.new(tex_a_node.outputs[0], bsdf_new.inputs["Alpha"])
        mat.blend_method = "CLIP"


class PanthorOTBakeRemapMaterials(Operator):
    """Bake Principled BSDF node graphs to textures and remap to Enfusion BCR/NMO format."""

    bl_idname: ClassVar[str] = "panthor.bake_remap_materials"
    bl_label: ClassVar[str] = "Bake & Remap Materials"
    bl_description: ClassVar[str] = (
        "Bake each material's Principled BSDF node graph to textures at the chosen "
        "resolution, then remap them into Enfusion-compatible BCR/NMO textures. "
        "Useful for models with no texture files or arbitrary procedural setups"
    )
    bl_options: ClassVar[set[str]] = {"REGISTER", "UNDO"}

    def execute(self, context):
        """Execute bake & remap for all mesh materials in the scene."""
        scene = context.scene
        res = int(scene.panthor_bake_resolution)
        use_enf       = getattr(scene, "panthor_use_enf_materials", False)
        workbench_path = getattr(scene, "panthor_workbench_path", "")
        can_use_enf    = (
            use_enf
            and workbench_path
            and hasattr(bpy.ops, "ebt")
            and hasattr(bpy.ops.ebt, "create_new_enfusion_material")
        )

        # ── Save scene state ──────────────────────────────────────────────────
        original_engine   = scene.render.engine
        original_active   = context.view_layer.objects.active
        original_selected = {o.name: o.select_get() for o in bpy.data.objects}

        # ── Collect one representative mesh object per unique material ─────────
        mat_to_obj: dict[str, bpy.types.Object] = {}
        for obj in bpy.data.objects:
            if obj.type != "MESH":
                continue
            for slot in obj.material_slots:
                if slot.material and slot.material.name not in mat_to_obj:
                    mat_to_obj[slot.material.name] = obj

        if not mat_to_obj:
            self.report({"INFO"}, "No mesh materials found to process.")
            return {"CANCELLED"}

        processed = 0
        warn_msgs: list[str] = []

        try:
            scene.render.engine = "CYCLES"

            for mat_name, bake_obj in mat_to_obj.items():
                mat = bpy.data.materials.get(mat_name)
                if not mat or not mat.use_nodes:
                    continue

                bsdf = _find_principled_bsdf(mat)
                if not bsdf:
                    warn_msgs.append(
                        f"'{mat.name}': no Principled BSDF node found – skipping. "
                        "Can only bake Principled BSDF materials."
                    )
                    continue

                try:
                    _bake_and_remap_material(
                        context, bake_obj, mat, bsdf, res, can_use_enf, workbench_path
                    )
                    processed += 1
                except Exception as exc:
                    warn_msgs.append(f"'{mat.name}': {exc}")

        finally:
            # ── Restore scene state ───────────────────────────────────────────
            scene.render.engine = original_engine
            context.view_layer.objects.active = original_active
            for obj_name, was_sel in original_selected.items():
                obj = bpy.data.objects.get(obj_name)
                if obj:
                    try:
                        obj.select_set(was_sel)
                    except Exception:
                        pass

        for msg in warn_msgs:
            self.report({"WARNING"}, msg)

        _refresh_texture_list(context)
        self.report({"INFO"}, f"Bake & Remap complete: {processed} material(s) processed.")
        return {"FINISHED"}


def register():
    """Register texture operators."""
    bpy.utils.register_class(PanthorTextureImportItem)
    bpy.utils.register_class(PanthorTextureItem)
    bpy.utils.register_class(PanthorOTImportTextures)
    bpy.utils.register_class(PanthorOTRefreshTextures)
    bpy.utils.register_class(PanthorOTBakeRemapMaterials)

    bpy.types.Scene.panthor_textures = CollectionProperty(type=PanthorTextureItem)
    bpy.types.Scene.panthor_texture_index = IntProperty()

    bpy.types.Scene.panthor_texture_import_list = CollectionProperty(type=PanthorTextureImportItem)

    from ..utils.texture_presets import get_preset_items
    bpy.types.Scene.panthor_texture_preset = EnumProperty(
        name="Texture Preset",
        items=get_preset_items,
    )

    bpy.types.Scene.panthor_workbench_path = StringProperty(
        name="Workbench Path",
        description="Directory where converted textures are saved for Workbench/EBT use",
        subtype="DIR_PATH",
        default="",
    )

    bpy.types.Scene.panthor_use_enf_materials = BoolProperty(
        name="Create ENF Materials",
        description="Create Enfusion (ENF) materials via EBT instead of Principled BSDF nodes. Requires EBT and a running Workbench instance",
        default=False,
    )

    bpy.types.Scene.panthor_bake_resolution = EnumProperty(
        name="Bake Resolution",
        description="Resolution for textures baked by 'Bake & Remap Materials'",
        items=[
            ("16",   "16",   "16 × 16 px"),
            ("32",   "32",   "32 × 32 px"),
            ("64",   "64",   "64 × 64 px"),
            ("128",  "128",  "128 × 128 px"),
            ("256",  "256",  "256 × 256 px"),
            ("512",  "512",  "512 × 512 px"),
            ("1024", "1024", "1024 × 1024 px"),
            ("2048", "2048", "2048 × 2048 px"),
            ("4096", "4096", "4096 × 4096 px"),
        ],
        default="1024",
    )


def unregister():
    """Unregister texture operators."""
    del bpy.types.Scene.panthor_bake_resolution
    del bpy.types.Scene.panthor_use_enf_materials
    del bpy.types.Scene.panthor_workbench_path
    del bpy.types.Scene.panthor_texture_preset
    del bpy.types.Scene.panthor_texture_import_list
    del bpy.types.Scene.panthor_texture_index
    del bpy.types.Scene.panthor_textures

    bpy.utils.unregister_class(PanthorOTBakeRemapMaterials)
    bpy.utils.unregister_class(PanthorOTRefreshTextures)
    bpy.utils.unregister_class(PanthorOTImportTextures)
    bpy.utils.unregister_class(PanthorTextureItem)
    bpy.utils.unregister_class(PanthorTextureImportItem)
