"""Texture operators."""

import os

import bpy
from bpy.props import CollectionProperty, EnumProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Operator, PropertyGroup

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
        if img.has_data and img.type != 'RENDER_RESULT' and img.name != 'Render Result':
            item = context.scene.panthor_textures.add()
            item.img = img


def _get_image_by_suffix(images_list, material_name, suffixes):
    """Find an image in a list that matches the material name and suffix."""
    mat_lower = material_name.lower()
    for img in images_list:
        name_lower = img.name.lower()
        # Remove extension
        name_lower = os.path.splitext(name_lower)[0]
        # Match material name or part of it
        if mat_lower in name_lower or mat_lower.replace("_", "") in name_lower.replace("_", ""):
            if any(name_lower.endswith(s) or f"_{s}" in name_lower for s in suffixes):
                return img
    return None


def process_material_textures(material, images_list, preset_key):
    """Generate textures based on preset and set up the material."""
    preset = TEXTURE_PRESETS.get(preset_key)
    if not preset:
        return

    # Collect available images for this material
    available_images = {}
    for tex_type, suffixes in TEXTURE_SUFFIXES.items():
        available_images[tex_type] = _get_image_by_suffix(images_list, material.name, suffixes)

    generated_textures = {}
    for map_config in preset["maps"]:
        tex_name = f"PTR_{material.name}_{map_config['name']}"

        # Determine fallback color based on typical use
        if map_config["name"] == "NMO":
            fallback = (0.5, 0.5, 0.0, 1.0)
        else:
            fallback = (1.0, 1.0, 1.0, 1.0)

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
        tex_bcr.location = (-300, 100)
        links.new(tex_bcr.outputs[0], bsdf.inputs["Base Color"])

    if "NMO" in generated_textures:
        tex_nmo = nodes.new("ShaderNodeTexImage")
        tex_nmo.image = generated_textures["NMO"]
        tex_nmo.location = (-300, -200)
        if tex_nmo.image:
            tex_nmo.image.colorspace_settings.name = "Non-Color"

        normal_map = nodes.new("ShaderNodeNormalMap")
        normal_map.location = (-100, -200)
        links.new(tex_nmo.outputs[0], normal_map.inputs["Color"])
        links.new(normal_map.outputs[0], bsdf.inputs["Normal"])


class PANTHOR_OT_remap_embedded_textures(Operator):
    """Remap embedded textures according to the selected preset."""

    bl_idname = "panthor.remap_embedded_textures"
    bl_label = "Remap Embedded Textures"
    bl_options = {"REGISTER", "UNDO"}

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


class PANTHOR_OT_import_textures(Operator):
    """Import textures from a directory and remap them."""

    bl_idname = "panthor.import_textures"
    bl_label = "Import & Remap Textures"
    bl_options = {"REGISTER", "UNDO"}

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


class PANTHOR_OT_refresh_textures(Operator):
    """Refresh the list of imported textures."""

    bl_idname = "panthor.refresh_textures"
    bl_label = "Refresh Textures"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        """Execute refresh."""
        _refresh_texture_list(context)
        return {"FINISHED"}


def register():
    """Register texture operators."""
    from ..utils.texture_presets import get_preset_items

    bpy.utils.register_class(PanthorTextureItem)
    bpy.utils.register_class(PANTHOR_OT_remap_embedded_textures)
    bpy.utils.register_class(PANTHOR_OT_import_textures)
    bpy.utils.register_class(PANTHOR_OT_refresh_textures)

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

    bpy.utils.unregister_class(PANTHOR_OT_refresh_textures)
    bpy.utils.unregister_class(PANTHOR_OT_import_textures)
    bpy.utils.unregister_class(PANTHOR_OT_remap_embedded_textures)
    bpy.utils.unregister_class(PanthorTextureItem)
