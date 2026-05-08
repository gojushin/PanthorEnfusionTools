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
    fallback_color: tuple = (1.0, 1.0, 1.0, 1.0),
) -> bpy.types.Image:
    """Generate a texture based on a dynamic config mapping.

    This function compiles a new texture by plucking specific channels
    from various input textures and packing them together.
    """
    # --- Step 1: Figure out what textures we actually need to load ---
    used_types = set()
    for map_key in ["R", "G", "B", "A"]:
        for mapping in config["mapping"].get(map_key, []):
            tex_type = mapping.split(".")[0]
            used_types.add(tex_type)

    # --- Step 2: Determine the maximum resolution to use ---
    # We want our output texture to be as large as the largest input texture.
    for tex_type in used_types:
        img = available_images.get(tex_type)
        if img:
            width = max(width, img.size[0])
            height = max(height, img.size[1])

    # --- Step 3: Setup the blank output canvas ---
    # We use empty to allocate memory quickly, then immediately fill it with our fallback color.
    pixels = np.empty((height, width, 4), dtype=np.float32)
    pixels[:, :, 0] = fallback_color[0]  # Red
    pixels[:, :, 1] = fallback_color[1]  # Green
    pixels[:, :, 2] = fallback_color[2]  # Blue
    pixels[:, :, 3] = fallback_color[3]  # Alpha

    # --- Step 4: Load all required images into Numpy Arrays ---
    pixel_arrays = {}
    for tex_type in used_types:
        img = available_images.get(tex_type)
        if img:
            pixel_arrays[tex_type] = _get_image_pixels(img)

    channel_indices = {"R": 0, "G": 1, "B": 2, "A": 3}

    # --- Step 5: Process Mappings Channel by Channel ---
    # Example: dest_ch_str might be "R", and sources might be ["BASECOLOR.R", "ROUGHNESS.R"]
    for dest_ch_str, sources in config["mapping"].items():
        if dest_ch_str not in channel_indices:
            continue

        dest_ch_idx = channel_indices[dest_ch_str]

        # Try each source in order. The first one that exists wins.
        for source in sources:
            parts = source.split(".")
            if len(parts) != 2:
                continue

            tex_type, src_ch_str = parts

            # Check if we actually have this image loaded
            if tex_type in pixel_arrays:
                src_pixels = pixel_arrays[tex_type]
                src_ch_idx = channel_indices.get(src_ch_str, 0)

                # Verify the source image actually has this channel (e.g. avoiding grabbing Alpha from an RGB image)
                if src_ch_idx < src_pixels.shape[2]:
                    h_src, w_src, _ = src_pixels.shape

                    # If dimensions perfectly match, do a blazing fast direct copy
                    if h_src == height and w_src == width:
                        pixels[:, :, dest_ch_idx] = src_pixels[:, :, src_ch_idx]
                    else:
                        # If the dimensions do NOT match, we just slice (crop) what fits.
                        # This prevents crashes but implies artists should match their texture sizes!
                        h_min = min(height, h_src)
                        w_min = min(width, w_src)
                        pixels[:h_min, :w_min, dest_ch_idx] = src_pixels[:h_min, :w_min, src_ch_idx]

                    # We successfully found a valid map, stop looking at fallbacks!
                    break

    # --- Step 6: Apply Inversions ---
    # Sometimes engines require flipped normals or Smoothness instead of Roughness (1.0 - value).
    actions = config.get("actions", {})
    if actions.get("invert_red_channel"):
        pixels[:, :, 0] = 1.0 - pixels[:, :, 0]

    if actions.get("invert_green_channel"):
        pixels[:, :, 1] = 1.0 - pixels[:, :, 1]

    if actions.get("invert_blue_channel"):
        pixels[:, :, 2] = 1.0 - pixels[:, :, 2]

    if actions.get("invert_alpha_channel"):
        pixels[:, :, 3] = 1.0 - pixels[:, :, 3]

    # --- Step 7: Save to Blender ---
    img = bpy.data.images.new(name=name, width=width, height=height, alpha=True)
    _set_image_pixels(img, pixels)
    img.pack()

    return img
