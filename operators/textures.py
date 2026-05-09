"""Texture operators."""

import os
from typing import ClassVar

import bpy
from bpy.props import CollectionProperty, EnumProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Image, Material, Operator, PropertyGroup

from ..utils.constants import TEXTURE_SUFFIXES
from ..utils.texture_presets import TEXTURE_PRESETS
from ..utils.texture_processing import generate_texture


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


def _get_image_by_suffix(images_list: list[Image], material_name: str, suffixes: list[str]) -> Image | None:
    """Find an image in a list that matches the material name and suffix."""
    mat_lower = material_name.lower()

    for img in images_list:
        name_lower = img.name.lower()

        # Strip Blender's .001 suffixes or file extensions like .png
        if "." in name_lower:
            name_lower = name_lower.rsplit(".", 1)[0]

        # Match material name exactly or without underscores
        if (mat_lower in name_lower or mat_lower.replace("_", "") in name_lower.replace("_", "")) and any(
            name_lower.endswith(s) or f"_{s}" in name_lower for s in suffixes
        ):
            return img
    return None


def _get_image_from_bsdf_input(bsdf: bpy.types.ShaderNodeBsdfPrincipled, input_name: str) -> Image | None:
    """Get an image from a BSDF input, handling Normal Maps."""
    if input_name not in bsdf.inputs:
        return None

    for link in bsdf.inputs[input_name].links:
        from_node = link.from_node
        if from_node.type == "TEX_IMAGE":
            return from_node.image
        if from_node.type == "NORMAL_MAP":
            for n_link in from_node.inputs["Color"].links:
                if n_link.from_node.type == "TEX_IMAGE":
                    return n_link.from_node.image
    return None


