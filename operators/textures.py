"""Texture operators."""

import os
from typing import ClassVar

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Material, Operator, PropertyGroup

from ..utils.constants import TEXTURE_SUFFIXES
from ..utils.texture_presets import TEXTURE_PRESETS
from ..utils.texture_processing import generate_texture, is_image_color
from ..utils.baking import bake_and_remap_material, setup_enf_material, rebuild_principled_nodes


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
        if img.has_data and img.type != "RENDER_RESULT" and img.name != "Render Result":
            item = context.scene.panthor_textures.add()
            item.img = img


def _find_principled_bsdf(material: Material):
    """Return the first Principled BSDF node found in *material*'s node tree, or None."""
    if not material.use_nodes:
        return None
    for node in material.node_tree.nodes:
        if node.type == "BSDF_PRINCIPLED":
            return node
    return None


def process_material_textures_explicit(material: Material, mapping_items: list[PanthorTextureImportItem]):
    """Generate textures based on explicit mapping and set up the material."""
    if not mapping_items:
        return

    preset_key = mapping_items[0].source_preset
    preset = TEXTURE_PRESETS.get(preset_key)
    if not preset:
        return

    scene = bpy.context.scene
    use_enf = getattr(scene, "panthor_use_enf_materials", False)
    workbench_path = getattr(scene, "panthor_workbench_path", "")
    can_use_enf = use_enf and workbench_path and hasattr(bpy.ops, "ebt")

    available_images = {}
    for item in mapping_items:
        if not os.path.exists(item.filepath):
            continue
        try:
            img = bpy.data.images.load(item.filepath, check_existing=True)
            available_images[item.texture_type] = img
        except Exception:
            continue

    generated_textures = {}
    for map_config in preset["maps"]:
        map_name = map_config["name"]
        tex_name = f"PTR_{material.name}_{map_name}"
        fallback = (0.5, 0.5, 0.0, 1.0) if map_name == "NMO" else (1.0, 1.0, 1.0, 1.0)

        img = generate_texture(tex_name, map_config, available_images, fallback_color=fallback)

        if is_image_color(img, fallback):
            bpy.data.images.remove(img)
            continue

        generated_textures[map_name] = img

    if can_use_enf:
        success = setup_enf_material(material, generated_textures, workbench_path)
        if success:
            return

    # Flat values needed by rebuild_principled_nodes when no BCR was generated
    flat_bc = [1.0, 1.0, 1.0, 1.0]
    flat_r = 0.5
    flat_m = 0.0
    rebuild_principled_nodes(material, generated_textures, flat_bc, flat_r, flat_m)


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
            context.scene.panthor_texture_import_list.clear()

            mats = [m.name for m in bpy.data.materials]

            for file in os.listdir(self.directory):
                if file.lower().endswith((".png", ".jpg", ".jpeg", ".tga", ".tif", ".tiff")):
                    item = context.scene.panthor_texture_import_list.add()
                    item.filename = file
                    item.filepath = os.path.join(self.directory, file)

                    name_lower = file.lower()

                    for tex_type, suffixes in TEXTURE_SUFFIXES.items():
                        if any(
                            name_lower.endswith(s + os.path.splitext(name_lower)[1])
                            or f"_{s}" in name_lower
                            for s in suffixes
                        ):
                            item.texture_type = tex_type
                            break

                    best_mat = "NONE"
                    for mat_name in mats:
                        if mat_name.lower() in name_lower:
                            best_mat = mat_name
                            break
                    item.target_material = best_mat

                    item.source_preset = context.scene.panthor_texture_preset

            self.is_configured = True
            return context.window_manager.invoke_props_dialog(self, width=800)

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
        use_enf = getattr(scene, "panthor_use_enf_materials", False)
        workbench_path = getattr(scene, "panthor_workbench_path", "")
        can_use_enf = (
            use_enf
            and workbench_path
            and hasattr(bpy.ops, "ebt")
            and hasattr(bpy.ops.ebt, "create_new_enfusion_material")
        )

        original_engine = scene.render.engine
        original_active = context.view_layer.objects.active
        original_selected = {o.name: o.select_get() for o in bpy.data.objects}

        # Collect one representative mesh object per unique material
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
                    bake_and_remap_material(
                        context, bake_obj, mat, bsdf, res, can_use_enf, workbench_path
                    )
                    processed += 1
                except Exception as exc:
                    warn_msgs.append(f"'{mat.name}': {exc}")

        finally:
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
        description=(
            "Create Enfusion (ENF) materials via EBT instead of Principled BSDF nodes. "
            "Requires EBT and a running Workbench instance"
        ),
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