import json
import os
import subprocess
import tempfile
from collections import Counter

import cv2
import ezdxf
from ezdxf.colors import DXF_DEFAULT_COLORS, int2rgb
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import dwg
from app.main import app
from app.vectorize import Options, nearest_aci, to_dxf, vectorize
from tests.test_vectorize import ring_and_rect

needs_dwg = pytest.mark.skipif(not dwg.available(), reason="LibreDWG (dxf2dwg) no está instalado")


def dwgread_json(data: bytes) -> list[dict]:
    exe = dwg.converter().replace("dxf2dwg", "dwgread")
    env = dict(os.environ, LD_LIBRARY_PATH=f"{dwg.PREFIX / 'lib'}:{os.environ.get('LD_LIBRARY_PATH', '')}")
    with tempfile.TemporaryDirectory() as tmp:
        src, out = os.path.join(tmp, "a.dwg"), os.path.join(tmp, "a.json")
        open(src, "wb").write(data)
        subprocess.run([exe, "-O", "json", "-o", out, src], capture_output=True, env=env, check=False)
        return [o for o in json.load(open(out))["OBJECTS"] if isinstance(o, dict)]


def test_nearest_aci():
    assert nearest_aci((255, 0, 0)) == 1  # rojo
    assert nearest_aci((0, 0, 255)) == 5  # azul
    assert nearest_aci((255, 255, 255)) in (7, 255)  # blanco


def test_compat_dxf_is_r2000_minimal():
    vec = vectorize(ring_and_rect(), Options(colors=3))
    doc = ezdxf.read(__import__("io").StringIO(to_dxf(vec, scale=0.1, compat=True).decode()))
    assert doc.dxfversion == "AC1015"
    assert {e.dxf.layer for e in doc.modelspace()} == {l.name for l in vec.layers}
    for l in vec.layers:  # ACI en vez de RGB, y cercano al color real
        c = int2rgb(DXF_DEFAULT_COLORS[doc.layers.get(l.name).dxf.color])
        assert abs(c.r - l.color[0]) + abs(c.g - l.color[1]) + abs(c.b - l.color[2]) < 60


@needs_dwg
@pytest.mark.parametrize("mode,kind", [("polyline", "LWPOLYLINE"), ("spline", "SPLINE")])
def test_dwg_roundtrip(mode, kind):
    vec = vectorize(ring_and_rect(), Options(colors=3))
    data = dwg.dxf_to_dwg(to_dxf(vec, scale=0.1, curve_mode=mode, compat=True))
    assert data.startswith(b"AC1015")  # DWG R2000
    objs = dwgread_json(data)
    ents = [o for o in objs if o.get("entity") in ("LWPOLYLINE", "SPLINE")]
    expected = Counter(e.dxftype() for e in ezdxf.read(__import__("io").StringIO(to_dxf(vec, 0.1, curve_mode=mode, compat=True).decode())).modelspace())
    assert Counter(e["entity"] for e in ents) == expected  # mismas entidades que el DXF
    assert kind in {e["entity"] for e in ents}
    layers = {o["name"] for o in objs if o.get("object") == "LAYER"}
    assert {l.name for l in vec.layers} <= layers


@needs_dwg
def test_dwg_coordinates_are_exact():
    vec = vectorize(ring_and_rect(), Options(colors=3, curves=False))
    dxf = to_dxf(vec, scale=0.25, compat=True)
    src = [np.array([(p[0], p[1]) for p in e.get_points()]) for e in ezdxf.read(__import__("io").StringIO(dxf.decode())).modelspace()]
    ents = [o for o in dwgread_json(dwg.dxf_to_dwg(dxf)) if o.get("entity") == "LWPOLYLINE"]
    assert len(ents) == len(src)
    for a, e in zip(src, ents):
        b = np.array([(p[0], p[1]) for p in e["points"]])
        assert a.shape == b.shape and np.abs(a - b).max() < 1e-6


@needs_dwg
def test_api_and_capabilities_dwg():
    c = TestClient(app)
    assert "dwg" in c.get("/api/capabilities").json()["formats"]
    r = c.post("/api/convert", files={"file": ("logo.png", ring_and_rect())}, data={"format": "dwg", "colors": 3, "width_mm": 100})
    assert r.status_code == 200 and r.content.startswith(b"AC1015")
    assert 'filename="logo.dwg"' in r.headers["content-disposition"]


def test_dwg_unavailable_is_reported(monkeypatch):
    monkeypatch.setattr(dwg, "converter", lambda: None)
    c = TestClient(app)
    assert "dwg" not in c.get("/api/capabilities").json()["formats"]
    r = c.post("/api/convert", files={"file": ("logo.png", ring_and_rect())}, data={"format": "dwg"})
    assert r.status_code == 501 and "DWG" in r.json()["detail"]
    with pytest.raises(dwg.DwgUnavailable):
        dwg.dxf_to_dwg(b"0\nEOF\n")


def test_invalid_converter_output_is_rejected(monkeypatch, tmp_path):
    fake = tmp_path / "dxf2dwg"
    fake.write_text("#!/bin/sh\nwhile [ $# -gt 0 ]; do [ \"$1\" = -o ] && out=$2; shift; done\necho basura > \"$out\"\n")
    fake.chmod(0o755)
    monkeypatch.setattr(dwg, "converter", lambda: str(fake))
    with pytest.raises(dwg.DwgError, match="inválido"):
        dwg.dxf_to_dwg(b"0\nEOF\n")
