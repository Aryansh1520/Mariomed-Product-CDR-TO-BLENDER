#!/usr/bin/env python3
"""Retexture a reference box GLB with the TBRenz artwork.

Run with the bpy venv:
  ./.venv-blender/bin/python retexture_box.py -- --src ~/Downloads/Box-3D-model.glb \
      --art art --out out/tbrenz_retextured.glb

The reference box is scaled to the carton dimensions (122 x 72 x 13 mm), each face
gets its panel artwork (front, back, side, glue, top, bottom) with planar UVs, and the
result is exported as a GLB that blender_render.py can read.
"""
import argparse
import os
import sys

import bpy
import bmesh

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--src", required=True)
ap.add_argument("--art", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--dims", default="122,13,72", help="carton W,D,H in mm")
args = ap.parse_args(argv)
art = os.path.abspath(args.art)

# Carton size in metres, Blender axes: X width, Y depth, Z height.
_dims = [float(v) for v in args.dims.split(",")]
TARGET = (_dims[0] / 1000, _dims[1] / 1000, _dims[2] / 1000)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=os.path.abspath(args.src))
obj = next(o for o in bpy.context.scene.objects if o.type == "MESH")
bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
dims = obj.dimensions
obj.scale = (TARGET[0] / dims.x, TARGET[1] / dims.y, TARGET[2] / dims.z)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

mesh = obj.data
# Centre the carton on the origin so the camera frames it the same way as the other models.
_c = [sum(v.co[i] for v in mesh.vertices) / len(mesh.vertices) for i in range(3)]
_bb = [(min(v.co[i] for v in mesh.vertices) + max(v.co[i] for v in mesh.vertices)) / 2 for i in range(3)]
for v in mesh.vertices:
    v.co.x -= _bb[0]; v.co.y -= _bb[1]; v.co.z -= _bb[2]
xs = [v.co.x for v in mesh.vertices]; ys = [v.co.y for v in mesh.vertices]; zs = [v.co.z for v in mesh.vertices]
xmin, xmax, ymin, ymax, zmin, zmax = min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)
W, D, H = xmax - xmin, ymax - ymin, zmax - zmin

# Panel per face. Blender: -Y is the front, +Y the back, +X right side, -X glue flap,
# +Z top flap, -Z bottom flap.
PANELS = ["front", "back", "side", "glue", "top", "bottom"]


def panel_for(n):
    if n.y < -0.5: return 0
    if n.y > 0.5: return 1
    if n.x > 0.5: return 2
    if n.x < -0.5: return 3
    if n.z > 0.5: return 4
    return 5


def uv_for(idx, co):
    x, y, z = co.x, co.y, co.z
    if idx == 0:   # front, viewed from -Y: un-mirror horizontally
        return ((x - xmin) / W, (z - zmin) / H)
    if idx == 1:   # back, viewed from +Y
        return ((xmax - x) / W, (z - zmin) / H)
    if idx == 2:   # right side, viewed from +X
        return ((ymax - y) / D, (zmax - z) / H)
    if idx == 3:   # glue flap, viewed from -X
        return ((y - ymin) / D, (zmax - z) / H)
    if idx == 4:   # top flap: artwork top-left = back-left corner when seen from above
        return ((x - xmin) / W, (y - ymin) / D)
    # bottom flap: row 0 is the edge away from the front (+Y)
    return ((x - xmin) / W, (ymax - y) / D)


def make_material(name, png, extra=None):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Specular IOR Level"].default_value = 0.5
    bsdf.inputs["Roughness"].default_value = 0.55
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = bpy.data.images.load(os.path.join(art, png), check_existing=True)
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    # Faint self-illumination from the same artwork, so every side stays readable in viewers
    # whose light comes from one direction. Colours come from the artwork, not a white glow.
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
    bsdf.inputs["Emission Strength"].default_value = 0.18
    if extra == "front":
        nmap_tex = nt.nodes.new("ShaderNodeTexImage")
        nmap_tex.image = bpy.data.images.load(os.path.join(art, "front_normal.png"), check_existing=True)
        nmap_tex.image.colorspace_settings.name = "Non-Color"
        nmap = nt.nodes.new("ShaderNodeNormalMap")
        nt.links.new(nmap_tex.outputs["Color"], nmap.inputs["Color"])
        nt.links.new(nmap.outputs["Normal"], bsdf.inputs["Normal"])
        rough_tex = nt.nodes.new("ShaderNodeTexImage")
        rough_tex.image = bpy.data.images.load(os.path.join(art, "front_roughness.png"), check_existing=True)
        rough_tex.image.colorspace_settings.name = "Non-Color"
        sep = nt.nodes.new("ShaderNodeSeparateColor")
        nt.links.new(rough_tex.outputs["Color"], sep.inputs["Color"])
        nt.links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
    return mat


# Material slots follow the face: slot 0 is the -Y face, slot 1 the +Y face. The camera
# sees the +Y face, so the front artwork goes on +Y and the back artwork on -Y.
SLOT_ART = {0: ("front.png", "front"), 1: ("back.png", None)}
mats = []
for i, p in enumerate(PANELS):
    png, extra = SLOT_ART.get(i, (p + ".png", None))
    mats.append(make_material(p, png, extra))
mesh.materials.clear()
for m in mats:
    mesh.materials.append(m)

# Planar UVs and material per face, written per loop.
uv_layer = mesh.uv_layers.active or mesh.uv_layers.new(name="UVMap")
bm = bmesh.new()
bm.from_mesh(mesh)
# Classify faces by axis (from the stored normal, which is reliable up to sign) and by sign
# (which side of the box centre the face sits on). The reference mesh has unreliable winding.
cx, cy, cz = (xmin + xmax) / 2, (ymin + ymax) / 2, (zmin + zmax) / 2
from mathutils import Vector as _V
flip = []
for f in bm.faces:
    n = f.normal
    ax = max(range(3), key=lambda i: abs(n[i]))
    c = f.calc_center_median()
    off = (c.x - cx, c.y - cy, c.z - cz)[ax]
    eff = [0.0, 0.0, 0.0]
    eff[ax] = 1.0 if off >= 0 else -1.0
    idx = panel_for(_V(eff))
    f.material_index = idx
    # Make the stored normal point outward (matches the classified direction).
    if n.dot(_V(eff)) < 0:
        flip.append(f)
    for loop in f.loops:
        loop[bm.loops.layers.uv.active].uv = uv_for(idx, loop.vert.co)
if flip:
    bmesh.ops.reverse_faces(bm, faces=flip)
bm.to_mesh(mesh)
bm.free()
mesh.update()

os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=os.path.abspath(args.out), export_format="GLB", use_selection=False)
print("  wrote", args.out, "dims", round(W, 4), round(D, 4), round(H, 4), flush=True)
