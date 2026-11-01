#!/usr/bin/env python3
"""TBRenz carton tool: dieline PDF -> panel textures -> GLB model -> product renders.

Usage:
  python3 tbrenz_tool.py extract <dieline.pdf> [--dpi 400] [--art art]
  python3 tbrenz_tool.py glb     [--art art] [--out out/tbrenz.glb]
  python3 tbrenz_tool.py render  [--art art] [--out out/renders] [--size 3000x2000]
  python3 tbrenz_tool.py all     <dieline.pdf> [--dpi 400]

Needs: pdftoppm (poppler), Pillow and numpy (see requirements.txt). No Blender.

The brand wordmark is embossed: a normal map is built from its coloured pixels
and used in the GLB (normalTexture) and in the renders (relief shading).
"""
import argparse
import json
import math
import os
import struct
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

# Carton size, from the dimension callouts on the dieline (mm).
W_MM, H_MM, D_MM = 122.0, 72.0, 13.0

# Panel crop boxes in PDF points (72 pt = 1 inch), measured on the dieline page.
# Front/back are the 122 x 72 mm faces; top/bottom are the 13 mm flaps;
# side is the 13 mm right strip; glue is the left glue flap.
PANEL_BOXES = {
    "front":  (804.2,  51.7, 1145.3, 250.6),
    "back":   (804.2, 292.5, 1145.3, 491.5),
    "side":   (1149.0, 51.7, 1183.2, 250.6),
    "glue":   (766.3, 292.5,  800.4, 491.5),
    "top":    (804.2, 255.2, 1145.3, 287.3),
    "bottom": (804.2, 496.0, 1145.3, 528.0),
}

# Per-product settings. Panel boxes are PDF points (72 pt = 1 inch), measured on each dieline.
# Marijoint: 137 x 13 x 87 mm carton, flaps 13 mm, front wordmark "Marijoint".
PRODUCTS = {
    "tbrenz": {
        "boxes": PANEL_BOXES,
        "dims": (122.0, 72.0, 13.0),
        "emboss_box": (0.03, 0.42, 0.56, 0.59),
        "emboss_mode": "colour",
        "art": "art_tbrenz",
    },
    "marijoint": {
        "boxes": {
            "front":  (913.2,  24.2, 1299.6, 268.5),
            "back":   (913.2, 306.3, 1299.6, 551.3),
            "side":   (1299.6, 24.2, 1335.3, 268.5),
            "glue":   (875.9, 306.3,  913.2, 551.3),
            "top":    (913.2, 268.5, 1299.6, 304.8),
            "bottom": (913.2, 551.1, 1299.6, 589.1),
        },
        "dims": (137.0, 87.0, 13.0),
        "emboss_box": (0.03, 0.46, 0.50, 0.70),
        "emboss_mode": "colour_or_dark",
        "art": "art_marijoint",
    },
    # Maronerv-NT: 108 x 50 x 50 mm cuboid. Panels are PDF points, measured from the dieline
    # (front row, composition row, top row, marketed-by row, right and left side strips).
    "maronerve": {
        "boxes": {
            "front":  (197.0, 230.4, 502.8, 371.9),   # Pregabalin row (front)
            "back":   (197.0, 505.3, 502.8, 648.1),   # second Pregabalin row: opposite the front
            "top":    (197.0, 371.9, 502.8, 505.3),   # composition row: between front and back
            "bottom": (197.0, 648.1, 502.8, 780.1),   # marketed-by row
            "side":   (502.8, 230.4, 636.2, 371.9),
            "glue":   (63.5, 505.3, 197.0, 648.1),
        },
        "dims": (108.0, 50.0, 50.0),
        "emboss_box": (0.06, 0.55, 0.47, 0.78),
        "emboss_mode": "colour_or_dark",
        "art": "art_maronerve",
    },
    # Marbone HD: 128 x 12 x 71 mm tuck-top carton (front, composition, logo strip, side).
    "marbone": {
        "boxes": {
            "front":  (979.9, 247.5, 1343.1, 449.0),
            "back":   (979.9, 477.8, 1343.1, 678.8),
            "top":    (979.9, 449.0, 1343.1, 477.8),
            "bottom": (979.9, 678.8, 1343.1, 707.0),
            "side":   (1343.1, 247.5, 1377.2, 449.0),
            "glue":   (945.8, 477.8, 979.9, 678.8),
        },
        "dims": (128.0, 12.0, 71.0),
        "emboss_box": (0.08, 0.49, 0.46, 0.66),
        "emboss_mode": "colour_or_dark",
        "art": "art_marbone",
    },
    # Marwin-Gold: 132 x 11 x 82 mm tuck-top carton (flat dieline, right-hand layout).
    "marwin": {
        "boxes": {
            "front":  (924.9, 252.0, 1299.6, 485.1),
            "top":    (924.9, 485.1, 1299.6, 515.8),
            "back":   (924.9, 515.8, 1299.6, 747.6),
            "bottom": (924.9, 747.6, 1299.6, 778.3),
            "side":   (1299.6, 252.0, 1330.3, 485.1),
            "glue":   (894.2, 515.8, 924.9, 747.6),
        },
        "dims": (132.0, 11.0, 82.0),
        "emboss_box": (0.27, 0.35, 0.74, 0.48),
        "emboss_mode": "colour_or_dark",
        "art": "art_marwin",
    },
}


