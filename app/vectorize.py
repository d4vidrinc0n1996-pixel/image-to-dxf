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
    centerline: bool = False  # trazos finos -> una línea central (abierta) en vez de contorno
    min_length: float = 10.0  # centerline: descarta líneas más cortas (px)
    crop: tuple[int, int, int, int] | None = None  # (x0, y0, x1, y1) en píxeles originales
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
    closed: bool = True


@dataclass
class Layer:
    name: str
    color: tuple[int, int, int]
    paths: list[Path] = field(default_factory=list)
    stroke: bool = False  # líneas centrales: se dibujan con trazo, no con relleno


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



def _thin(mask: np.ndarray) -> np.ndarray:
    """Esqueleto de 1 px (Zhang-Suen vectorizado con numpy)."""
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return mask
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1  # recorta al contenido
    full = np.zeros(mask.shape, bool)
    full[y0:y1, x0:x1] = _thin_core(mask[y0:y1, x0:x1])
    return full


def _thin_core(mask: np.ndarray) -> np.ndarray:
    img = np.pad(mask.astype(np.uint8), 1)
    while True:
        changed = False
        for step in (0, 1):
            P = img
            n = [P[:-2, 1:-1], P[:-2, 2:], P[1:-1, 2:], P[2:, 2:],
                 P[2:, 1:-1], P[2:, :-2], P[1:-1, :-2], P[:-2, :-2]]  # N,NE,E,SE,S,SW,W,NW
            B = sum(x.astype(np.int16) for x in n)
            A = sum(((n[i] == 0) & (n[(i + 1) % 8] == 1)).astype(np.int16) for i in range(8))
            N, E, S, W = n[0], n[2], n[4], n[6]
            if step == 0:
                c = (N * E * S == 0) & (E * S * W == 0)
            else:
                c = (N * E * W == 0) & (N * S * W == 0)
            rm = (P[1:-1, 1:-1] == 1) & (B >= 2) & (B <= 6) & (A == 1) & c
            if rm.any():
                img[1:-1, 1:-1][rm] = 0
                changed = True
        if not changed:
            return img[1:-1, 1:-1].astype(bool)


_NB = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]


def _skeleton_lines(skel: np.ndarray) -> list[list[Point]]:
    """Recorre el esqueleto y devuelve polilíneas (x, y). Los cruces se funden en un nodo."""
    ys, xs = np.nonzero(skel)
    pix = set(zip(xs.tolist(), ys.tolist()))

    def nbrs(p):
        x, y = p
        return [(x + dx, y + dy) for dy, dx in _NB if (x + dx, y + dy) in pix]

    def crossings(p):  # grupos contiguos de vecinos alrededor del píxel
        x, y = p
        ring = [(x + dx, y + dy) in pix for dy, dx in _NB]
        return sum(1 for i in range(8) if not ring[i] and ring[(i + 1) % 8])

    kind = {}  # "end" | "junction"
    for p in pix:
        n = len(nbrs(p))
        if n <= 1:
            kind[p] = "end"
        elif crossings(p) >= 3:
            kind[p] = "junction"
    # funde píxeles de cruce vecinos en un único nodo (centroide)
    centre: dict[tuple[int, int], Point] = {}
    junc = [p for p, k in kind.items() if k == "junction"]
    if junc:
        m = np.zeros(skel.shape, np.uint8)
        for x, y in junc:
            m[y, x] = 1
        _, lab = cv2.connectedComponents(m, connectivity=8)
        groups: dict[int, list] = {}
        for x, y in junc:
            groups.setdefault(int(lab[y, x]), []).append((x, y))
        for g in groups.values():
            cx, cy = np.mean(g, axis=0)
            for p in g:
                centre[p] = (float(cx), float(cy))
    group_of = {p: centre[p] for p in centre}

    seen: set[frozenset] = set()
    lines: list[list[Point]] = []

    def point(p):
        return group_of.get(p, (float(p[0]), float(p[1])))

    def walk(start, nxt):
        pts = [point(start)]
        prev, cur = start, nxt
        seen.add(frozenset((start, nxt)))
        while True:
            if cur in kind or cur == start:
                pts.append(point(cur))
                return pts
            pts.append((float(cur[0]), float(cur[1])))
            opts = [q for q in nbrs(cur) if q != prev and frozenset((cur, q)) not in seen]
            far = [q for q in opts if max(abs(q[0] - prev[0]), abs(q[1] - prev[1])) > 1]
            opts = far or opts
            if not opts:
                return pts
            opts.sort(key=lambda q: abs(q[0] - cur[0]) + abs(q[1] - cur[1]))
            prev, cur = cur, opts[0]
            seen.add(frozenset((prev, cur)))

    for n in sorted(kind):
        for q in nbrs(n):
            if frozenset((n, q)) in seen:
                continue
            if n in group_of and q in group_of and group_of[n] == group_of[q]:
                continue
            lines.append(walk(n, q))
    for p in sorted(pix):  # lazos cerrados sin nodos
        for q in nbrs(p):
            if frozenset((p, q)) not in seen:
                lines.append(walk(p, q))
    return lines


