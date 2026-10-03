import cv2
import ezdxf
import numpy as np
from fastapi.testclient import TestClient

from app.main import app
from app.vectorize import Options, to_dxf, to_svg, vectorize


def png(draw) -> bytes:
    img = np.full((100, 200, 3), 255, np.uint8)
    draw(img)
    return cv2.imencode(".png", img)[1].tobytes()


def rect_png() -> bytes:
    return png(lambda i: cv2.rectangle(i, (20, 20), (120, 80), (0, 0, 0), -1))


def test_rectangle_is_one_polygon():
    vec = vectorize(rect_png())
    assert (vec.width, vec.height) == (200, 100)
    assert len(vec.polygons) == 1
    assert len(vec.polygons[0]) == 4


def test_hole_gives_two_contours():
    def draw(i):
        cv2.rectangle(i, (20, 20), (120, 80), (0, 0, 0), -1)
        cv2.circle(i, (70, 50), 15, (255, 255, 255), -1)

    assert len(vectorize(png(draw)).polygons) == 2


def test_invert_and_min_area():
    vec = vectorize(rect_png(), Options(invert=True, min_area=1e6))
    assert vec.polygons == []


def test_svg_and_dxf_output(tmp_path):
    vec = vectorize(rect_png())
    assert "<path" in to_svg(vec)
    f = tmp_path / "o.dxf"
    f.write_bytes(to_dxf(vec, scale=0.5))
    doc = ezdxf.readfile(f)
    polys = list(doc.modelspace().query("LWPOLYLINE"))
    assert len(polys) == 1 and polys[0].closed
    xs = [p[0] for p in polys[0].get_points()]
    ys = [p[1] for p in polys[0].get_points()]
    assert max(xs) - min(xs) == 50  # 100 px * 0.5
    assert min(ys) >= 0  # Y flipped, upright in CAD


def test_api():
    c = TestClient(app)
    r = c.post("/api/convert", files={"file": ("a.png", rect_png())}, data={"format": "dxf"})
    assert r.status_code == 200 and b"LWPOLYLINE" in r.content
    r = c.post("/api/convert", files={"file": ("a.png", b"basura")})
    assert r.status_code == 400
    assert c.get("/").status_code == 200