def set_product(name):
    """Point the module-level settings at one product (read at call time by the functions)."""
    global PANEL_BOXES, W_MM, H_MM, D_MM, EMBOSS_BOX, EMBOSS_MODE
    cfg = PRODUCTS[name]
    PANEL_BOXES = cfg["boxes"]
    W_MM, H_MM, D_MM = cfg["dims"]
    EMBOSS_BOX = cfg["emboss_box"]
    EMBOSS_MODE = cfg["emboss_mode"]
    return cfg["art"]


EMBOSS_MODE = "colour"

HERE = os.path.dirname(os.path.abspath(__file__))

# Emboss: wordmark region on the front panel, as fractions of the panel (x0, y0, x1, y1).
# Only coloured (blue/teal) pixels inside it count, so "Tablets" and the swoosh are left out.
EMBOSS_BOX = (0.03, 0.42, 0.56, 0.59)
EMBOSS_BLUR = 0.0035      # blur radius as a fraction of panel width (sets the edge softness)
EMBOSS_STRENGTH = 40.0    # steepness of the relief; higher = more pronounced edges
EMBOSS_RELIEF_GAIN = 0.45 # how strongly the relief shows in the renders
LIGHT = np.array([-0.35, 0.55, 0.75]) / np.linalg.norm([-0.35, 0.55, 0.75])


