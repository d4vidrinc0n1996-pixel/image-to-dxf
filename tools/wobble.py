"""Mide la calidad geométrica de un vector: ondulación de tramos rectos y desalineación con los ejes."""
import sys
import numpy as np

sys.path.insert(0, ".")
from app.vectorize import Options, decode, vectorize  # noqa: E402


def flatten(path, n=16):
    pts, cur = [np.array(path.start)], np.array(path.start)
    for c1, c2, e in path.segments:
        e = np.array(e)
        if c1 is None:
            pts.append(e)
        else:
            c1, c2 = np.array(c1), np.array(c2)
            for t in np.linspace(0, 1, n)[1:]:
                u = 1 - t
                pts.append(u**3 * cur + 3*u*u*t*c1 + 3*u*t*t*c2 + t**3 * e)
        cur = e
    return np.array(pts)


def report(vec, label=""):
    """Tramos casi rectos y largos (>25 px): ondulación (RMS respecto a su recta) y desalineo con los ejes."""
    nodes = 0
    rms, off_axis = [], []
    for l in vec.layers:
        for p in l.paths:
            nodes += len(p.segments)
            pts = flatten(p)
            i = 0
            while i < len(pts) - 2:
                best = None
                for j in range(i + 2, len(pts)):
                    seg = pts[i : j + 1]
                    d = pts[j] - pts[i]
                    L = np.linalg.norm(d)
                    if L < 1e-6:
                        break
                    n = np.array([-d[1], d[0]]) / L
                    dev = (seg - pts[i]) @ n
                    if np.abs(dev).max() > 1.5:
                        break
                    best = (j, L, d, np.sqrt((dev**2).mean()))
                if best and best[1] > 25:
                    j, L, d, r = best
                    rms.append(r)
                    ang = np.degrees(np.arctan2(abs(d[1]), abs(d[0])))
                    off_axis.append(min(ang, abs(90 - ang)))
                    i = j
                else:
                    i += 1
    rms, off_axis = np.array(rms), np.array(off_axis)
    near = off_axis < 6  # lados que "quieren" ser horizontales o verticales
    print(f"{label:14s} nodos={nodes:5d} lados rectos={len(rms):3d}  ondulación RMS={rms.mean():.3f}px  "
          f"desalineo H/V={off_axis[near].mean() if near.any() else 0:.2f}° (máx {off_axis[near].max() if near.any() else 0:.1f}°)")


if __name__ == "__main__":
    d = open("/tmp/sign.jpg", "rb").read()
    report(vectorize(d, Options(auto_perspective=True, colors=2)), "actual")
