import io
import zipfile

import cv2
import ezdxf
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.vectorize import ImageError, Options, to_dxf, to_svg, vectorize


def png(draw, bg=255) -> bytes:
    img = np.full((300, 400, 3), bg, np.uint8)
    draw(img)
    return cv2.imencode(".png", img)[1].tobytes()


def rect_png() -> bytes:
    return png(lambda i: cv2.rectangle(i, (20, 20), (220, 180), (0, 0, 0), -1))


def ring_and_rect() -> bytes:
    def draw(i):
        cv2.circle(i, (120, 150), 80, (0, 0, 255), -1)  # rojo (BGR)
        cv2.circle(i, (120, 150), 30, (255, 255, 255), -1)
        cv2.rectangle(i, (250, 60), (360, 240), (200, 0, 0), -1)  # azul

    return png(draw)


def read_dxf(b: bytes):
    return ezdxf.read(io.StringIO(b.decode()))


def test_bilevel_rectangle():
    vec = vectorize(rect_png())
    assert (vec.width, vec.height) == (400, 300)
    assert [l.name for l in vec.layers] == ["TRAZO"]
    assert len(vec.layers[0].paths) == 1


def test_hole_gives_two_paths():
    def draw(i):
        cv2.rectangle(i, (20, 20), (220, 180), (0, 0, 0), -1)
        cv2.circle(i, (120, 100), 30, (255, 255, 255), -1)

    assert len(vectorize(png(draw)).layers[0].paths) == 2


def test_curves_vs_polygons():
    data = ring_and_rect()
    curved = vectorize(data, Options(colors=3))
    flat = vectorize(data, Options(colors=3, curves=False))
    has_curve = lambda v: any(c1 is not None for l in v.layers for p in l.paths for c1, _, _ in p.segments)
    assert has_curve(curved) and not has_curve(flat)
    # una curva necesita muchos menos nodos que el polígono equivalente
    n = lambda v: sum(len(p.segments) for l in v.layers for p in l.paths)
    assert n(curved) < n(flat)


def test_color_layers_ignore_background():
    vec = vectorize(ring_and_rect(), Options(colors=3))
    assert sorted(l.name.split("_")[-1] for l in vec.layers) == ["0000C8", "FF0000"]
    keep = vectorize(ring_and_rect(), Options(colors=3, skip_background=False))
    assert len(keep.layers) == 3


def test_svg_has_curves_and_color_groups():
    svg = to_svg(vectorize(ring_and_rect(), Options(colors=3)))
    assert 'fill="#FF0000"' in svg and 'fill="#0000C8"' in svg and "C" in svg


@pytest.mark.parametrize("mode,kind", [("spline", "SPLINE"), ("polyline", "LWPOLYLINE")])
def test_dxf_curve_modes_and_layers(mode, kind):
    vec = vectorize(ring_and_rect(), Options(colors=3))
    doc = read_dxf(to_dxf(vec, scale=0.1, curve_mode=mode))
    ents = list(doc.modelspace())
    assert kind in {e.dxftype() for e in ents}
    assert {e.dxf.layer for e in ents} == {l.name for l in vec.layers}
    assert doc.layers.get("COLOR_2_FF0000").rgb == (255, 0, 0)


def test_dxf_width_mm_and_orientation():
    vec = vectorize(rect_png(), Options(curves=False))
    doc = read_dxf(to_dxf(vec, width_mm=100))  # imagen de 400 px -> 100 mm
    pts = list(list(doc.modelspace())[0].get_points())
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    assert max(xs) - min(xs) == pytest.approx(201 * 0.25, abs=0.01)  # 201 px (20..220 inclusive)
    assert min(ys) > 0  # Y hacia arriba: el rectángulo estaba arriba en la imagen
    assert min(ys) == pytest.approx((300 - 180) * 0.25, abs=0.5)


def test_downscale_keeps_physical_size():
    big = np.full((600, 800, 3), 255, np.uint8)
    cv2.rectangle(big, (100, 100), (500, 400), (0, 0, 0), -1)
    data = cv2.imencode(".png", big)[1].tobytes()
    vec = vectorize(data, Options(curves=False, max_dim=400))
    assert vec.traced_w == 400 and vec.ratio == 2
    doc = read_dxf(to_dxf(vec, scale=1.0))
    xs = [p[0] for p in list(doc.modelspace())[0].get_points()]
    assert max(xs) - min(xs) == pytest.approx(400, abs=3)  # 400 px originales


