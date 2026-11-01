#!/usr/bin/env python3
"""Cycles studio render of the TBRenz carton GLB.

Run with the bpy venv (Python 3.11), not the main one:
  ./.venv-blender/bin/python blender_render.py -- --glb out/tbrenz.glb --out out/blender
Called by tbrenz_tool.py ("blender" subcommand).

The GLB is the single source of truth: artwork, emboss (normalTexture) and
gloss (metallicRoughnessTexture) all come from it.
"""
import argparse
import math
import os
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
ap = argparse.ArgumentParser()
ap.add_argument("--glb", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--size", default="3000x2000")
ap.add_argument("--samples", type=int, default=128)
ap.add_argument("--views", default="hero,front,back,side,left,top,bottom")
ap.add_argument("--device", default="OPTIX", choices=["OPTIX", "CUDA", "CPU"])
ap.add_argument("--name", default="tbrenz", help="filename prefix for the renders")
ap.add_argument("--light-scale", type=float, default=0.6)
args = ap.parse_args(argv)
W, H = (int(v) for v in args.size.split("x"))

# Same view angles as tbrenz_tool.py VIEWS (yaw, pitch in degrees).
VIEWS = {
    "hero":   (-35, 22),
    "front":  (-14, 10),
    "flat":   (0, 0),
    "topdown": (0, 0),
    "back":   (166, 10),
    "side":   (-90, 0),
    "left":   (90, 0),
    "top":    (0, 85),
    "bottom": (0, -85),
}

# ---------------------------------------------------------------- scene
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=os.path.abspath(args.glb))
carton = next(o for o in bpy.context.scene.objects if o.type == "MESH")
carton.rotation_mode = "ZXY"  # apply yaw (Z) first, then pitch (X): same order as the PIL renderer

# glTF stores each face with its own vertices, so the box comes in as 6 loose quads.
# Weld coincident corners so the edges are shared, which the bevel needs.
bpy.context.view_layer.objects.active = carton
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.remove_doubles(threshold=1e-6)
bpy.ops.object.mode_set(mode="OBJECT")

# Tuck-top lid: split the top panel off as its own flap, give it paper thickness and lift
# it a hair, so the seam to the front shows the way it does on a real folded carton.
bpy.ops.object.mode_set(mode="OBJECT")
for poly in carton.data.polygons:
    poly.select = poly.normal.z > 0.9          # Blender Z is up (glTF +Y): the top face
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.separate(type="SELECTED")
bpy.ops.object.mode_set(mode="OBJECT")
lid = next(o for o in bpy.context.scene.objects if o.type == "MESH" and o is not carton)
lid.name = "lid"
lid.parent = carton
lid.location = (0, 0, 0.0015)
lid.modifiers.new("thickness", "SOLIDIFY").thickness = 0.0004
bpy.context.view_layer.objects.active = carton

# Bevel the edges so the box catches light like a real carton.
bev = carton.modifiers.new("bevel", "BEVEL")
bev.width = 0.0012
bev.segments = 4
bev.limit_method = "ANGLE"
bev.angle_limit = math.radians(30)
print("  bevel modifiers on carton:", [m.type for m in carton.modifiers], flush=True)

# Keep the print colours saturated: low specular so the box does not turn white-washed.
for mat in carton.data.materials:
    if mat and mat.use_nodes:
        for node in mat.node_tree.nodes:
            if node.bl_idname == "ShaderNodeBsdfPrincipled":
                node.inputs["Specular IOR Level"].default_value = 0.5

# Smooth shading across the bevel so the edges roll off like a real folded carton,
# instead of stepping from face to face.
bpy.context.view_layer.objects.active = carton
bpy.ops.object.shade_smooth_by_angle(angle=math.radians(35))

# Studio sweep: one curved plane that runs from the floor up behind the carton, so there is
# no seam between floor and wall. Built from a subdivided plane bent around a radius.
import bmesh as _bmesh
bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, 0))
floor = bpy.context.active_object
floor.name = "floor"
_bm = _bmesh.new()
_bm.from_mesh(floor.data)
_bmesh.ops.subdivide_edges(_bm, edges=_bm.edges[:], cuts=80)
Y0, R = 0.5, 0.9
for v in _bm.verts:
    y = v.co.y
    if y <= Y0:
        v.co.z = 0.0
        continue
    t = y - Y0
    if t < R:
        a = t / R * (math.pi / 2)
        v.co.y = Y0 + R * math.sin(a)
        v.co.z = R * (1 - math.cos(a))
    else:
        v.co.y = Y0 + R
        v.co.z = R + (t - R)
_bm.to_mesh(floor.data)
_bm.free()
floor.data.update()
fm = bpy.data.materials.new("floor")
fm.use_nodes = True
fm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.9, 0.9, 0.91, 1)
fm.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.9
floor.data.materials.append(fm)
floor.is_shadow_catcher = True  # only the shadow lands on the floor; the backdrop is composited later