def _smooth_segments(pts: list[Point]) -> list[Segment]:
    """Bézier a través de los puntos; las esquinas marcadas se mantienen vivas."""
    n = len(pts)
    P = [np.array(p) for p in pts]
    corner = [False] * n
    for i in range(1, n - 1):
        a, b = P[i] - P[i - 1], P[i + 1] - P[i]
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        if na and nb and (a @ b) / (na * nb) < 0.5:  # giro > 60°
            corner[i] = True
    tan = []
    for i in range(n):
        if i in (0, n - 1) or corner[i]:
            tan.append(None)
        else:
            tan.append((P[i + 1] - P[i - 1]) / 6)
    segs: list[Segment] = []
    for i in range(n - 1):
        d = P[i + 1] - P[i]
        c1 = P[i] + (tan[i] if tan[i] is not None else d / 3)
        c2 = P[i + 1] - (tan[i + 1] if tan[i + 1] is not None else d / 3)
        segs.append(((float(c1[0]), float(c1[1])), (float(c2[0]), float(c2[1])),
                     (float(P[i + 1][0]), float(P[i + 1][1]))))
    return segs


def _trace_centerline(mask: np.ndarray, o: Options) -> list[Path]:
    out = []
    for line in _skeleton_lines(_thin(mask)):
        if len(line) < max(o.min_length, 2):
            continue
        arr = np.array(line, np.float32).reshape(-1, 1, 2)
        closed = line[0] == line[-1] and len(line) > 3
        if o.epsilon > 0:
            arr = cv2.approxPolyDP(arr, max(o.epsilon, 0.5), closed)
        pts = [(float(x), float(y)) for x, y in arr.reshape(-1, 2)]
        if closed and pts[0] != pts[-1]:
            pts.append(pts[0])
        if len(pts) < 2:
            continue
        if o.curves and len(pts) > 2:
            segs = _smooth_segments(pts)
        else:
            segs = [(None, None, q) for q in pts[1:]]
        out.append(Path(pts[0], segs, closed))
    return out

def _trace_mask(mask: np.ndarray, o: Options) -> list[Path]:
    """mask: bool, True = zona a vectorizar."""
    if o.centerline:
        return _trace_centerline(mask, o)
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


def _clean(mask: np.ndarray) -> np.ndarray:
    """Quita motas y suaviza bordes de una máscara por color (mediana 5x5)."""
    return cv2.medianBlur(mask.astype(np.uint8) * 255, 5) > 127


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

    if o.crop:
        x0, y0, x1, y1 = o.crop
        H, W = img.shape[:2]
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, W), min(y1, H)
        if x1 - x0 < 2 or y1 - y0 < 2:
            raise ValueError("El recorte está vacío o fuera de la imagen")
        img = img[y0:y1, x0:x1]
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
        layers.append(Layer("TRAZO", (0, 0, 0), _trace_mask(m > 0, o), o.centerline))
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
                Layer(f"COLOR_{n}_{_hex(rgb)}", rgb, _trace_mask(_clean(labels == i), o), o.centerline)
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
            parts.append("".join(d) + ("Z" if p.closed else ""))
        style = (
            f'fill="none" stroke="#{_hex(layer.color)}" stroke-width="1" '
            'stroke-linecap="round" stroke-linejoin="round"'
            if layer.stroke
            else f'fill="#{_hex(layer.color)}" fill-rule="evenodd"'
        )
        out.append(
            f'<g id="{layer.name}" {style}>'
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
                ends = p.segments[:-1] if p.closed else p.segments
                pts = [f(p.start)] + [f(e) for _, _, e in ends]
                msp.add_lwpolyline(pts, close=p.closed, dxfattribs=attr)
                continue
            chain = _bezier_chain(p, f)
            if curve_mode == "polyline":
                pts: list = []
                for b in chain:
                    pts.extend(list(b.flattening(tolerance))[:-1])
                msp.add_lwpolyline([(v.x, v.y) for v in pts], close=p.closed, dxfattribs=attr)
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
