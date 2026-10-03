"""Imagen raster -> trazados vectoriales (líneas / curvas Bézier) por capas de color -> SVG / DXF."""
from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field

import cv2
import ezdxf
import numpy as np
import potrace
from ezdxf.colors import rgb2int
from ezdxf.math import Bezier4P, Vec2, bezier_to_bspline

Point = tuple[float, float]
# (c1, c2, end): curva Bézier cúbica.  (None, None, end): línea recta.
Segment = tuple["Point | None", "Point | None", Point]


class ImageError(ValueError):
    """Los bytes recibidos no son una imagen legible."""


@dataclass
class Options:
    colors: int = 1  # 1 = blanco/negro; 2..16 = capas por color
    threshold: int | None = None  # solo colors=1; None -> Otsu automático
    invert: bool = False  # solo colors=1: trazar zonas claras
    blur: int = 0  # suavizado previo (kernel gaussiano impar), 0 = off
    curves: bool = True  # True: curvas Bézier; False: polígonos
    smooth: float = 1.0  # 0 = todo esquinas, ~1.33 = muy redondeado
    opt_tolerance: float = 0.2  # tolerancia al unir curvas (mayor = menos nodos)
    epsilon: float = 1.0  # simplificación de polígonos (curves=False)
    min_area: float = 20.0  # descarta manchas menores (px²)
    skip_background: bool = True  # colors>1: no vectoriza el color de fondo
    max_dim: int = 2000  # reduce imágenes más grandes para ir más rápido
    # --- DXF ---
    scale: float = 1.0  # unidades por píxel original
    width_mm: float | None = None  # alternativa: ancho final del dibujo
    dxf_curves: str = "spline"  # "spline" | "polyline" (más compatible)
    tolerance: float = 0.1  # error de aplanado (unidades DXF) en "polyline"


@dataclass
class Path:
    start: Point
    segments: list[Segment]


@dataclass
class Layer:
    name: str
    color: tuple[int, int, int]
    paths: list[Path] = field(default_factory=list)


@dataclass
class Vector:
    width: int  # tamaño original de la imagen
    height: int
    layers: list[Layer]
    ratio: float = 1.0  # píxel original / píxel trazado (si se redujo)
    traced_w: int = 0
    traced_h: int = 0

    @property
    def path_count(self) -> int:
        return sum(len(layer.paths) for layer in self.layers)


# ---------------------------------------------------------------- trazado ---

def _hex(rgb) -> str:
    return "{:02X}{:02X}{:02X}".format(*rgb)


def _trace_mask(mask: np.ndarray, o: Options) -> list[Path]:
    """mask: bool, True = zona a vectorizar."""
    if o.curves:
        bm = potrace.Bitmap(~mask)  # potracer traza lo que NO es True
        plist = bm.trace(
            turdsize=int(o.min_area),
            turnpolicy=potrace.POTRACE_TURNPOLICY_MINORITY,
            alphamax=o.smooth,
            opticurve=o.opt_tolerance > 0,
            opttolerance=max(o.opt_tolerance, 1e-6),
        )
        out = []
        for c in plist:
            segs: list[Segment] = []
            for s in c.segments:
                end = (s.end_point.x, s.end_point.y)
                if s.is_corner:
                    segs.append((None, None, (s.c.x, s.c.y)))
                    segs.append((None, None, end))
                else:
                    segs.append(((s.c1.x, s.c1.y), (s.c2.x, s.c2.y), end))
            out.append(Path((c.start_point.x, c.start_point.y), segs))
        return out

    contours, _ = cv2.findContours(
        mask.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE
    )
    out = []
    for c in contours:
        if cv2.contourArea(c) < o.min_area:
            continue
        if o.epsilon > 0:
            c = cv2.approxPolyDP(c, o.epsilon, True)
        if len(c) >= 3:
            pts = [(float(x), float(y)) for x, y in c.reshape(-1, 2)]
            out.append(Path(pts[0], [(None, None, p) for p in pts[1:] + pts[:1]]))
    return out


def _quantize(img: np.ndarray, k: int):
    """k-means sobre una muestra; devuelve (etiquetas HxW, centros BGR)."""
    h, w = img.shape[:2]
    flat = img.reshape(-1, 3).astype(np.float32)
    rng = np.random.default_rng(0)
    sample = flat[rng.choice(len(flat), min(len(flat), 50_000), replace=False)]
    cv2.setRNGSeed(0)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    _, _, centers = cv2.kmeans(sample, k, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    labels = np.empty(len(flat), np.int32)
    for i in range(0, len(flat), 200_000):  # por bloques para no gastar memoria
        d = ((flat[i : i + 200_000, None, :] - centers[None]) ** 2).sum(-1)
        labels[i : i + 200_000] = d.argmin(1)
    return labels.reshape(h, w), centers


def vectorize(data: bytes, opts: Options | None = None) -> Vector:
    o = opts or Options()
    if not 1 <= o.colors <= 16:
        raise ValueError("colors debe estar entre 1 y 16")
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ImageError("No se pudo leer la imagen")
    if img.dtype != np.uint8:  # 16 bits, etc.
        img = cv2.normalize(img, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    if img.ndim == 3 and img.shape[2] == 4:  # aplana transparencia sobre blanco
        a = img[:, :, 3:4].astype(np.float32) / 255
        img = (img[:, :, :3] * a + 255 * (1 - a)).astype(np.uint8)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    ow, oh = img.shape[1], img.shape[0]
    ratio = 1.0
    if max(ow, oh) > o.max_dim:
        ratio = max(ow, oh) / o.max_dim
        img = cv2.resize(
            img, (round(ow / ratio), round(oh / ratio)), interpolation=cv2.INTER_AREA
        )
    h, w = img.shape[:2]
    if o.blur > 1:
        k = o.blur | 1
        img = cv2.GaussianBlur(img, (k, k), 0)

    layers: list[Layer] = []
    if o.colors == 1:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        mode = cv2.THRESH_BINARY if o.invert else cv2.THRESH_BINARY_INV
        if o.threshold is None:
            _, m = cv2.threshold(gray, 0, 255, mode | cv2.THRESH_OTSU)
        else:
            _, m = cv2.threshold(gray, o.threshold, 255, mode)
        layers.append(Layer("TRAZO", (0, 0, 0), _trace_mask(m > 0, o)))
    else:
        labels, centers = _quantize(img, o.colors)
        counts = np.bincount(labels.ravel(), minlength=len(centers))
        bg = -1
        if o.skip_background:  # el color que domina el borde de la imagen
            border = np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])
            bg = int(np.bincount(border, minlength=len(centers)).argmax())
        n = 0
        for i in np.argsort(-counts):
            if i == bg or counts[i] == 0:
                continue
            n += 1
            rgb = tuple(int(v) for v in centers[i][::-1].round())
            layers.append(
                Layer(f"COLOR_{n}_{_hex(rgb)}", rgb, _trace_mask(labels == i, o))
            )
    layers = [l for l in layers if l.paths]
    return Vector(ow, oh, layers, ratio, w, h)


