"""Mide la calidad: imagen de referencia -> degradada como foto -> vectorizada -> IoU contra la referencia."""
import sys, time
import cv2
import numpy as np

sys.path.insert(0, ".")
from app.vectorize import Options, vectorize  # noqa: E402


def reference(w=700, h=900):
    """Gráficos blancos (máscara ideal) sobre un panel verde."""
    m = np.zeros((h, w), np.uint8)
    cv2.putText(m, "EMERGENCY", (30, 120), cv2.FONT_HERSHEY_DUPLEX, 2.2, 255, 9, cv2.LINE_AA)
    cv2.putText(m, "STOP Test", (60, 230), cv2.FONT_HERSHEY_TRIPLEX, 2.0, 255, 7, cv2.LINE_AA)
    cv2.circle(m, (200, 520), 120, 255, 8, cv2.LINE_AA)
    cv2.ellipse(m, (200, 520), (70, 40), 30, 0, 360, 255, 6, cv2.LINE_AA)
    cv2.rectangle(m, (400, 400), (640, 640), 255, 8, cv2.LINE_AA)
    cv2.line(m, (60, 800), (640, 700), 255, 6, cv2.LINE_AA)
    pts = np.array([[420, 780], [520, 690], [640, 830]], np.int32)
    cv2.fillPoly(m, [pts], 255, cv2.LINE_AA)
    return m


def photo(m, seed=0):
    rng = np.random.default_rng(seed)
    h, w = m.shape
    a = (m.astype(np.float32) / 255)[..., None]
    green, white = np.array([57, 101, 8], np.float32), np.array([230, 238, 232], np.float32)
    img = green * (1 - a) + white * a
    yy, xx = np.mgrid[0:h, 0:w]
    img *= (0.85 + 0.2 * xx / w + 0.1 * yy / h)[..., None]  # iluminación desigual
    img = cv2.GaussianBlur(img, (0, 0), 1.3)  # desenfoque de lente
    img += rng.normal(0, 7, img.shape)  # ruido de sensor
    img = np.clip(img, 0, 255).astype(np.uint8)
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 60])[1].tobytes()


def render(vec, shape):
    """Rasteriza los trazados (relleno par-impar) para compararlos."""
    out = np.zeros(shape, np.uint8)
    S = 4  # supermuestreo
    for layer in vec.layers:
        acc = np.zeros((shape[0] * S, shape[1] * S), np.uint8)
        for p in layer.paths:
            pts = [p.start]
            cur = p.start
            for c1, c2, e in p.segments:
                if c1 is None:
                    pts.append(e)
                else:
                    for t in np.linspace(0, 1, 12)[1:]:
                        u = 1 - t
                        pts.append(tuple(u**3 * np.array(cur) + 3*u*u*t*np.array(c1) + 3*u*t*t*np.array(c2) + t**3 * np.array(e)))
                cur = e
            poly = (np.array(pts) * S).astype(np.int32)
            tmp = np.zeros_like(acc)
            cv2.fillPoly(tmp, [poly], 1)
            acc ^= tmp  # par-impar
        out |= cv2.resize(acc * 255, shape[::-1], interpolation=cv2.INTER_AREA) > 127
    return out > 0


def iou(a, b):
    return (a & b).sum() / max((a | b).sum(), 1)


if __name__ == "__main__":
    ref = reference()
    data = photo(ref)
    cv2.imwrite("/tmp/bench_photo.jpg", cv2.imdecode(np.frombuffer(data, np.uint8), 1))
    configs = {a.split("=")[0]: a for a in []}
    variants = [("actual", dict(colors=2))] + [
        (n, dict(colors=2, **kw)) for n, kw in
        [(n.split(":")[0], eval(n.split(":")[1])) for n in sys.argv[1:]]
    ]
    for name, kw in variants:
        t = time.time()
        try:
            v = vectorize(data, Options(**kw))
        except TypeError as e:
            print(name, "no soportado:", e); continue
        dt = time.time() - t
        r = render(v, ref.shape)
        nodes = sum(len(p.segments) for l in v.layers for p in l.paths)
        print(f"{name:14s} IoU={iou(r, ref > 127):.4f}  nodos={nodes:5d}  {dt:.1f}s")
        if name == "actual":
            cv2.imwrite("/tmp/bench_actual.png", r.astype(np.uint8) * 255)
