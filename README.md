# TBRenz carton tool

Turns a CorelDRAW dieline PDF into:

- `out/tbrenz.glb`: a 122 × 72 × 13 mm carton model with the artwork on each face
- `out/renders/`: hero, front, back, side, left, top and bottom product shots (3000 × 2000)
- `art_tbrenz/` (per product: `art_<product>/`): the individual panel textures, plus `front_normal.png` (emboss)

## Requirements

- poppler's `pdftoppm` (`sudo pacman -S poppler` on Arch/CachyOS)
- Python packages in the venv: `./.venv/bin/pip install -r requirements.txt`

## Usage

```bash
cd ~/Desktop/Projects/PersonalProjects/tbrenz-tool

# everything, from a dieline PDF
./.venv/bin/python tbrenz_tool.py all "/home/aryan/Downloads/TBRenz-DS Tablet - CC.pdf" --dpi 400

# or step by step
./.venv/bin/python tbrenz_tool.py extract "<dieline.pdf>" --dpi 600   # higher-res textures
./.venv/bin/python tbrenz_tool.py glb
./.venv/bin/python tbrenz_tool.py render --size 4000x2667
```

## Changing the layout

Panel crop boxes live in `PANEL_BOXES` at the top of `tbrenz_tool.py`, in PDF points.
Carton size is `W_MM`, `H_MM`, `D_MM`. Change these if a new dieline has different
panels or dimensions. Camera angles are in `VIEWS`.

## Limits

- Renders are flat-shaded mockups, not photoreal.
- The wordmark emboss comes from a colour-based mask of the logo (`EMBOSS_BOX`); check the result if the artwork changes.
- Spot-UV drip-off is not modelled.
- Top and bottom flap artwork is stretched slightly to fit the 13 mm depth.

## Studio renders (Blender Cycles, photoreal)

Uses Blender's Python module (`bpy`) in a separate Python 3.11 venv, with GPU rendering (OptiX/CUDA).

```bash
# one-time setup
uv venv --python 3.11 .venv-blender
uv pip install --python .venv-blender/bin/python bpy pillow numpy

# render (after extract + glb)
./.venv/bin/python tbrenz_tool.py studio
./.venv/bin/python tbrenz_tool.py all "<dieline.pdf>" --studio
```

Output: `out/blender/tbrenz_<view>_cycles.png`. Floor, bevel, shadow, lights and camera are set in `blender_render.py`; light power is tuned there (high values wash the colours out).
The GLB is the single source for the artwork, emboss and gloss.