# ----------------------------------------------------------------- salida ---

def _fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def to_svg(vec: Vector) -> str:
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{vec.width}" '
        f'height="{vec.height}" viewBox="0 0 {vec.traced_w} {vec.traced_h}">'
    ]
    for layer in vec.layers:
        parts = []
        for p in layer.paths:
            d = [f"M{_fmt(p.start[0])},{_fmt(p.start[1])}"]
            for c1, c2, e in p.segments:
                if c1 is None:
                    d.append(f"L{_fmt(e[0])},{_fmt(e[1])}")
                else:
                    d.append(
                        "C" + " ".join(f"{_fmt(a)},{_fmt(b)}" for a, b in (c1, c2, e))
                    )
            parts.append("".join(d) + "Z")
        out.append(
            f'<g id="{layer.name}" fill="#{_hex(layer.color)}" fill-rule="evenodd">'
            f'<path d="{" ".join(parts)}"/></g>'
        )
    out.append("</svg>")
    return "".join(out)


def _unit_scale(vec: Vector, scale: float, width_mm: float | None) -> float:
    """Unidades DXF por píxel *trazado*."""
    if width_mm:
        return width_mm / vec.traced_w
    return scale * vec.ratio


def _bezier_chain(path: Path, f) -> list[Bezier4P]:
    cur = Vec2(f(path.start))
    chain = []
    for c1, c2, e in path.segments:
        end = Vec2(f(e))
        if c1 is None:  # recta -> cúbica degenerada
            p1, p2 = cur.lerp(end, 1 / 3), cur.lerp(end, 2 / 3)
        else:
            p1, p2 = Vec2(f(c1)), Vec2(f(c2))
        if not cur.isclose(end) or c1 is not None:
            chain.append(Bezier4P((cur, p1, p2, end)))
        cur = end
    return chain


def to_dxf(
    vec: Vector,
    scale: float = 1.0,
    width_mm: float | None = None,
    curve_mode: str = "spline",
    tolerance: float = 0.1,
) -> bytes:
    """DXF R2010 en mm: una capa por color. Y invertido para que no salga espejado."""
    s = _unit_scale(vec, scale, width_mm)
    H = vec.traced_h

    def f(pt: Point) -> tuple[float, float]:
        return pt[0] * s, (H - pt[1]) * s

    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    for layer in vec.layers:
        doc.layers.add(layer.name, true_color=rgb2int(layer.color))
        attr = {"layer": layer.name}
        for p in layer.paths:
            straight = all(c1 is None for c1, _, _ in p.segments)
            if straight:
                pts = [f(p.start)] + [f(e) for _, _, e in p.segments[:-1]]
                msp.add_lwpolyline(pts, close=True, dxfattribs=attr)
                continue
            chain = _bezier_chain(p, f)
            if curve_mode == "polyline":
                pts: list = []
                for b in chain:
                    pts.extend(list(b.flattening(tolerance))[:-1])
                msp.add_lwpolyline([(v.x, v.y) for v in pts], close=True, dxfattribs=attr)
            else:
                bs = bezier_to_bspline(chain)
                msp.add_open_spline(
                    bs.control_points, degree=bs.degree, knots=bs.knots(), dxfattribs=attr
                )
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")


def to_zip(vec: Vector, o: Options, stem: str = "salida") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{stem}.svg", to_svg(vec))
        z.writestr(
            f"{stem}.dxf", to_dxf(vec, o.scale, o.width_mm, o.dxf_curves, o.tolerance)
        )
    return buf.getvalue()


def convert(data: bytes, fmt: str, o: Options, stem: str = "salida") -> tuple[bytes, str]:
    """Devuelve (contenido, tipo MIME)."""
    vec = vectorize(data, o)
    if fmt == "svg":
        return to_svg(vec).encode(), "image/svg+xml"
    if fmt == "dxf":
        return (
            to_dxf(vec, o.scale, o.width_mm, o.dxf_curves, o.tolerance),
            "application/dxf",
        )
    if fmt == "zip":
        return to_zip(vec, o, stem), "application/zip"
    raise ValueError(f"formato desconocido: {fmt}")
