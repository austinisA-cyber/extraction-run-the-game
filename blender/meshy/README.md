# Gothic Outfit – Meshy version

`meshy_outfit.py` sends the garment views from the character sheet to [Meshy](https://www.meshy.ai) and gets back a textured 3D model of each garment. It runs one multi-image-to-3D job per garment:

| Piece | Input images |
|---|---|
| Top | `input/top_front.png`, `input/top_back.png` |
| Skirt | `input/skirt_front.png`, `input/skirt_back.png` |

It saves `output/meshy_top.glb/.fbx` and `output/meshy_skirt.glb/.fbx`. If Blender's `bpy` module is available, it also combines them into `output/gothic_outfit_meshy.blend`.

```bash
export MESHY_API_KEY=msy_...        # https://www.meshy.ai/settings/api  (uses credits)
python meshy_outfit.py              # or run inside Blender: blender -b -P meshy_outfit.py
```

Options:
* `--only top|skirt`: run a single garment.
* `--single`: use only the front view (Meshy's image-to-3D endpoint).
* `--polycount N`: target polygon count. The default is 60k.
* `--triangles`: use triangle topology instead of quads.

Notes:
* Meshy rebuilds geometry from the pictures, so it can't guarantee "clothes only". The product shots on the sheet show some skin: the chest and shoulders on the top, and a thigh stand-in on the skirt. Meshy may include those as surfaces, and you can delete them in Blender's Edit Mode.
* Meshy produces a single fused mesh with baked textures. If you need separate, editable garment pieces with procedural lace, use the procedural model in `../gothic_outfit/`.
