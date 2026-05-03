"""Texture channel packing and processing utilizing numpy for speed."""

import bpy
import numpy as np


def _get_image_pixels(image: bpy.types.Image) -> np.ndarray:
    """Retrieve image pixels as a numpy array."""
    # Ensure image is loaded into memory
    if not image.has_data:
        image.pixels[0]

    width, height = image.size
    channels = image.channels
    pixels = np.empty(width * height * channels, dtype=np.float32)
    image.pixels.foreach_get(pixels)

    return pixels.reshape((height, width, channels))

def _set_image_pixels(image: bpy.types.Image, pixels_array: np.ndarray):
    """Set image pixels from a numpy array."""
    pixels = pixels_array.flatten()
    image.pixels.foreach_set(pixels)
    image.update()

def create_bcr_texture(
    name: str,
    bc_img: bpy.types.Image = None,
    r_img: bpy.types.Image = None,
    width: int = 1024,
    height: int = 1024,
    fallback_color: tuple = (1.0, 1.0, 1.0, 1.0),
) -> bpy.types.Image:
    """Create a BaseColor + Roughness (BCR) texture.

    RGB = Base Color, Alpha = Roughness.
    """
    if bc_img:
        width, height = bc_img.size
    elif r_img:
        width, height = r_img.size

    bcr_img = bpy.data.images.new(name=name, width=width, height=height, alpha=True)

    pixels = np.ones((height, width, 4), dtype=np.float32)

    if bc_img:
        bc_pixels = _get_image_pixels(bc_img)
        # Handle cases where base color might not have alpha
        if bc_pixels.shape[2] == 4:
            pixels[:, :, :3] = bc_pixels[:, :, :3]
        elif bc_pixels.shape[2] == 3:
            pixels[:, :, :3] = bc_pixels
    else:
        pixels[:, :, 0] = fallback_color[0]
        pixels[:, :, 1] = fallback_color[1]
        pixels[:, :, 2] = fallback_color[2]

    if r_img:
        r_pixels = _get_image_pixels(r_img)
        # Roughness is usually single channel or we take the first channel
        if r_pixels.shape[2] >= 1:
            pixels[:, :, 3] = r_pixels[:, :, 0]
    else:
        pixels[:, :, 3] = fallback_color[3]

    _set_image_pixels(bcr_img, pixels)
    bcr_img.pack()
    return bcr_img

def create_nmo_texture(
    name: str,
    n_img: bpy.types.Image = None,
    orm_img: bpy.types.Image = None,
    r_img: bpy.types.Image = None,
    width: int = 1024,
    height: int = 1024,
) -> bpy.types.Image:
    """Create a Normal + Metallic + Ambient Occlusion (NMO) texture.

    RG = Normal, B = Metallic, A = Ambient Occlusion.
    """
    if n_img:
        width, height = n_img.size
    elif orm_img:
        width, height = orm_img.size
    elif r_img:
        width, height = r_img.size

    nmo_img = bpy.data.images.new(name=name, width=width, height=height, alpha=True)
    # Default: Flat Normal (0.5, 0.5, 1.0), Black Metallic, White AO
    pixels = np.ones((height, width, 4), dtype=np.float32)
    pixels[:, :, 0] = 0.5  # Normal R
    pixels[:, :, 1] = 0.5  # Normal G
    pixels[:, :, 2] = 0.0  # Metallic
    pixels[:, :, 3] = 1.0  # AO

    if n_img:
        n_pixels = _get_image_pixels(n_img)
        if n_pixels.shape[2] >= 2:
            pixels[:, :, :2] = n_pixels[:, :, :2]

    if orm_img:
        orm_pixels = _get_image_pixels(orm_img)
        if orm_pixels.shape[2] >= 3:
            # ORM: R = AO, G = Roughness, B = Metallic
            pixels[:, :, 2] = orm_pixels[:, :, 2] # Metallic -> B
            pixels[:, :, 3] = orm_pixels[:, :, 0] # AO -> A
    elif r_img:
        # User defined: If only roughness, R=white, G=roughness, B=white
        # Then metallic=0.0 (default), AO=1.0 (default)
        pass

    _set_image_pixels(nmo_img, pixels)
    nmo_img.pack()
    return nmo_img