# ----------------------------------------------------------------- extract
def extract(pdf, dpi, art):
    os.makedirs(art, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        base = os.path.join(td, "page")
        subprocess.run(["pdftoppm", "-r", str(dpi), "-png", "-singlefile", pdf, base],
                       check=True, stderr=subprocess.DEVNULL)
        page = Image.open(base + ".png").convert("RGB")
        k = dpi / 72.0
        for name, (x0, y0, x1, y1) in PANEL_BOXES.items():
            box = tuple(round(v * k) for v in (x0, y0, x1, y1))
            out = os.path.join(art, name + ".png")
            page.crop(box).save(out)
            print(f"  {name:7s} {box[2]-box[0]}x{box[3]-box[1]} px -> {out}")
            if name == "front":
                build_normal_map(Image.open(out).convert("RGB"), os.path.join(art, "front_normal.png"))
                build_gloss_map(Image.open(out).convert("RGB"), os.path.join(art, "front_roughness.png"))
                print("  front_normal (emboss) and front_roughness (UV drip-off) written")


# ----------------------------------------------------------------- emboss
def build_normal_map(img, out):
    """Height map = blurred mask of the wordmark; normal map = its gradient.
    Encoded tangent-space, OpenGL convention (+Y = image up), as glTF expects."""
    a = np.asarray(img, dtype=np.float32) / 255.0
    H, W, _ = a.shape
    chroma = a.max(-1) - a.min(-1)
    mask = np.zeros((H, W), np.float32)
    x0, y0, x1, y1 = EMBOSS_BOX
    sl = (slice(int(y0 * H), int(y1 * H)), slice(int(x0 * W), int(x1 * W)))
    if EMBOSS_MODE == "colour_or_dark":
        dark = a.mean(-1) < 0.35
        mask[sl] = ((chroma[sl] > 0.25) | dark[sl]).astype(np.float32)
    else:
        mask[sl] = (chroma[sl] > 0.25).astype(np.float32)

    blur = Image.fromarray((mask * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(W * EMBOSS_BLUR))
    h = np.asarray(blur, np.float32) / 255.0
    dy, dx = np.gradient(h)            # dy: down the image rows, dx: across columns
    nx = -dx * EMBOSS_STRENGTH
    ny = dy * EMBOSS_STRENGTH          # image-down gradient is -up, so flip for +Y = up
    nz = np.ones_like(h)
    n = np.stack([nx, ny, nz], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    rgb = ((n * 0.5 + 0.5) * 255).round().astype(np.uint8)
    Image.fromarray(rgb, "RGB").save(out)


def build_gloss_map(img, out):
    """Roughness map (glTF metallicRoughness: G = roughness). Coloured graphics get
    low roughness, so they catch highlights like the UV drip-off spot on the artwork."""
    a = np.asarray(img, dtype=np.float32) / 255.0
    chroma = a.max(-1) - a.min(-1)
    coloured = (chroma > 0.2).astype(np.float32)
    coloured = np.asarray(Image.fromarray((coloured * 255).astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(2)), np.float32) / 255.0
    rough = 0.55 - (0.55 - 0.30) * coloured          # white/base 0.55, graphics 0.30
    h, w = rough.shape
    rgb = np.zeros((h, w, 3), np.uint8)
    rgb[..., 1] = (rough * 255).round().astype(np.uint8)
    Image.fromarray(rgb, "RGB").save(out)


def relief_factor(normal_path):
    """Per-pixel brightness multiplier from the normal map, for the renders."""
    n = np.asarray(Image.open(normal_path).convert("RGB"), np.float32) / 255.0 * 2 - 1
    lam = np.clip(n @ LIGHT, 0, 1)
    flat = max(0.0, LIGHT[2])
    return 1.0 + EMBOSS_RELIEF_GAIN * (lam - flat)


def apply_relief(tex, normal_path):
    f = relief_factor(normal_path)
    arr = np.asarray(tex, np.float32) * f[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


# ----------------------------------------------------------------- geometry
def carton_faces():
    """Each face: outward normal and corners [TL, TR, BR, BL] as seen from outside.
    Texture UV (0,0) is TL, so each artwork maps onto its face the right way round.
    Coordinates in metres, Y up, +Z toward the front panel."""
    w, h, d = W_MM / 2000, H_MM / 2000, D_MM / 2000
    return {
        "front":  ((0, 0, 1),  [(-w, h, d), (w, h, d), (w, -h, d), (-w, -h, d)]),
        "back":   ((0, 0, -1), [(w, h, -d), (-w, h, -d), (-w, -h, -d), (w, -h, -d)]),
        "side":   ((1, 0, 0),  [(w, h, d), (w, h, -d), (w, -h, -d), (w, -h, d)]),
        "glue":   ((-1, 0, 0), [(-w, h, -d), (-w, h, d), (-w, -h, d), (-w, -h, -d)]),
        # Flaps fold onto the front (top) and back (bottom): the texture edge that
        # was glued to the panel sits on the fold line.
        "top":    ((0, 1, 0),  [(-w, h, -d), (w, h, -d), (w, h, d), (-w, h, d)]),
        "bottom": ((0, -1, 0), [(-w, -h, -d), (w, -h, -d), (w, -h, d), (-w, -h, d)]),
    }


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


# ----------------------------------------------------------------- GLB writer
def write_glb(art, out):
    bin_buf = bytearray()
    buffer_views, accessors, images, textures, materials, primitives = [], [], [], [], [], []

    def add_view(data):
        while len(bin_buf) % 4:
            bin_buf.append(0)
        off = len(bin_buf)
        bin_buf.extend(data)
        buffer_views.append({"buffer": 0, "byteOffset": off, "byteLength": len(data)})
        return len(buffer_views) - 1

    def add_accessor(view, ctype, count, typ, extra=None):
        acc = {"bufferView": view, "componentType": ctype, "count": count, "type": typ}
        if extra:
            acc.update(extra)
        accessors.append(acc)
        return len(accessors) - 1

    FLOAT, UINT16 = 5126, 5123
    for i, (name, (normal, corners)) in enumerate(carton_faces().items()):
        # Winding: make the triangles counter-clockwise seen from outside.
        c = cross(sub(corners[1], corners[0]), sub(corners[2], corners[0]))
        idx = [0, 1, 2, 0, 2, 3] if dot(c, normal) > 0 else [0, 2, 1, 0, 3, 2]

        pos = b"".join(struct.pack("<3f", *p) for p in corners)
        nrm = b"".join(struct.pack("<3f", *normal) for _ in range(4))
        uv = b"".join(struct.pack("<2f", *t) for t in [(0, 0), (1, 0), (1, 1), (0, 1)])
        ind = struct.pack("<6H", *idx)

        xs, ys, zs = zip(*corners)
        a_pos = add_accessor(add_view(pos), FLOAT, 4, "VEC3",
                             {"min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]})
        a_nrm = add_accessor(add_view(nrm), FLOAT, 4, "VEC3")
        a_uv = add_accessor(add_view(uv), FLOAT, 4, "VEC2")
        a_idx = add_accessor(add_view(ind), UINT16, 6, "SCALAR")

        png = open(os.path.join(art, name + ".png"), "rb").read()
        images.append({"name": name, "bufferView": add_view(png), "mimeType": "image/png"})
        textures.append({"sampler": 0, "source": len(images) - 1})
        mat = {
            "name": name,
            "pbrMetallicRoughness": {"baseColorTexture": {"index": len(textures) - 1},
                                     "metallicFactor": 0.0, "roughnessFactor": 0.45},
            "doubleSided": False,
        }
        nfile = os.path.join(art, name + "_normal.png")
        if os.path.exists(nfile):
            images.append({"name": name + "_normal", "bufferView": add_view(open(nfile, "rb").read()),
                           "mimeType": "image/png"})
            textures.append({"sampler": 0, "source": len(images) - 1})
            mat["normalTexture"] = {"index": len(textures) - 1}
        rfile = os.path.join(art, name + "_roughness.png")
        if os.path.exists(rfile):
            images.append({"name": name + "_roughness", "bufferView": add_view(open(rfile, "rb").read()),
                           "mimeType": "image/png"})
            textures.append({"sampler": 0, "source": len(images) - 1})
            mat["pbrMetallicRoughness"]["metallicRoughnessTexture"] = {"index": len(textures) - 1}
            mat["pbrMetallicRoughness"]["roughnessFactor"] = 1.0
        materials.append(mat)
        primitives.append({"attributes": {"POSITION": a_pos, "NORMAL": a_nrm, "TEXCOORD_0": a_uv},
                           "indices": a_idx, "material": len(materials) - 1})

    gltf = {
        "asset": {"version": "2.0", "generator": "tbrenz_tool.py"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "TBRenz-DS carton"}],
        "meshes": [{"name": "TBRenz-DS carton", "primitives": primitives}],
        "materials": materials,
        "textures": textures,
        "images": images,
        "samplers": [{"magFilter": 9729, "minFilter": 9987, "wrapS": 33071, "wrapT": 33071}],
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": 0}],
        "extras": {"units": "metres", "carton_mm": [W_MM, H_MM, D_MM]},
    }
    while len(bin_buf) % 4:
        bin_buf.append(0)
    gltf["buffers"][0]["byteLength"] = len(bin_buf)

    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    total = 12 + 8 + len(js) + 8 + len(bin_buf)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, total))
        f.write(struct.pack("<I4s", len(js), b"JSON"))
        f.write(js)
        f.write(struct.pack("<I4s", len(bin_buf), b"BIN\0"))
        f.write(bin_buf)
    print(f"  wrote {out} ({total/1024:.0f} KiB)")


# ----------------------------------------------------------------- renderer
def rotate(p, yaw, pitch):
    x, y, z = p
    cy, sy = math.cos(yaw), math.sin(yaw)
    x, z = x * cy + z * sy, -x * sy + z * cy
    cp, sp = math.cos(pitch), math.sin(pitch)
    y, z = y * cp - z * sp, y * sp + z * cp
    return (x, y, z)


def solve(a, b):
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[piv] = m[piv], m[col]
        for r in range(n):
            if r != col and m[col][col] != 0:
                f = m[r][col] / m[col][col]
                for c in range(col, n + 1):
                    m[r][c] -= f * m[col][c]
    return [m[i][n] / m[i][i] for i in range(n)]


def perspective_coeffs(screen_quad, tex_size):
    """PIL PERSPECTIVE wants the inverse map: output (screen) -> input (texture)."""
    tw, th = tex_size
    src = [(0, 0), (tw, 0), (tw, th), (0, th)]
    rows, rhs = [], []
    for (x, y), (u, v) in zip(screen_quad, src):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); rhs.append(u)
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y]); rhs.append(v)
    return solve(rows, rhs)


