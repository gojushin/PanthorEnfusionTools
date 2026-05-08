"""Texture operators."""

import os
import bpy
from bpy.props import CollectionProperty, EnumProperty, IntProperty, PointerProperty, StringProperty
from bpy.types import Operator, PropertyGroup

from ..utils.constants import (
    TEXTURE_SUFFIXES_BASECOLOR,
    TEXTURE_SUFFIXES_METALNESS,
    TEXTURE_SUFFIXES_NORMAL,
    TEXTURE_SUFFIXES_ORM,
    TEXTURE_SUFFIXES_ROUGHNESS,
)
from ..utils.texture_processing import create_bcr_texture, create_nmo_texture


class PanthorTextureItem(PropertyGroup):
    """Property group for a texture item."""
    
    img: PointerProperty(type=bpy.types.Image)


def _refresh_texture_list(context):
    """Refresh the list of generated PTR_ textures."""
    context.scene.panthor_textures.clear()
    for img in bpy.data.images:
        if img.name.startswith("PTR_"):
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


def process_material_textures(material, images_list, preset):
    """Generate BCR and NMO textures and set up the material."""
    bc_img = _get_image_by_suffix(images_list, material.name, TEXTURE_SUFFIXES_BASECOLOR)
    n_img = _get_image_by_suffix(images_list, material.name, TEXTURE_SUFFIXES_NORMAL)
    
    r_img, m_img, orm_img = None, None, None
    if preset == 'UNREAL':
        orm_img = _get_image_by_suffix(images_list, material.name, TEXTURE_SUFFIXES_ORM)
    elif preset == 'PBR':
        r_img = _get_image_by_suffix(images_list, material.name, TEXTURE_SUFFIXES_ROUGHNESS)
        m_img = _get_image_by_suffix(images_list, material.name, TEXTURE_SUFFIXES_METALNESS)
        
    bcr = create_bcr_texture(f"PTR_{material.name}_BCR", bc_img=bc_img, r_img=r_img if preset=='PBR' else None)
    nmo = create_nmo_texture(f"PTR_{material.name}_NMO", n_img=n_img, orm_img=orm_img, m_img=m_img)
    
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
    
    tex_bcr = nodes.new("ShaderNodeTexImage")
    tex_bcr.image = bcr
    tex_bcr.location = (-300, 100)
    links.new(tex_bcr.outputs[0], bsdf.inputs["Base Color"])
    
    tex_nmo = nodes.new("ShaderNodeTexImage")
    tex_nmo.image = nmo
    tex_nmo.location = (-300, -200)
    if tex_nmo.image:
        tex_nmo.image.colorspace_settings.name = 'Non-Color'
    
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
        if preset == 'NONE':
            self.report({'WARNING'}, "Texture preset is set to NONE.")
            return {'CANCELLED'}
            
        images = [img for img in bpy.data.images if img.has_data]
        
        for obj in context.scene.objects:
            if obj.type == 'MESH':
                for slot in obj.material_slots:
                    if slot.material:
                        process_material_textures(slot.material, images, preset)
                        
        _refresh_texture_list(context)
        self.report({'INFO'}, "Embedded textures remapped.")
        return {'FINISHED'}


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
        if preset == 'NONE':
            self.report({'WARNING'}, "Texture preset is set to NONE.")
            return {'CANCELLED'}
            
        if not self.directory:
            return {'CANCELLED'}
            
        # Load all images in the directory
        loaded_images = []
        for file in os.listdir(self.directory):
            if file.lower().endswith(('.png', '.jpg', '.jpeg', '.tga', '.tif', '.tiff')):
                filepath = os.path.join(self.directory, file)
                img = bpy.data.images.load(filepath, check_existing=True)
                loaded_images.append(img)
                
        for obj in context.scene.objects:
            if obj.type == 'MESH':
                for slot in obj.material_slots:
                    if slot.material:
                        process_material_textures(slot.material, loaded_images, preset)
                        
        _refresh_texture_list(context)
        self.report({'INFO'}, "Textures imported and remapped.")
        return {"FINISHED"}


class PANTHOR_OT_refresh_textures(Operator):
    """Refresh the list of imported textures."""
    bl_idname = "panthor.refresh_textures"
    bl_label = "Refresh Textures"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        """Execute refresh."""
        _refresh_texture_list(context)
        return {'FINISHED'}


def register():
    """Register texture operators."""
    bpy.utils.register_class(PanthorTextureItem)
    bpy.utils.register_class(PANTHOR_OT_remap_embedded_textures)
    bpy.utils.register_class(PANTHOR_OT_import_textures)
    bpy.utils.register_class(PANTHOR_OT_refresh_textures)
    
    bpy.types.Scene.panthor_textures = CollectionProperty(type=PanthorTextureItem)
    bpy.types.Scene.panthor_texture_index = IntProperty()
    
    bpy.types.Scene.panthor_texture_preset = EnumProperty(
        name="Texture Preset",
        items=[
            ('NONE', "None", "Do not remap"),
            ('UNREAL', "Unreal (ORM)", "Use Occlusion/Roughness/Metallic maps"),
            ('PBR', "PBR (Roughness/Metallic)", "Use separate Roughness and Metallic maps"),
        ],
        default='NONE'
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
