#!/usr/bin/env python3
"""Spot-UV (UV drip-off) maps for the front panel, built from art/front.png.

Coloured graphics get low roughness (glossy) and a fine bump texture, like the
UV drip-off in the reference. Writes art/front_roughness.png and art/front_normal.png,
keeping the emboss relief on the wordmark.
"""
import os
import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ART = os.path.join(HERE, "art_tbrenz")
GLOSS_ROUGH = 0.12   # glossy spot
BASE_ROUGH = 0.55    # uncoated paper
BUMP = 0.08          # strength of the fine orange-peel texture

img = Image.open(os.path.join(ART, "front.png")).convert("RGB")
a = np.asarray(img, np.float32) / 255.0
H, W, _ = a.shape
chroma = a.max(-1) - a.min(-1)
mask = (chroma > 0.2).astype(np.uint8) * 255
soft = np.asarray(Image.fromarray(mask).filter(ImageFilter.GaussianBlur(2)), np.float32) / 255.0

# Roughness map: G channel.
rough = BASE_ROUGH - (BASE_ROUGH - GLOSS_ROUGH) * soft
rgb = np.zeros((H, W, 3), np.uint8)
rgb[..., 1] = (rough * 255).round().astype(np.uint8)
Image.fromarray(rgb, "RGB").save(os.path.join(ART, "front_roughness.png"))

# Normal map: keep the emboss from the wordmark, add fine noise on the gloss areas.
emboss = np.asarray(Image.open(os.path.join(ART, "front_normal.png")).convert("RGB"), np.float32) / 255.0 * 2 - 1
rng = np.random.default_rng(7)
noise = rng.standard_normal((H, W)).astype(np.float32)
noise = np.asarray(Image.fromarray(((noise * 40) + 128).clip(0, 255).astype(np.uint8)).filter(
    ImageFilter.GaussianBlur(1.2)), np.float32) / 255.0 * 2 - 1
gx = np.gradient(noise, axis=1) * BUMP * 60
gy = np.gradient(noise, axis=0) * BUMP * 60
nx = emboss[..., 0] + gx * soft
ny = emboss[..., 1] + gy * soft
nz = np.ones_like(nx)
n = np.stack([nx, ny, nz], -1)
n /= np.linalg.norm(n, axis=-1, keepdims=True)
out = ((n * 0.5 + 0.5) * 255).round().astype(np.uint8)
Image.fromarray(out, "RGB").save(os.path.join(ART, "front_normal.png"))
print("coloured gloss area: %.1f%% of panel" % (soft.mean() * 100))
