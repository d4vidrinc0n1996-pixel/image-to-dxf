"""Genera el logotipo (SVG + PNG) de TrazaCAD. Uso: python tools/make_logo.py"""
import math
import sys
from pathlib import Path

NAME_A, NAME_B = "Traza", "CAD"
TAGLINE = "Imágenes a vectores, DXF y DWG"
OUT = Path(__file__).resolve().parent.parent / "app" / "static"

BG1, BG2 = "#0F6B4C", "#0A3B2B"   # verde profundo (el del letrero)
PIX, INK, ACC = "#8CEBC8", "#FFFFFF", "#FFB020"

P = [(46, 190), (120, 196), (136, 62), (210, 66)]  # curva cúbica del símbolo


def bez(p, t):
    u = 1 - t
    return tuple(u**3 * p[0][i] + 3*u*u*t * p[1][i] + 3*u*t*t * p[2][i] + t**3 * p[3][i] for i in (0, 1))


def split(p, t):
    """De Casteljau: devuelve (izquierda, derecha)."""
    lerp = lambda a, b: tuple(a[i] + (b[i] - a[i]) * t for i in (0, 1))
    a, b, c = lerp(p[0], p[1]), lerp(p[1], p[2]), lerp(p[2], p[3])
    d, e = lerp(a, b), lerp(b, c)
    m = lerp(d, e)
    return [p[0], a, d, m], [m, e, c, p[3]]


def icon_body(size_note=""):
    left, right = split(P, 0.5)
    # trazo pixelado: celdas de 16 px cuyo centro cae cerca de la primera mitad de la curva
    samples = [bez(left, i / 200) for i in range(201)]
    cell, gap, half = 16, 2, 15
    cells = set()
    for gx in range(0, 256, cell):
        for gy in range(0, 256, cell):
            cx, cy = gx + cell / 2, gy + cell / 2
            if min(math.hypot(cx - x, cy - y) for x, y in samples) < half:
                cells.add((gx, gy))
    rects = "".join(
        f'<rect x="{x + gap/2}" y="{y + gap/2}" width="{cell - gap}" height="{cell - gap}" rx="2.5"/>'
        for x, y in sorted(cells)
    )
    m, e = right[0], right[3]
    h1, h2 = right[1], right[2]
    f = lambda q: f"{q[0]:.1f} {q[1]:.1f}"
    return f"""
  <g fill="{PIX}" opacity=".95">{rects}</g>
  <path d="M{f(right[0])} C{f(h1)} {f(h2)} {f(right[3])}" fill="none" stroke="{INK}" stroke-width="28" stroke-linecap="round"/>
  <g stroke="{ACC}" stroke-width="3" stroke-linecap="round" opacity=".95">
    <line x1="{m[0]:.1f}" y1="{m[1]:.1f}" x2="{h1[0]:.1f}" y2="{h1[1]:.1f}"/>
    <line x1="{e[0]:.1f}" y1="{e[1]:.1f}" x2="{h2[0]:.1f}" y2="{h2[1]:.1f}"/>
  </g>
  <g fill="{ACC}"><circle cx="{h1[0]:.1f}" cy="{h1[1]:.1f}" r="6"/><circle cx="{h2[0]:.1f}" cy="{h2[1]:.1f}" r="6"/></g>
  <g fill="{ACC}" stroke="{INK}" stroke-width="4" stroke-linejoin="round">
    <rect x="{m[0]-9:.1f}" y="{m[1]-9:.1f}" width="18" height="18" rx="3"/>
    <rect x="{e[0]-9:.1f}" y="{e[1]-9:.1f}" width="18" height="18" rx="3"/>
  </g>"""


def icon_svg(rounded=True):
    rx = 56 if rounded else 0
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" role="img" aria-label="{NAME_A}{NAME_B}">
  <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{BG1}"/><stop offset="1" stop-color="{BG2}"/></linearGradient></defs>
  <rect width="256" height="256" rx="{rx}" fill="url(#g)"/>{icon_body()}
</svg>
"""


FONT = "'Inter','Segoe UI','Helvetica Neue',Arial,sans-serif"


def wordmark_svg(dark_bg=False):
    a = INK if dark_bg else BG2
    b = "#43D9A3" if dark_bg else "#0F9D6B"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1010 256" role="img" aria-label="{NAME_A}{NAME_B}">
  <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{BG1}"/><stop offset="1" stop-color="{BG2}"/></linearGradient></defs>
  <rect width="256" height="256" rx="56" fill="url(#g)"/>{icon_body()}
  <text x="292" y="148" font-family="{FONT}" font-size="118" font-weight="800" letter-spacing="-3" fill="{a}">{NAME_A}<tspan fill="{b}">{NAME_B}</tspan></text>
  <text x="296" y="204" font-family="{FONT}" font-size="31" font-weight="500" fill="{a}" opacity=".72">{TAGLINE}</text>
</svg>
"""


def card_html():
    return f"""<html><body style="margin:0;width:1200px;height:630px;background:linear-gradient(135deg,{BG1},{BG2});
display:flex;align-items:center;justify-content:center;gap:56px;font-family:{FONT};color:#fff">
<div style="width:260px;height:260px">{icon_svg().replace('<svg ', '<svg width="260" height="260" ')}</div>
<div><div style="font-size:128px;font-weight:800;letter-spacing:-3px;line-height:1">{NAME_A}<span style="color:#43D9A3">{NAME_B}</span></div>
<div style="font-size:36px;opacity:.85;margin-top:18px">{TAGLINE}</div></div></body></html>"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "logo.svg").write_text(icon_svg())
    (OUT / "logo-wordmark.svg").write_text(wordmark_svg())
    (OUT / "logo-wordmark-dark.svg").write_text(wordmark_svg(dark_bg=True))
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Sin playwright: solo SVG"); return
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path="/opt/pw-browsers/chromium" if Path("/opt/pw-browsers/chromium").exists() else None)
        for name, size, rounded in [("logo-512.png", 512, True), ("apple-touch-icon.png", 180, False), ("favicon-32.png", 32, True), ("icon-192.png", 192, True)]:
            pg = b.new_page(viewport={"width": size, "height": size})
            pg.set_content(f'<body style="margin:0">{icon_svg(rounded).replace("<svg ", f"<svg width=%d height=%d " % (size, size))}</body>')
            pg.screenshot(path=str(OUT / name), omit_background=True)
        pg = b.new_page(viewport={"width": 1200, "height": 630})
        pg.set_content(card_html()); pg.screenshot(path=str(OUT / "og.png"))
        pg = b.new_page(viewport={"width": 1010, "height": 256})
        pg.set_content(f'<body style="margin:0;background:#fff">{wordmark_svg().replace("<svg ", "<svg width=1010 height=256 ")}</body>')
        pg.screenshot(path="/tmp/_wordmark_preview.png")
        b.close()
    print("Logo generado en", OUT)


if __name__ == "__main__":
    main()