def convex_hull(points):
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts
    def half(seq):
        out = []
        for p in seq:
            while len(out) >= 2 and (out[-1][0]-out[-2][0])*(p[1]-out[-2][1]) - (out[-1][1]-out[-2][1])*(p[0]-out[-2][0]) <= 0:
                out.pop()
            out.append(p)
        return out
    lower, upper = half(pts), half(pts[::-1])
    return lower[:-1] + upper[:-1]


def background(size):
    w, h = size
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    top, bot = (247, 247, 248), (219, 221, 225)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=tuple(round(top[i] + (bot[i] - top[i]) * t) for i in range(3)))
    return img


VIEWS = {
    "hero":   dict(yaw=-35, pitch=22),
    "front":  dict(yaw=0, pitch=0),
    "back":   dict(yaw=180, pitch=0),
    "side":   dict(yaw=-90, pitch=0),
    "left":   dict(yaw=90, pitch=0),
    "top":    dict(yaw=0, pitch=85),
    "bottom": dict(yaw=0, pitch=-85),
}
CAM_DIST = 0.9  # metres; long lens keeps the carton close to true proportions


def render_view(name, cfg, art, out_dir, size, ss=2):
    W, H = size[0] * ss, size[1] * ss
    faces = carton_faces()
    yaw, pitch = math.radians(cfg["yaw"]), math.radians(cfg["pitch"])
    cam = (0.0, 0.0, CAM_DIST)
    light = (-0.35, 0.55, 0.75)
    ln = math.sqrt(sum(c * c for c in light))
    light = tuple(c / ln for c in light)

    # Project every corner with unit scale, to fit the carton into the frame.
    def project(p, S):
        x, y, z = rotate(p, yaw, pitch)
        depth = CAM_DIST - z
        return (x * S / depth, -y * S / depth)

    all_pts = [project(p, 1.0) for _, (_, cs) in faces.items() for p in cs]
    xs, ys = [p[0] for p in all_pts], [p[1] for p in all_pts]
    bw, bh = max(xs) - min(xs), max(ys) - min(ys)
    S = min(W * 0.66 / bw, H * 0.62 / bh)
    ox = W / 2 - S * (max(xs) + min(xs)) / 2
    oy = H / 2 - S * (max(ys) + min(ys)) / 2

    def to_screen(p):
        x, y = project(p, S)
        return (x + ox, y + oy)

    canvas = background((W, H))

    # Soft contact shadow from the silhouette.
    hull = convex_hull([to_screen(p) for _, (_, cs) in faces.items() for p in cs])
    shadow = Image.new("L", (W, H), 0)
    dx, dy = S * 0.02, S * 0.07
    ImageDraw.Draw(shadow).polygon([(x + dx, y + dy) for x, y in hull], fill=90)
    shadow = shadow.filter(ImageFilter.GaussianBlur(S * 0.05))
    canvas.paste(Image.new("RGB", (W, H), (30, 32, 38)), (0, 0), shadow)

    # Draw visible faces. A box is convex, so no depth sorting is needed.
    for fname, (normal, corners) in faces.items():
        rn = rotate(normal, yaw, pitch)
        centre = tuple(sum(c[i] for c in corners) / 4 for i in range(3))
        rc = rotate(centre, yaw, pitch)
        if dot(rn, sub(cam, rc)) <= 0:
            continue
        tex = Image.open(os.path.join(art, fname + ".png")).convert("RGB")
        nfile = os.path.join(art, fname + "_normal.png")
        if os.path.exists(nfile):
            tex = apply_relief(tex, nfile)
        shade = 0.80 + 0.22 * max(0.0, dot(rn, light))
        tex = ImageEnhance.Brightness(tex).enhance(shade)
        quad = [to_screen(p) for p in corners]
        coeffs = perspective_coeffs(quad, tex.size)
        layer = tex.transform((W, H), Image.Transform.PERSPECTIVE, coeffs,
                              Image.Resampling.BICUBIC)
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).polygon(quad, fill=255)
        canvas.paste(layer, (0, 0), mask)

    canvas = canvas.resize(size, Image.Resampling.LANCZOS)
    path = os.path.join(out_dir, f"tbrenz_{name}.png")
    canvas.save(path)
    print(f"  wrote {path}")