def _get_images_from_nodes(material: Material) -> dict[str, Image]:
    """Extract images currently linked to the material's Principled BSDF."""
    images = {}
    if not material.use_nodes:
        return images

    bsdf = next((n for n in material.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if not bsdf:
        return images

    # Map input names to their texture keys
    mapping = {
        "Base Color": "BASECOLOR",
        "Normal": "NORMAL",
        "Metallic": "METALNESS",
        "Roughness": "ROUGHNESS",
    }

    for input_name, tex_key in mapping.items():
        img = _get_image_from_bsdf_input(bsdf, input_name)
        if img:
            images[tex_key] = img

    return images


def process_material_textures(material, images_list, preset_key):
    """Generate textures based on preset and set up the material."""
    preset = TEXTURE_PRESETS.get(preset_key)
    if not preset:
        return

    # First, try to pull exactly what Blender's FBX importer already wired up (for embedded textures)
    available_images = _get_images_from_nodes(material)

    # Fill in any missing maps by intelligently string-matching against the folder/images list
    for tex_type, suffixes in TEXTURE_SUFFIXES.items():
        if tex_type not in available_images or available_images[tex_type] is None:
            available_images[tex_type] = _get_image_by_suffix(images_list, material.name, suffixes)

    generated_textures = {}
    for map_config in preset["maps"]:
        tex_name = f"PTR_{material.name}_{map_config['name']}"

        # Determine fallback color based on typical use
        fallback = (0.5, 0.5, 0.0, 1.0) if map_config["name"] == "NMO" else (1.0, 1.0, 1.0, 1.0)

        img = generate_texture(tex_name, map_config, available_images, fallback_color=fallback)
        generated_textures[map_config["name"]] = img

    # Set up material nodes
    material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()

    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (300, 0)
    links.new(bsdf.outputs[0], out.inputs[0])

    if "BCR" in generated_textures:
        tex_bcr = nodes.new("ShaderNodeTexImage")
        tex_bcr.image = generated_textures["BCR"]
        tex_bcr.location = (-600, 200)
        links.new(tex_bcr.outputs[0], bsdf.inputs["Base Color"])

        # Alpha channel of BCR is Roughness
        links.new(tex_bcr.outputs["Alpha"], bsdf.inputs["Roughness"])

    if "NMO" in generated_textures:
        tex_nmo = nodes.new("ShaderNodeTexImage")
        tex_nmo.image = generated_textures["NMO"]
        tex_nmo.location = (-600, -100)
        if tex_nmo.image:
            tex_nmo.image.colorspace_settings.name = "Non-Color"

        # NMO: R+B = Normal, G = Metallic, A = AO
        sep = nodes.new("ShaderNodeSeparateColor")
        sep.location = (-400, -100)
        links.new(tex_nmo.outputs[0], sep.inputs[0])

        # Metallic
        links.new(sep.outputs["Green"], bsdf.inputs["Metallic"])

        # Normal Map reconstruction (R, B, 1.0)
        comb = nodes.new("ShaderNodeCombineColor")
        comb.location = (-200, -100)
        links.new(sep.outputs["Red"], comb.inputs["Red"])
        links.new(sep.outputs["Blue"], comb.inputs["Green"])  # We use Blue as the Y channel
        comb.inputs["Blue"].default_value = 1.0

        norm_map = nodes.new("ShaderNodeNormalMap")
        norm_map.location = (0, -200)
        links.new(comb.outputs[0], norm_map.inputs["Color"])
        links.new(norm_map.outputs[0], bsdf.inputs["Normal"])

    if "A" in generated_textures:
        tex_a = nodes.new("ShaderNodeTexImage")
        tex_a.image = generated_textures["A"]
        tex_a.location = (-600, -400)
        if tex_a.image:
            tex_a.image.colorspace_settings.name = "Non-Color"

        links.new(tex_a.outputs[0], bsdf.inputs["Alpha"])
        # Set blend mode to Alpha Clip or Blend if opacity is present
        material.blend_method = "CLIP"
        material.shadow_method = "CLIP"


class PanthorOTRemapEmbeddedTextures(Operator):
    """Remap embedded textures according to the selected preset."""

    bl_idname: ClassVar[str] = "panthor.remap_embedded_textures"
    bl_label: ClassVar[str] = "Remap Embedded Textures"
    bl_options: ClassVar[set[str]] = {"REGISTER", "UNDO"}

    def execute(self, context):
        """Execute."""
        preset = context.scene.panthor_texture_preset
        if preset == "NONE":
            self.report({"WARNING"}, "Texture preset is set to NONE.")
            return {"CANCELLED"}

        images = [img for img in bpy.data.images if img.has_data]
        processed_materials = set()

        for obj in context.scene.objects:
            if obj.type == "MESH":
                for slot in obj.material_slots:
                    if slot.material and slot.material not in processed_materials:
                        processed_materials.add(slot.material)
                        process_material_textures(slot.material, images, preset)

        _refresh_texture_list(context)
        self.report({"INFO"}, "Embedded textures remapped.")
        return {"FINISHED"}


class PanthorOTImportTextures(Operator):
    """Import textures from a directory and remap them."""

    bl_idname: ClassVar[str] = "panthor.import_textures"
    bl_label: ClassVar[str] = "Import & Remap Textures"
    bl_options: ClassVar[set[str]] = {"REGISTER", "UNDO"}

    directory: StringProperty(subtype="DIR_PATH")

    def invoke(self, context, event):
        """Invoke."""
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        """Execute."""
        preset = context.scene.panthor_texture_preset
        if preset == "NONE":
            self.report({"WARNING"}, "Texture preset is set to NONE.")
            return {"CANCELLED"}

        if not self.directory:
            return {"CANCELLED"}

        # Load all images in the directory
        loaded_images = []
        for file in os.listdir(self.directory):
            if file.lower().endswith((".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff")):
                filepath = os.path.join(self.directory, file)
                img = bpy.data.images.load(filepath, check_existing=True)
                loaded_images.append(img)

        processed_materials = set()

        for obj in context.scene.objects:
            if obj.type == "MESH":
                for slot in obj.material_slots:
                    if slot.material and slot.material not in processed_materials:
                        processed_materials.add(slot.material)
                        process_material_textures(slot.material, loaded_images, preset)

        _refresh_texture_list(context)
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


def register():
    """Register texture operators."""
    from ..utils.texture_presets import get_preset_items

    bpy.utils.register_class(PanthorTextureItem)
    bpy.utils.register_class(PanthorOTRemapEmbeddedTextures)
    bpy.utils.register_class(PanthorOTImportTextures)
    bpy.utils.register_class(PanthorOTRefreshTextures)

    bpy.types.Scene.panthor_textures = CollectionProperty(type=PanthorTextureItem)
    bpy.types.Scene.panthor_texture_index = IntProperty()

    bpy.types.Scene.panthor_texture_preset = EnumProperty(
        name="Texture Preset",
        items=get_preset_items,
    )


def unregister():
    """Unregister texture operators."""
    del bpy.types.Scene.panthor_texture_preset
    del bpy.types.Scene.panthor_texture_index
    del bpy.types.Scene.panthor_textures

    bpy.utils.unregister_class(PanthorOTRefreshTextures)
    bpy.utils.unregister_class(PanthorOTImportTextures)
    bpy.utils.unregister_class(PanthorOTRemapEmbeddedTextures)
    bpy.utils.unregister_class(PanthorTextureItem)
