"""Uso: python -m app.cli entrada.png -o salida.dxf [--threshold 128] [--scale 0.1]"""
import argparse
from pathlib import Path

from .vectorize import Options, to_dxf, to_svg, vectorize


def main() -> None:
    p = argparse.ArgumentParser(description="Imagen -> SVG/DXF")
    p.add_argument("input")
    p.add_argument("-o", "--output", required=True, help="termina en .svg o .dxf")
    p.add_argument("--threshold", type=int)
    p.add_argument("--invert", action="store_true")
    p.add_argument("--blur", type=int, default=0)
    p.add_argument("--epsilon", type=float, default=1.0)
    p.add_argument("--min-area", type=float, default=20.0)
    p.add_argument("--scale", type=float, default=1.0, help="unidades DXF (mm) por píxel")
    a = p.parse_args()

    opts = Options(a.threshold, a.invert, a.blur, a.epsilon, a.min_area, a.scale)
    vec = vectorize(Path(a.input).read_bytes(), opts)
    out = Path(a.output)
    if out.suffix.lower() == ".svg":
        out.write_text(to_svg(vec))
    elif out.suffix.lower() == ".dxf":
        out.write_bytes(to_dxf(vec, a.scale))
    else:
        p.error("la salida debe terminar en .svg o .dxf")
    print(f"{len(vec.polygons)} contornos -> {out}")


if __name__ == "__main__":
    main()
