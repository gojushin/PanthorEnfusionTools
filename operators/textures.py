"""Texture operators."""

import os
from typing import ClassVar

import bpy
from bpy.props import CollectionProperty, EnumProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Material, Operator, PropertyGroup

from ..utils.constants import TEXTURE_SUFFIXES
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
            mix.data_type = 'COLOR'
            mix.blend_type = 'MULTIPLY'
            mix.inputs["Factor"].default_value = 1.0
            mix.location = (-200, 200)

            links.new(tex_bcr.outputs[0], mix.inputs["A"])
            links.new(sep.outputs["Alpha"], mix.inputs["B"])
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


def register():
    """Register texture operators."""
    bpy.utils.register_class(PanthorTextureImportItem)
    bpy.utils.register_class(PanthorTextureItem)
    bpy.utils.register_class(PanthorOTImportTextures)
    bpy.utils.register_class(PanthorOTRefreshTextures)

    bpy.types.Scene.panthor_textures = CollectionProperty(type=PanthorTextureItem)
    bpy.types.Scene.panthor_texture_index = IntProperty()

    bpy.types.Scene.panthor_texture_import_list = CollectionProperty(type=PanthorTextureImportItem)

    from ..utils.texture_presets import get_preset_items
    bpy.types.Scene.panthor_texture_preset = EnumProperty(
        name="Texture Preset",
        items=get_preset_items,
    )


def unregister():
    """Unregister texture operators."""
    del bpy.types.Scene.panthor_texture_preset
    del bpy.types.Scene.panthor_texture_import_list
    del bpy.types.Scene.panthor_texture_index
    del bpy.types.Scene.panthor_textures

    bpy.utils.unregister_class(PanthorOTRefreshTextures)
    bpy.utils.unregister_class(PanthorOTImportTextures)
    bpy.utils.unregister_class(PanthorTextureItem)
    bpy.utils.unregister_class(PanthorTextureImportItem)
