import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.perspective import detect_panel, order_corners, rectify
from app.vectorize import Options, decode, vectorize
from tools.benchmark import iou, photo, reference, render

REF = reference()
GT = REF > 127
DST = np.array([[170, 130], [830, 70], [790, 1010], [210, 950]], np.float32)  # panel en ángulo


def tilted(seed=0):
    """Panel (referencia degradada) pegado sobre una placa de acero y visto en perspectiva."""
    panel = decode(photo(REF, seed))
    h, w = panel.shape[:2]
    M = cv2.getPerspectiveTransform(np.array([[0, 0], [w, 0], [w, h], [0, h]], np.float32), DST)
    rng = np.random.default_rng(seed)
    steel = np.clip(165 + rng.normal(0, 12, (1100, 1000, 3)), 0, 255).astype(np.uint8)
    steel = cv2.GaussianBlur(steel, (0, 0), 2)
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), M, (1000, 1100))
    warped = cv2.warpPerspective(panel, M, (1000, 1100), flags=cv2.INTER_CUBIC)
    out = np.where(mask[..., None] > 127, warped, steel)
    return cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()


def test_order_corners():
    shuffled = [(100, 100), (0, 100), (100, 0), (0, 0)]
    assert order_corners(shuffled).tolist() == [[0, 0], [100, 0], [100, 100], [0, 100]]


def test_detect_panel_finds_tilted_panel():
    img = decode(tilted())
    found = np.array(detect_panel(img))
    assert np.abs(found - DST).max() < 12  # px, en una foto de 1000x1100


def test_rectify_makes_rectangle_with_right_aspect():
    img = decode(tilted())
    out = rectify(img, DST)
    assert out.shape[1] / out.shape[0] == pytest.approx(REF.shape[1] / REF.shape[0], rel=0.15)
    assert rectify(img, DST, aspect=0.5).shape[1] / rectify(img, DST, aspect=0.5).shape[0] == pytest.approx(0.5, abs=0.01)
    with pytest.raises(ValueError):
        rectify(img, [(0, 0)] * 4)


def straightened_iou(vec):
    r = render(vec, (vec.height, vec.width)).astype(np.uint8)
    r = cv2.resize(r, REF.shape[::-1], interpolation=cv2.INTER_AREA) > 0.5
    return iou(r, GT)


def test_vectorize_recovers_straight_graphics():
    data = tilted()
    aspect = REF.shape[1] / REF.shape[0]
    auto = vectorize(data, Options(colors=2, auto_perspective=True, aspect=aspect, inset=0.002))
    manual = vectorize(data, Options(colors=2, corners=[tuple(p) for p in DST], aspect=aspect, inset=0.002))
    assert straightened_iou(auto) > 0.85
    assert straightened_iou(manual) > 0.85
    # sin corregir, el mismo contenido sale deformado
    crude = vectorize(data, Options(colors=2, crop=(170, 70, 830, 1010)))
    assert straightened_iou(crude) < straightened_iou(manual) - 0.2


def test_auto_failure_message():
    blank = cv2.imencode(".png", np.full((200, 200, 3), 128, np.uint8))[1].tobytes()
    with pytest.raises(ValueError, match="esquinas"):
        vectorize(blank, Options(auto_perspective=True))


def test_api_detect_and_rectify():
    c = TestClient(app)
    files = {"file": ("p.jpg", tilted())}
    j = c.post("/api/detect-panel", files=files).json()
    assert j["corners"] and len(j["corners"]) == 4
    cs = ",".join(str(round(v)) for p in j["corners"] for v in p)
    r = c.post("/api/rectify", files=files, data={"corners": cs, "inset": 0.01})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    r = c.post("/api/convert", files=files, data={"format": "dxf", "colors": 2, "corners": cs})
    assert r.status_code == 200 and b"SPLINE" in r.content
    assert c.post("/api/convert", files=files, data={"corners": "1,2,3"}).status_code == 422


def test_snap_fixes_sloppy_clicks():
    from app.perspective import snap_corners

    img = decode(tilted())
    rng = np.random.default_rng(3)
    sloppy = (DST + rng.uniform(-7, 7, DST.shape)).astype(np.float32)
    snapped = np.array(snap_corners(img, sloppy))
    assert np.abs(snapped - DST).max() < 2
    assert np.abs(sloppy - DST).max() > 4  # los clics sí eran imprecisos
    aspect = REF.shape[1] / REF.shape[0]
    corners = [tuple(p) for p in sloppy]
    on = straightened_iou(vectorize(tilted(), Options(colors=2, corners=corners, aspect=aspect, inset=0.002)))
    off = straightened_iou(vectorize(tilted(), Options(colors=2, corners=corners, aspect=aspect, inset=0.002, snap=False)))
    assert on > off + 0.1
