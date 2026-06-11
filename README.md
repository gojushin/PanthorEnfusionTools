[![Build Plugins](https://github.com/gojushin/PanthorEnfusionTools/actions/workflows/build.yml/badge.svg)](https://github.com/gojushin/PanthorEnfusionTools/actions/workflows/build.yml)

# Panthor Enfusion Tools

A Blender 4.2+ extension designed to streamline the conversion and editing of `.fbx` assets for the Enfusion engine. It supports assets from common workflows such as Unreal Engine, Unity, and standard PBR Metal/Rough pipelines.

The addon can also be integrated into existing industry-standard Metal/Rough workflows, providing tools for creating and managing Enfusion materials, colliders, and LODs directly within Blender.

---

## Features

### FBX Importer

- Import FBX, while automatically applying the required transformations for Enfusion compatibility.

### Texture Conversion

- Automatically converts and packs PBR textures from various sources into Enfusion's required formats (`BCR` and `NMO`) using fast internal channel packing.
- Textures are automatically transferred to Workbench and registered when available.
- Materials are configured using Enfusion Materials when the Enfusion Blender Tools are installed.
- If Enfusion Blender Tools are unavailable, a compatible node graph using Bohemia's texture packing workflow is generated automatically.

### Bake & Remap Materials

- For objects with **no texture files** or **arbitrary procedural / node-based setups**, bake the entire Principled BSDF shading network down to flat textures at a selectable resolution (16 – 4096 px) and remap them automatically into Enfusion-compatible `BCR`/`NMO` textures.
- Flat (default/constant) material values are handled without baking – no texture is created unnecessarily.
- Supports the full ENF material pipeline including Workbench registration and EBT assignment.

### Collider Management

- Quickly fix and enumerate existing `UCX`/`UBX` colliders.
- Create new primitive colliders:
  - Box
  - Convex
  - Sphere
  - Capsule
  - Cylinder

- Validate colliders for:
  - Correct origins
  - Applied scale and rotation
  - Vertex count limits

(see more: https://community.bistudio.com/wiki/Arma_Reforger:FBX_Import#Collider_shape)

### LOD Management

- Create and manage Levels of Detail through a dynamic UI list.
- Uses Blender's Decimate modifier with adjustable reduction ratios.

### Enfusion Export

- Automatically applies modifiers and adjusts collider origins before export.
- Exports the processed `.fbx` and converted `.png` textures to a target directory.
- Can export directly into an Arma Reforger project using the Enfusion Blender Tools.

---

## Installation

1. Download the latest `.zip` release from the GitHub Releases page.
2. Open Blender 4.2 or newer.
3. Navigate to **Edit → Preferences → Get Extensions**.
4. Open the dropdown menu in the top-right corner and select **Install from Disk...**.
5. Select the downloaded `.zip` file.
6. Install the Enfusion Blender Tools (`EBT-ArmaReforger.zip`) as well. Follow Bohemia Interactive's official guide:

   https://community.bistudio.com/wiki/Arma_Reforger:Enfusion_Blender_Tools

> **Important**
>
> Do not skip the step **"Enable Net API (for communication with external applications)"** in the Enfusion Blender Tools setup.

7. Access the addon from the **Panthor** tab in the 3D Viewport sidebar (`N` panel).

---

## Usage

> **Note**
>
> For the best experience, keep Workbench running while using the addon.

### 1. Import FBX

Use the **Import FBX** button to import your asset.

To export directly into a Workbench project:

- Set the destination path to your Workbench project directory.
- Enable **Create ENF Materials**.

### 2. Import & Convert Textures

Select a folder containing your PBR textures.

Supported naming conventions include common suffixes such as:

- `_BC`
- `_N`
- `_ORM`

The addon automatically generates:

- `PTR_*_BCR`
- `PTR_*_NMO`

and assigns them to the imported materials.

### 2b. Bake & Remap Materials

Use **Bake & Remap Materials** for objects that have **no texture files** or whose look is driven entirely by an **arbitrary node graph** (e.g. imported models with only colours set, or assets built with procedural shader nodes).

1. Select the desired output resolution from the dropdown to the right of the button (16 – 4096 px, default 1024).
2. Click **Bake & Remap Materials**.

The operator processes every material on every mesh object in the scene:

| Principled BSDF Input | Condition                      | Action                                                           |
| --------------------- | ------------------------------ | ---------------------------------------------------------------- |
| **Base Color**        | No link (flat colour)          | Sets the colour directly on the ENF material; no texture baked   |
| **Base Color**        | Has a node link                | Baked into `PTR_*_BCR` (RGB channels)                            |
| **Roughness**         | No link, value = 0.5 (default) | Skipped                                                          |
| **Roughness**         | No link, value ≠ 0.5           | Solid-colour image written into `PTR_*_BCR` (Alpha channel)      |
| **Roughness**         | Has a node link                | Baked, packed into `PTR_*_BCR` (Alpha channel)                   |
| **Metallic**          | No link, value = 0.0 (default) | Skipped                                                          |
| **Metallic**          | No link, value ≠ 0.0           | Solid-colour image written into `PTR_*_NMO` (Blue channel)       |
| **Metallic**          | Has a node link                | Baked via Emission trick, packed into `PTR_*_NMO` (Blue channel) |
| **Normal**            | No link                        | Skipped                                                          |
| **Normal**            | Has a node link                | Baked into `PTR_*_NMO` (RG channels)                             |
| **Alpha**             | No link, value = 1.0 (default) | Skipped                                                          |
| **Alpha**             | Non-default or has a node link | Baked / solid image assigned as `PTR_*_A` Opacity Map            |

The resulting textures are packed into the `.blend` file. When **Create ENF Materials** is enabled and a Workbench path is set, they are saved to disk, registered with Workbench, and assigned to a `MatPBRBasic` Enfusion material via EBT. Without EBT, a Principled BSDF node graph is reconstructed automatically.

> **Note:** Baking requires the **Cycles** render engine. The addon switches to Cycles automatically and restores the original engine afterwards. Meshes without UV maps receive an automatic Smart UV Project unwrap before baking.
>
> Only materials using a **Principled BSDF** as their material output can be processed. Materials with unsupported node setups are skipped and reported as warnings.

### 3. Manage Colliders

Use **Fix Colliders** to:

- Enforce naming conventions.
- Rebuild invalid colliders when possible.

Use the primitive creation tools to add new collision shapes.

Run **Validate** to verify that colliders meet Enfusion requirements.

### 4. Create LODs

- Add new LODs using the **+** button.
- Adjust the decimation ratio using the provided slider.

### 5. Export

#### Export FBX for Enfusion

Exports the processed FBX and converted textures to a selected directory.

#### Export Using EBT

Uses the Enfusion Blender Tools to export directly into your Workbench project.

---

## Presets

The addon includes a `presets` folder that defines texture packing and channel mapping rules.

You can easily extend the addon by creating your own presets and adding them to this directory.

---

## License

This project is licensed under the **GPL-2.0-or-later** license.
