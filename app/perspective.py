"""Corrección de perspectiva: enderezar un panel fotografiado en ángulo."""
from __future__ import annotations

import cv2
import numpy as np

Corners = list[tuple[float, float]]


def order_corners(pts) -> np.ndarray:
    """Ordena 4 puntos como arriba-izq, arriba-der, abajo-der, abajo-izq."""
    p = np.asarray(pts, np.float32).reshape(4, 2)
    s, d = p.sum(1), np.diff(p, axis=1).ravel()  # d = y - x
    return np.array([p[s.argmin()], p[d.argmin()], p[s.argmax()], p[d.argmax()]], np.float32)


def rectify(
    img: np.ndarray,
    corners,
    aspect: float | None = None,
    inset: float = 0.0,
) -> np.ndarray:
    """Devuelve el panel enderezado.

    corners: 4 esquinas (x, y) en píxeles, en cualquier orden.
    aspect: ancho/alto real del panel; si no se da, se estima de los bordes.
    inset: fracción (0-0.2) que se recorta de cada lado para descartar el borde del panel.
    """
    src = order_corners(corners)
    tl, tr, br, bl = src
    w = max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))
    h = max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))
    if w < 10 or h < 10:
        raise ValueError("Las esquinas son demasiado juntas o están repetidas")
    if aspect:
        if aspect <= 0:
            raise ValueError("aspect debe ser positivo")
        w = h * aspect if aspect * h >= w else w
        h = w / aspect
    W, H = int(round(w)), int(round(h))
    dst = np.array([[0, 0], [W, 0], [W, H], [0, H]], np.float32)
    M = cv2.getPerspectiveTransform(src, dst)
    out = cv2.warpPerspective(img, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    if inset > 0:
        dx, dy = int(W * inset), int(H * inset)
        out = out[dy : H - dy, dx : W - dx]
    return out


def _quad(hull: np.ndarray) -> np.ndarray | None:
    peri = cv2.arcLength(hull, True)
    for eps in (0.01, 0.02, 0.03, 0.05):
        approx = cv2.approxPolyDP(hull, eps * peri, True)
        if len(approx) == 4:
            return approx.reshape(4, 2)
    return None


def _refine_quad(points: np.ndarray, quad: np.ndarray) -> np.ndarray:
    """Ajusta una recta a cada lado usando los puntos del contorno y calcula sus cruces.

    Las esquinas de un contorno suavizado salen redondeadas; las rectas no.
    """
    q = order_corners(quad)
    pts = points.reshape(-1, 2).astype(np.float32)
    lines = []
    for i in range(4):
        a, b = q[i], q[(i + 1) % 4]
        d = b - a
        L = np.linalg.norm(d)
        if L < 1:
            return q
        d /= L
        rel = pts - a
        t = rel @ d  # posición a lo largo del lado
        dist = np.abs(rel[:, 0] * d[1] - rel[:, 1] * d[0])
        sel = pts[(dist < max(4.0, 0.02 * L)) & (t > 0.1 * L) & (t < 0.9 * L)]
        if len(sel) < 10:
            return q
        vx, vy, x0, y0 = cv2.fitLine(sel, cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        lines.append((np.array([x0, y0]), np.array([vx, vy])))
    out = []
    for i in range(4):  # esquina i = cruce del lado i-1 con el lado i
        (p1, d1), (p2, d2) = lines[i - 1], lines[i]
        A = np.array([d1, -d2]).T
        if abs(np.linalg.det(A)) < 1e-6:
            return q
        t = np.linalg.solve(A, p2 - p1)
        out.append(p1 + t[0] * d1)
    out = np.array(out, np.float32)
    # si el ajuste se desvía mucho del cuadrilátero original, no se confía en él
    return out if np.abs(out - q).max() < 0.05 * max(np.ptp(q[:, 0]), np.ptp(q[:, 1])) else q


def _detect_by_color(small: np.ndarray) -> np.ndarray | None:
    """Panel = región de un color que ocupa buena parte de la foto pero no domina su borde."""
    h, w = small.shape[:2]
    lab = cv2.cvtColor(cv2.GaussianBlur(small, (7, 7), 0), cv2.COLOR_BGR2LAB)
    flat = lab.reshape(-1, 3).astype(np.float32)
    flat[:, 0] *= 0.3  # agrupa por color, no por brillo (la luz desigual partiría el panel)
    cv2.setRNGSeed(0)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, _ = cv2.kmeans(flat, 4, None, crit, 2, cv2.KMEANS_PP_CENTERS)
    labels = labels.reshape(h, w)
    best, best_area = None, 0.0
    for c in range(4):
        m = (labels == c).astype(np.uint8)
        border = np.concatenate([m[0], m[-1], m[:, 0], m[:, -1]]).mean()
        if border > 0.35:  # fondo: domina el borde de la imagen
            continue
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnts:
            continue
        cnt = max(cnts, key=cv2.contourArea)
        hull = cv2.convexHull(cnt)
        area, harea = cv2.contourArea(cnt), cv2.contourArea(hull)
        if harea < 0.15 * h * w or area < 0.7 * harea:  # grande y sin grandes huecos/entrantes
            continue
        quad = _quad(hull)
        if quad is not None and harea > best_area:
            best, best_area = _refine_quad(cnt, quad), harea
    return best


def snap_corners(img: np.ndarray, corners, radius: float | None = None) -> Corners:
    """Ajusta las esquinas a los bordes reales del panel (precisión subpíxel).

    Para cada lado mide, en muchos puntos, dónde cambia más el color perpendicularmente al
    lado, ajusta una recta y recalcula las esquinas. Si algo no cuadra devuelve las originales.
    """
    q = order_corners(corners)
    lab = cv2.cvtColor(cv2.GaussianBlur(img, (0, 0), 1.2), cv2.COLOR_BGR2LAB).astype(np.float32)
    center = q.mean(0)
    lines = []
    for i in range(4):
        a, b = q[i], q[(i + 1) % 4]
        d = b - a
        L = float(np.linalg.norm(d))
        if L < 20:
            return [tuple(map(float, p)) for p in q]
        d /= L
        n = np.array([-d[1], d[0]], np.float32)
        R = radius or max(8.0, 0.015 * L)
        ts = np.linspace(0.12, 0.88, 60, dtype=np.float32)
        ss = np.arange(-R, R + 0.01, 0.5, dtype=np.float32)
        base = a[None, :] + ts[:, None] * (b - a)[None, :]  # (60, 2)
        pos = base[:, None, :] + ss[None, :, None] * n[None, None, :]  # (60, ns, 2)
        prof = cv2.remap(lab, pos[..., 0], pos[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        g = np.linalg.norm(prof[:, 2:] - prof[:, :-2], axis=2)  # (60, ns-2)
        k = g.argmax(1)
        ok = (g[np.arange(len(ts)), k] > 10) & (k > 0) & (k < g.shape[1] - 1)
        if ok.sum() < 20:
            return [tuple(map(float, p)) for p in q]
        kk = k[ok]
        gy = g[ok]
        y0, y1, y2 = gy[np.arange(len(kk)), kk - 1], gy[np.arange(len(kk)), kk], gy[np.arange(len(kk)), np.minimum(kk + 1, gy.shape[1] - 1)]
        den = y0 - 2 * y1 + y2
        off = np.where(np.abs(den) > 1e-6, 0.5 * (y0 - y2) / den, 0.0).clip(-1, 1)
        s_star = ss[kk + 1] + off * 0.5  # +1: el gradiente está centrado en kk+1
        pts = base[ok] + s_star[:, None] * n[None, :]
        vx, vy, x0, y0_ = cv2.fitLine(pts.astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        lines.append((np.array([x0, y0_], np.float32), np.array([vx, vy], np.float32)))
    out = []
    for i in range(4):
        (p1, d1), (p2, d2) = lines[i - 1], lines[i]
        A = np.array([d1, -d2]).T
        if abs(np.linalg.det(A)) < 1e-6:
            return [tuple(map(float, p)) for p in q]
        t = np.linalg.solve(A, p2 - p1)
        out.append(p1 + t[0] * d1)
    out = np.array(out, np.float32)
    lim = radius or max(8.0, 0.015 * float(np.linalg.norm(q[1] - q[0]))) * 2.5
    if np.abs(out - q).max() > lim:
        return [tuple(map(float, p)) for p in q]
    return [(float(x), float(y)) for x, y in out]


def detect_panel(img: np.ndarray) -> Corners | None:
    """Busca el panel: primero por color; si no, el cuadrilátero más grande por bordes."""
    h, w = img.shape[:2]
    k = 800 / max(h, w) if max(h, w) > 800 else 1.0
    small = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else img
    by_color = _detect_by_color(small)
    if by_color is not None:
        q = order_corners(by_color / k)
        return snap_corners(img, q)
    lab = cv2.cvtColor(cv2.GaussianBlur(small, (5, 5), 0), cv2.COLOR_BGR2LAB)
    # bordes en los tres canales de color (un panel verde sobre acero casi no cambia en gris)
    edges = np.zeros(small.shape[:2], np.uint8)
    for c in range(3):
        edges |= cv2.Canny(lab[:, :, c], 30, 90)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    area_img = small.shape[0] * small.shape[1]
    best, best_area = None, 0.0
    for c in contours:
        hull = cv2.convexHull(c)
        area = cv2.contourArea(hull)
        if area < 0.2 * area_img or area <= best_area:
            continue
        quad = _quad(hull)
        if quad is not None:
            best, best_area = quad, area
    if best is None:
        return None
    return snap_corners(img, order_corners(best / k))
