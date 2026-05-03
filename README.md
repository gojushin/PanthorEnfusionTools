# Panthor Enfusion Tools

A robust Blender 4.2+ extension designed to streamline the pipeline for converting standard `.fbx` files into the Enfusion engine formats. 

## Features

- **FBX Importer**: Import FBX files with options to selectively keep or strip LODs and Collisions, automatically applying correct transformations.
- **Texture Conversion**: Automatically packs standard PBR textures into Enfusion's specific formats (BCR and NMO) using fast internal channel packing. Material nodes are set up automatically.
- **Collider Management**: 
  - Quickly fix and enumerate existing UCX/UBX colliders.
  - Add new primitive colliders (Box, Convex, Sphere, Capsule, Cylinder).
  - Validate colliders for proper origins, applied scale/rotation, and vertex limits.
- **LOD Management**: Dynamic UI list to create and manage Level of Details using Decimate modifiers with adjustable reduction ratios.
- **Enfusion Export**: Automatically applies modifiers, sets collider origins to geometry, and exports the final `.fbx` alongside the converted `.png` textures to a specified directory.

## Installation

1. Download the latest `.zip` release from the GitHub Releases page.
2. Open Blender (4.2 or higher).
3. Go to `Edit` -> `Preferences` -> `Get Extensions`.
4. Click the dropdown arrow on the top right, select `Install from Disk...`, and choose the downloaded `.zip` file.
5. Access the toolbox from the `Panthor` tab in the 3D Viewport sidebar (N-panel).

## Usage

1. **Import FBX**: Use the `Import FBX` button. Ensure you check or uncheck LODs and Collisions as needed.
2. **Import & Convert Textures**: Select a folder containing your PBR textures. They must follow standard naming conventions (`_BC`, `_N`, `_ORM`, etc.). The tool will pack them into `PTR_*_BCR` and `PTR_*_NMO` textures and assign them.
3. **Colliders**: Click `Fix Colliders` to ensure naming rules are enforced. Use the primitive buttons to quickly add new physics shapes. Run `Validate` to verify they meet Enfusion requirements.
4. **LODs**: Add new LODs using the `+` button in the UI list. Adjust the slider to set the decimation ratio.
5. **Export**: Use `Export to Enfusion` to output the processed FBX and converted Textures to your target directory.

## License
This project is licensed under the GPL-2.0-or-later License.
