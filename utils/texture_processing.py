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

def generate_texture(
    name: str,
    config: dict,
    available_images: dict,
    width: int = 1024,
    height: int = 1024,
    fallback_color: tuple = (1.0, 1.0, 1.0, 1.0)
) -> bpy.types.Image:
    """Generate a texture based on a dynamic config mapping."""
    
    # 1. Determine maximum resolution among used images
    used_types = set()
    for map_key in ["R", "G", "B", "A"]:
        for mapping in config["mapping"].get(map_key, []):
            tex_type = mapping.split(".")[0]
            used_types.add(tex_type)
            
    for tex_type in used_types:
        img = available_images.get(tex_type)
        if img:
            width = max(width, img.size[0])
            height = max(height, img.size[1])

    # 2. Initialize pixels with fallback color
    pixels = np.empty((height, width, 4), dtype=np.float32)
    pixels[:, :, 0] = fallback_color[0]
    pixels[:, :, 1] = fallback_color[1]
    pixels[:, :, 2] = fallback_color[2]
    pixels[:, :, 3] = fallback_color[3]
    
    # 3. Load pixel arrays for needed images
    pixel_arrays = {}
    for tex_type in used_types:
        img = available_images.get(tex_type)
        if img:
            pixel_arrays[tex_type] = _get_image_pixels(img)
            
    channel_indices = {"R": 0, "G": 1, "B": 2, "A": 3}
    
    # 4. Apply mappings
    for dest_ch_str, sources in config["mapping"].items():
        if dest_ch_str not in channel_indices: 
            continue
        dest_ch_idx = channel_indices[dest_ch_str]
        
        # Sources is a list (e.g. ["BASECOLOR.R", "ROUGHNESS.G"])
        for source in sources:
            parts = source.split(".")
            if len(parts) != 2:
                continue
                
            tex_type, src_ch_str = parts
            if tex_type in pixel_arrays:
                src_pixels = pixel_arrays[tex_type]
                src_ch_idx = channel_indices.get(src_ch_str, 0)
                
                if src_ch_idx < src_pixels.shape[2]:
                    # If the source image is lower resolution, we should ideally resize it.
                    # For performance and simplicity, we currently assume textures are same resolution
                    # if they are actively being mapped, or we just map what fits.
                    
                    h_src, w_src, _ = src_pixels.shape
                    
                    if h_src == height and w_src == width:
                        pixels[:, :, dest_ch_idx] = src_pixels[:, :, src_ch_idx]
                    else:
                        import cv2
                        # Faster resizing with OpenCV if available, else simple slice (which tiles/crops)
                        # We will use simple slice/crop for now to avoid cv2 dependency.
                        # It's better to ensure users supply matching resolutions.
                        h_min = min(height, h_src)
                        w_min = min(width, w_src)
                        # Tile/crop logic:
                        pixels[:h_min, :w_min, dest_ch_idx] = src_pixels[:h_min, :w_min, src_ch_idx]
                        
                    break # Success! Do not try fallbacks for this channel

    # 5. Apply actions (Inversions)
    actions = config.get("actions", {})
    if actions.get("invert_red_channel"):
        pixels[:, :, 0] = 1.0 - pixels[:, :, 0]
    if actions.get("invert_green_channel"):
        pixels[:, :, 1] = 1.0 - pixels[:, :, 1]
    if actions.get("invert_blue_channel"):
        pixels[:, :, 2] = 1.0 - pixels[:, :, 2]
    if actions.get("invert_alpha_channel"):
        pixels[:, :, 3] = 1.0 - pixels[:, :, 3]
        
    img = bpy.data.images.new(name=name, width=width, height=height, alpha=True)
    _set_image_pixels(img, pixels)
    img.pack()
    return img
