#!/usr/bin/env python3
"""Light unsharp mask on the renders, to restore edge detail lost to denoising and downscaling.

Usage: ./.venv/bin/python sharpen_renders.py out/hires
Writes *_sharp.png next to each render. Originals are kept.
"""
import glob
import os
import sys

from PIL import Image, ImageFilter

root = sys.argv[1] if len(sys.argv) > 1 else "out/hires"
# Radius scales with image width so the effect is the same at any render size.
for path in sorted(glob.glob(os.path.join(root, "**", "*_cycles.png"), recursive=True)):
    if path.endswith("_sharp.png"):
        continue
    im = Image.open(path).convert("RGB")
    radius = max(1.0, im.width / 2500)
    sharp = im.filter(ImageFilter.UnsharpMask(radius=radius, percent=70, threshold=2))
    out = path[: -len("_cycles.png")] + "_cycles_sharp.png"
    sharp.save(out)
    print("sharpened", out)