def test_transparent_png_and_errors():
    img = np.zeros((100, 100, 4), np.uint8)
    cv2.circle(img, (50, 50), 30, (0, 0, 0, 255), -1)
    vec = vectorize(cv2.imencode(".png", img)[1].tobytes())
    assert len(vec.layers[0].paths) == 1
    with pytest.raises(ImageError):
        vectorize(b"basura")
    with pytest.raises(ValueError):
        vectorize(rect_png(), Options(colors=99))


def test_api():
    c = TestClient(app)
    files = {"file": ("logo.png", ring_and_rect())}
    r = c.post("/api/convert", files=files, data={"format": "dxf", "colors": 3})
    assert r.status_code == 200 and b"SPLINE" in r.content
    r = c.post("/api/convert", files=files, data={"format": "zip", "colors": 3})
    assert sorted(zipfile.ZipFile(io.BytesIO(r.content)).namelist()) == ["logo.dxf", "logo.svg"]
    r = c.post("/api/convert", files={"file": ("a.png", b"basura")})
    assert r.status_code == 400
    r = c.post("/api/convert", files=files, data={"colors": 99})
    assert r.status_code == 422
    assert c.get("/").status_code == 200


def lines_png() -> bytes:
    def draw(i):
        cv2.rectangle(i, (30, 40), (230, 240), (0, 0, 0), 5)
        cv2.line(i, (260, 40), (380, 260), (0, 0, 0), 4)

    return png(draw)


def test_centerline_gives_open_lines_not_outlines():
    vec = vectorize(lines_png(), Options(centerline=True))
    paths = vec.layers[0].paths
    assert vec.layers[0].stroke
    assert any(not p.closed for p in paths)
    # el contorno de un trazo de 5 px tendría ~2x el perímetro; la línea central, uno
    length = sum(
        np.hypot(e[0] - s[0], e[1] - s[1])
        for p in paths
        for s, e in zip([p.start] + [x[2] for x in p.segments], [x[2] for x in p.segments])
    )
    assert 950 < length < 1100  # cuadrado 4*200 + diagonal ~250


def test_centerline_outputs():
    vec = vectorize(lines_png(), Options(centerline=True))
    svg = to_svg(vec)
    assert 'fill="none"' in svg and 'stroke="#000000"' in svg
    doc = read_dxf(to_dxf(vec, width_mm=100, curve_mode="polyline"))
    ents = list(doc.modelspace())
    assert ents and any(not e.closed for e in ents if e.dxftype() == "LWPOLYLINE")
    assert read_dxf(to_dxf(vec, width_mm=100))  # splines abiertos también válidos


def test_centerline_api():
    r = TestClient(app).post(
        "/api/convert",
        files={"file": ("p.png", lines_png())},
        data={"format": "svg", "centerline": "true", "min_length": 5},
    )
    assert r.status_code == 200 and b"stroke=" in r.content


def test_crop_limits_area_and_validates():
    def draw(i):
        cv2.rectangle(i, (20, 20), (120, 120), (0, 0, 0), -1)  # dentro del recorte
        cv2.rectangle(i, (300, 200), (380, 280), (0, 0, 0), -1)  # fuera

    data = png(draw)
    assert len(vectorize(data).layers[0].paths) == 2
    vec = vectorize(data, Options(crop=(0, 0, 200, 150)))
    assert (vec.width, vec.height) == (200, 150) and len(vec.layers[0].paths) == 1
    with pytest.raises(ValueError):
        vectorize(data, Options(crop=(500, 500, 600, 600)))
    c = TestClient(app)
    ok = c.post("/api/convert", files={"file": ("a.png", data)}, data={"format": "svg", "crop": "0,0,200,150"})
    bad = c.post("/api/convert", files={"file": ("a.png", data)}, data={"crop": "x"})
    assert ok.status_code == 200 and bad.status_code == 422