# ---- High-key studio lighting -------------------------------------------------
# Even ambient world so the backdrop reads as bright studio paper.
world = bpy.context.scene.world or bpy.data.worlds.new("world")
bpy.context.scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes["Background"]
bg.inputs["Color"].default_value = (0.92, 0.92, 0.93, 1)
bg.inputs["Strength"].default_value = 0.45 * args.light_scale


def softbox(name, loc, target, power, size):
    data = bpy.data.lights.new(name, "AREA")
    data.energy = power * args.light_scale
    data.size = size
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = Vector(loc)
    direction = Vector(target) - obj.location
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return obj


# Large overhead softbox: produces the soft contact shadow under the carton.
softbox("overhead", (0.0, 0.35, 1.2), (0, 0, 0), 70, 2.5)
# Two soft front lights for even face lighting, no harsh hotspot.
softbox("left", (-0.9, -0.7, 0.45), (0, 0, 0), 30, 1.6)
softbox("right", (0.9, -0.7, 0.35), (0, 0, 0), 14, 1.6)

# Camera: 85 mm product lens, looking along +Y from -Y.
cam_data = bpy.data.cameras.new("cam")
cam_data.lens = 85
cam_data.sensor_width = 36
cam = bpy.data.objects.new("cam", cam_data)
bpy.context.scene.collection.objects.link(cam)
bpy.context.scene.camera = cam
cam.location = (0, -0.48, 0)
cam.rotation_euler = (math.pi / 2, 0, 0)

# ---------------------------------------------------------------- render settings
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.render.resolution_x = W
scene.render.resolution_y = H
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = "PNG"
scene.cycles.samples = args.samples
scene.cycles.use_denoising = True
scene.cycles.denoiser = "OPTIX" if args.device == "OPTIX" else "OPENIMAGEDENOISE"
scene.view_settings.view_transform = "Standard"
scene.render.film_transparent = True
scene.view_settings.look = "None"

prefs = bpy.context.preferences.addons["cycles"].preferences
if args.device == "CPU":
    scene.cycles.device = "CPU"
else:
    prefs.compute_device_type = args.device
    prefs.refresh_devices()
    for d in prefs.devices:
        d.use = d.type == args.device
    scene.cycles.device = "GPU"
    print("  cycles device:", args.device, [d.name for d in prefs.devices if d.use], flush=True)

def _composite_backdrop(path):
    """Put the transparent render over a light studio gradient (reference look)."""
    from PIL import Image as _Image
    fg = _Image.open(path).convert("RGBA")
    w, h = fg.size
    top, bot = (255, 255, 255), (234, 235, 237)
    grad = _Image.new("RGBA", (w, h))
    px = grad.load()
    for y in range(h):
        t = y / max(1, h - 1)
        c = tuple(round(top[i] + (bot[i] - top[i]) * t) for i in range(3)) + (255,)
        for x in range(w):
            px[x, y] = c
    # Soft contact shadow under the carton: a blurred ellipse at the carton's base.
    from PIL import ImageDraw as _Draw, ImageFilter as _Filter
    alpha = fg.split()[3].point(lambda v: 255 if v > 200 else 0)
    box = alpha.getbbox()
    if box:
        x0, y0, x1, y1 = box
        bw, bh = x1 - x0, y1 - y0
        mask = _Image.new("L", (w, h), 0)
        sh = bh * 0.06
        _Draw.Draw(mask).ellipse(
            [x0 + bw * 0.10, y1 - sh * 1.6, x1 + bw * 0.06, y1 + sh * 0.2], fill=120)
        mask = mask.filter(_Filter.GaussianBlur(sh * 0.9))
        shadow = _Image.new("RGBA", (w, h), (40, 42, 46, 0))
        shadow.putalpha(mask)
        grad.alpha_composite(shadow)
    grad.alpha_composite(fg)
    grad.convert("RGB").save(path)


# ---------------------------------------------------------------- views
os.makedirs(args.out, exist_ok=True)
for name in args.views.split(","):
    yaw, pitch = VIEWS[name]
    if name == "topdown":
        cam.location = (0, 0, 0.5)
        cam.rotation_euler = (0, 0, 0)
    else:
        cam.location = (0, -0.48, 0)
        cam.rotation_euler = (math.pi / 2, 0, 0)
    carton.rotation_euler = (math.radians(pitch), 0, math.radians(yaw))
    bpy.context.view_layer.update()
    # Rest the carton on the floor: the floor follows the lowest corner after rotation.
    lowest = min((carton.matrix_world @ Vector(c)).z for c in carton.bound_box)
    floor.location = (0, 0, lowest)
    bpy.context.view_layer.update()
    scene.render.filepath = os.path.join(os.path.abspath(args.out), f"{args.name}_{name}_cycles.png")
    bpy.ops.render.render(write_still=True)
    _composite_backdrop(scene.render.filepath)
    print("  wrote", scene.render.filepath, flush=True)
