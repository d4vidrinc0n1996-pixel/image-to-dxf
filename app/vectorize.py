"""Raster image -> vector polygons -> SVG / DXF."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import ezdxf
import numpy as np

Polygon = np.ndarray  # shape (N, 2), float, pixel coordinates (y down)


class ImageError(ValueError):
    """The uploaded bytes are not a decodable image."""


@dataclass
class Options:
    threshold: int | None = None  # None -> Otsu automatic threshold
    invert: bool = False  # trace light shapes on a dark background
    blur: int = 0  # gaussian blur kernel (odd), 0 = off
    epsilon: float = 1.0  # polygon simplification tolerance, in pixels
    min_area: float = 20.0  # drop contours smaller than this (px^2)
    scale: float = 1.0  # DXF units per pixel (e.g. mm/px)


@dataclass
class Vector:
    width: int
    height: int
    polygons: list[Polygon]


def vectorize(data: bytes, opts: Options | None = None) -> Vector:
    opts = opts or Options()
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ImageError("No se pudo leer la imagen")

    if img.ndim == 3 and img.shape[2] == 4:  # flatten alpha onto white
        alpha = img[:, :, 3:4].astype(np.float32) / 255
        rgb = img[:, :, :3].astype(np.float32)
        img = (rgb * alpha + 255 * (1 - alpha)).astype(np.uint8)
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    if opts.blur > 1:
        k = opts.blur | 1
        gray = cv2.GaussianBlur(gray, (k, k), 0)

    # Shapes to trace are white in the mask.
    mode = cv2.THRESH_BINARY if opts.invert else cv2.THRESH_BINARY_INV
    if opts.threshold is None:
        _, mask = cv2.threshold(gray, 0, 255, mode | cv2.THRESH_OTSU)
    else:
        _, mask = cv2.threshold(gray, opts.threshold, 255, mode)

    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    polygons: list[Polygon] = []
    for c in contours:
        if cv2.contourArea(c) < opts.min_area:
            continue
        if opts.epsilon > 0:
            c = cv2.approxPolyDP(c, opts.epsilon, True)
        if len(c) >= 3:
            polygons.append(c.reshape(-1, 2).astype(float))
    h, w = gray.shape[:2]
    return Vector(w, h, polygons)


def to_svg(vec: Vector) -> str:
    d = " ".join(
        "M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in p) + " Z" for p in vec.polygons
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{vec.width}" '
        f'height="{vec.height}" viewBox="0 0 {vec.width} {vec.height}">'
        f'<path d="{d}" fill="black" fill-rule="evenodd"/></svg>'
    )


def to_dxf(vec: Vector, scale: float = 1.0) -> bytes:
    """DXF (R2010, millimetres). Y is flipped so the drawing isn't mirrored in CAD."""
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    for p in vec.polygons:
        pts = [(x * scale, (vec.height - y) * scale) for x, y in p]
        msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": "0"})
    from io import StringIO

    buf = StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")
