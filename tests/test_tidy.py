import cv2
import numpy as np

from app.vectorize import Options, vectorize
from tools.benchmark import iou, photo, reference, render


def noisy_rect_png(angle=0.0):
    """Rectángulo cuyos lados tienen una leve panza (como un borde fotografiado)."""
    img = np.full((400, 600, 3), 255, np.uint8)
    rng = np.random.default_rng(1)
    pts = np.array([[100, 100], [500, 100], [500, 300], [100, 300]], np.float32)
    dense = []
    for a, b in zip(pts, np.roll(pts, -1, axis=0)):
        d = (b - a) / np.linalg.norm(b - a)
        n = np.array([-d[1], d[0]])
        for t in np.linspace(0, 1, 80, endpoint=False):
            dense.append(a + (b - a) * t + n * 0.6 * np.sin(np.pi * t) + rng.normal(0, 0.1, 2))
    cv2.fillPoly(img, [np.array(np.round(np.array(dense) * 8), np.int32)], (0, 0, 0), cv2.LINE_AA, shift=3)
    if angle:
        M = cv2.getRotationMatrix2D((300, 200), angle, 1)
        img = cv2.warpAffine(img, M, (600, 400), borderValue=(255, 255, 255))
    return cv2.imencode(".png", img)[1].tobytes()


def line_angles(vec):
    out = []
    for l in vec.layers:
        for p in l.paths:
            cur = p.start
            for c1, _, e in p.segments:
                if c1 is None and np.hypot(e[0] - cur[0], e[1] - cur[1]) > 30:
                    out.append(np.degrees(np.arctan2(e[1] - cur[1], e[0] - cur[0])) % 180)
                cur = e
    return np.array(out)


def test_wobbly_rectangle_becomes_four_exact_lines():
    vec = vectorize(noisy_rect_png())
    paths = vec.layers[0].paths
    assert len(paths) == 1
    assert len(paths[0].segments) <= 8  # 4 lados (+ nodos de esquina)
    ang = line_angles(vec)
    assert len(ang) >= 4
    assert np.all((ang < 1e-6) | (np.abs(ang - 90) < 1e-6) | (np.abs(ang - 180) < 1e-6))  # exactos H/V


def L(*pts):
    return [(None, None, p) for p in pts]


def test_unit_merges_collinear_and_snaps_axes():
    from app.vectorize import Path, _tidy_path

    # borde superior con ruido (3 puntos casi colineales), lados casi verticales y base casi horizontal
    p = Path((0.0, 0.2), L((50.0, -0.2), (100.0, 0.1), (100.8, 80.0), (1.0, 79.0), (0.0, 0.2)))
    out = _tidy_path(p, tol=0.7, axis_deg=3.0)
    assert len(out.segments) == 4  # los 3 tramos del borde superior se funden en uno
    pts = [out.start] + [e for _, _, e in out.segments]
    assert pts[0][1] == pts[1][1]  # arriba: horizontal exacta
    assert pts[1][0] == pts[2][0]  # derecha: vertical exacta
    assert pts[2][1] == pts[3][1]  # abajo: horizontal exacta


def test_unit_keeps_real_curves_and_diagonals():
    from app.vectorize import Path, _tidy_path

    arc = ((0.0, 20.0), (40.0, 20.0), (40.0, 0.0))  # arco real: no es recta
    p = Path((0.0, 0.0), [arc, (None, None, (60.0, 40.0)), (None, None, (0.0, 0.0))])
    out = _tidy_path(p, tol=0.7, axis_deg=3.0)
    assert out.segments[0][0] is not None  # la curva sigue siendo curva
    assert out.segments[1][0] is None and out.segments[1][2] == (60.0, 40.0)  # la diagonal no se toca


def test_unit_moves_curve_handles_with_snapped_nodes():
    from app.vectorize import Path, _tidy_path

    # lado casi horizontal seguido de una curva: al alinear el nodo, la curva debe moverse con él
    p = Path((0.0, 0.0), [(None, None, (100.0, 1.0)), ((120.0, 1.0), (140.0, 20.0), (140.0, 40.0)),
                          (None, None, (0.0, 40.0)), (None, None, (0.0, 0.0))])
    out = _tidy_path(p, tol=0.7, axis_deg=3.0)
    (_, _, e0), (c1, c2, e1) = out.segments[0], out.segments[1]
    assert out.start[1] == e0[1]
    # el nodo (100, 1) sube/baja hasta y=0.5; la asa de salida de la curva se desplaza igual
    assert e0[1] == out.start[1]
    assert c1[1] == 1.0 + (e0[1] - 1.0)


def test_tilted_shape_not_forced_to_axes():
    ang = line_angles(vectorize(noisy_rect_png(angle=12)))
    assert len(ang) >= 4
    assert not np.any(np.isclose(ang % 90, 0, atol=0.5))  # 12° está fuera de la tolerancia de 3°


def test_tidy_does_not_hurt_fidelity():
    ref = reference()
    data = photo(ref, 0)
    on = iou(render(vectorize(data, Options(colors=2)), ref.shape), ref > 127)
    off = iou(render(vectorize(data, Options(colors=2, straighten=False, axis_snap=0)), ref.shape), ref > 127)
    assert on > off - 0.01