def render_all(art, out_dir, size):
    os.makedirs(out_dir, exist_ok=True)
    for name, cfg in VIEWS.items():
        render_view(name, cfg, art, out_dir, size)


# ----------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub_ = ap.add_subparsers(dest="cmd", required=True)
    default_art = os.path.join(HERE, "art_tbrenz")
    default_out = os.path.join(HERE, "out")

    p = sub_.add_parser("extract"); p.add_argument("pdf"); p.add_argument("--dpi", type=int, default=400); p.add_argument("--art", default=default_art)
    p = sub_.add_parser("glb"); p.add_argument("--art", default=default_art); p.add_argument("--out", default=os.path.join(default_out, "tbrenz.glb"))
    p = sub_.add_parser("render"); p.add_argument("--art", default=default_art); p.add_argument("--out", default=os.path.join(default_out, "renders")); p.add_argument("--size", default="3000x2000")
    p = sub_.add_parser("studio", help="photoreal Cycles render via Blender (needs .venv-blender)")
    p.add_argument("--glb", default=os.path.join(default_out, "tbrenz.glb"))
    p.add_argument("--out", default=os.path.join(default_out, "blender"))
    p.add_argument("--size", default="3000x2000"); p.add_argument("--samples", type=int, default=128)
    p.add_argument("--views", default="hero,front,back,side,left,top,bottom")
    p = sub_.add_parser("all"); p.add_argument("pdf"); p.add_argument("--dpi", type=int, default=400)
    p.add_argument("--studio", action="store_true", help="also run the Cycles studio render")
    ap.add_argument("--product", default="tbrenz", choices=sorted(PRODUCTS))
    a = ap.parse_args()
    art_dir = set_product(a.product)
    if getattr(a, "art", None) in (None, default_art):
        a.art = os.path.join(HERE, art_dir)
    default_art = os.path.join(HERE, art_dir)

    def studio(glb, out, size, samples, views):
        py = os.path.join(HERE, ".venv-blender", "bin", "python")
        script = os.path.join(HERE, "blender_render.py")
        print("rendering studio (Cycles)")
        subprocess.run([py, script, "--", "--glb", glb, "--out", out, "--size", size,
                        "--samples", str(samples), "--views", views], check=True)

    if a.cmd in ("extract", "all"):
        print("extracting panels"); extract(a.pdf, a.dpi, a.art if a.cmd == "extract" else default_art)
    art = a.art if a.cmd in ("extract", "glb", "render") else default_art
    if a.cmd in ("glb", "all"):
        print("building GLB"); write_glb(art, os.path.join(default_out, "tbrenz.glb"))
    if a.cmd in ("render", "all"):
        w, h = (int(v) for v in ("3000x2000" if a.cmd == "all" else a.size).split("x"))
        print("rendering views"); render_all(art, os.path.join(default_out, "renders"), (w, h))
    if a.cmd == "studio":
        studio(a.glb, a.out, a.size, a.samples, a.views)
    if a.cmd == "all" and a.studio:
        studio(os.path.join(default_out, "tbrenz.glb"), os.path.join(default_out, "blender"),
               "3000x2000", 128, "hero,front,back,side,left,top,bottom")


if __name__ == "__main__":
    main()
