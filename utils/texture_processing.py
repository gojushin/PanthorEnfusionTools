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
    """
    Generate a texture based on a dynamic config mapping.

    This function compiles a new texture by plucking specific channels
    from various input textures and packing them together.
    """
    # 1. Determine dimensions (use inputs if available, otherwise fallback)
    target_width, target_height = _determine_dimensions(config, available_images)
    if target_width == 0:
        target_width, target_height = width, height

    pixels = _initialize_canvas(target_width, target_height, fallback_color)

    # 2. Load required source pixels
    pixel_arrays = _load_source_pixel_arrays(config, available_images)

    # 3. Process channel mappings
    _apply_channel_mappings(pixels, config, pixel_arrays)

    # 4. Apply post-processing actions (e.g. inversions)
    _apply_post_actions(pixels, config)

    # 5. Create and save to Blender
    # Remove existing image if it exists to avoid .001 name collision
    existing = bpy.data.images.get(name)
    if existing:
        bpy.data.images.remove(existing)

    img = bpy.data.images.new(name=name, width=target_width, height=target_height, alpha=True)
    _set_image_pixels(img, pixels)
    img.pack()

    return img


def _determine_dimensions(config: dict, available_images: dict) -> tuple[int, int]:
    """Calculate maximum dimensions from used textures."""
    width, height = 0, 0
    used_types = set()
    for sources in config["mapping"].values():
        for source in sources:
            used_types.add(source.split(".")[0])

    for tex_type in used_types:
        img = available_images.get(tex_type)
        if img:
            width = max(width, img.size[0])
            height = max(height, img.size[1])
    return width, height


def _initialize_canvas(width: int, height: int, fallback_color: tuple) -> np.ndarray:
    """Create a new blank pixel array."""
    pixels = np.empty((height, width, 4), dtype=np.float32)
    for i in range(4):
        pixels[:, :, i] = fallback_color[i]
    return pixels


def _load_source_pixel_arrays(config: dict, available_images: dict) -> dict[str, np.ndarray]:
    """Load all necessary images into numpy arrays."""
    pixel_arrays = {}
    used_types = {s.split(".")[0] for sources in config["mapping"].values() for s in sources}

    for tex_type in used_types:
        img = available_images.get(tex_type)
        if img:
            pixel_arrays[tex_type] = _get_image_pixels(img)
    return pixel_arrays


def _apply_channel_mappings(pixels: np.ndarray, config: dict, pixel_arrays: dict):
    """Iterate through mapping config and pack channels into pixels array."""
    channel_indices = {"R": 0, "G": 1, "B": 2, "A": 3}
    target_h, target_w, _ = pixels.shape

    for dest_ch_str, sources in config["mapping"].items():
        if dest_ch_str not in channel_indices:
            continue

        dest_ch_idx = channel_indices[dest_ch_str]

        for source in sources:
            parts = source.split(".")
            if len(parts) != 2:
                continue

            tex_type, src_ch_str = parts
            if tex_type not in pixel_arrays:
                continue

            src_pixels = pixel_arrays[tex_type]
            src_ch_idx = channel_indices.get(src_ch_str, 0)

            if src_ch_idx < src_pixels.shape[2]:
                src_h, src_w, _ = src_pixels.shape

                # If resolutions don't match, perform nearest-neighbor scaling
                if src_h != target_h or src_w != target_w:
                    # Simple nearest-neighbor upscale/downscale
                    row_indices = np.linspace(0, src_h - 1, target_h).astype(int)
                    col_indices = np.linspace(0, src_w - 1, target_w).astype(int)
                    pixels[:, :, dest_ch_idx] = src_pixels[row_indices[:, None], col_indices, src_ch_idx]
                else:
                    pixels[:, :, dest_ch_idx] = src_pixels[:, :, src_ch_idx]
                break


def _apply_post_actions(pixels: np.ndarray, config: dict):
    """Apply inversions and other pixel-wise operations."""
    actions = config.get("actions", {})
    channels = ["red", "green", "blue", "alpha"]

    for i, color_name in enumerate(channels):
        if actions.get(f"invert_{color_name}_channel"):
            pixels[:, :, i] = 1.0 - pixels[:, :, i]


def is_image_color(image: bpy.types.Image, color: tuple[float, ...], tolerance: float = 0.001) -> bool:
    """Check if an image consists entirely of a single color."""
    if not image or not image.has_data:
        return True

    pixels = np.empty(image.size[0] * image.size[1] * image.channels, dtype=np.float32)
    image.pixels.foreach_get(pixels)
    pixels = pixels.reshape((-1, image.channels))

    # Compare against target color for existing channels
    target = np.array(color[: image.channels], dtype=np.float32)
    return np.all(np.abs(pixels - target) < tolerance)
