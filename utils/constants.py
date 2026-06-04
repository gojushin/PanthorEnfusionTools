"""Constants for Panthor Enfusion Tools."""

# Collider Prefix Constants
COLLIDER_PREFIX_BOX = "UBX_"
COLLIDER_PREFIX_CONVEX = "UCX_"
COLLIDER_PREFIX_SPHERE = "USP_"
COLLIDER_PREFIX_CAPSULE = "UCS_"
COLLIDER_PREFIX_CYLINDER = "UCL_"

TEXTURE_SUFFIXES = {
    "BASECOLOR": ("basecolor", "bc", "bca", "albedo"),
    "NORMAL": ("n", "norm", "normal"),
    "ORM": ("orm", "occlusionroughnessmetallic"),
    "ROUGHNESS": ("rough", "roughness", "r"),
    "METALNESS": ("metalness", "m", "metallic"),
    "OPACITY": ("opacity", "alpha", "a"),
    "MASK": ("mask", "maskmap"),
    "AO": ("ao", "ambientocclusion", "occlusion"),
}

# Output Texture Prefixes and Suffixes
TEXTURE_PREFIX_ENFUSION = "PTR_"
TEXTURE_SUFFIX_ENFUSION_BCR = "_BCR"
TEXTURE_SUFFIX_ENFUSION_NMO = "_NMO"
TEXTURE_SUFFIX_ENFUSION_A = "_A"

# Other Constants
MAX_VERTS_COLLIDER = 65535

# Size used for solid (single-colour) placeholder images.  These are tiny because
# they contain no detail; _read_resized() will upscale them to match the packed
# map resolution at channel-packing time.
SOLID_IMAGE_SIZE = 4
