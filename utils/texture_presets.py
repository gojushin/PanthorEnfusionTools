"""Dynamic texture mapping presets."""

import json
import os

TEXTURE_PRESETS = {}


def load_presets():
    """Load all JSON texture presets from the presets directory."""
    global TEXTURE_PRESETS
    TEXTURE_PRESETS.clear()

    current_dir = os.path.dirname(os.path.abspath(__file__))
    presets_dir = os.path.join(os.path.dirname(current_dir), "presets")

    if not os.path.exists(presets_dir):
        return

    for filename in os.listdir(presets_dir):
        if filename.endswith(".json"):
            filepath = os.path.join(presets_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)

                key = os.path.splitext(filename)[0].upper()
                TEXTURE_PRESETS[key] = data
            except Exception as e:
                print(f"Panthor Enfusion Tools: Failed to load preset {filename}: {e}")


# Load presets upon module import
load_presets()


def get_preset_items(self, context):
    """Return a dynamic list of items for the EnumProperty."""
    items = [("NONE", "None", "Do not remap")]

    for key, data in TEXTURE_PRESETS.items():
        name = data.get("name", key)
        items.append((key, name, f"Use {name} mapping"))

    return items
