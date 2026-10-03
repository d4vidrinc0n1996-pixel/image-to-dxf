"""Uso: python -m app.cli logo.png foto.jpg -o salida/ --colors 4 --width-mm 100"""
import argparse
from pathlib import Path

from .vectorize import Options, convert


def main() -> None:
    p = argparse.ArgumentParser(description="Imagen -> SVG/DXF (curvas y capas de color)")
    p.add_argument("inputs", nargs="+")
    p.add_argument("-o", "--output", required=True,
                   help="archivo (.svg/.dxf) si hay una entrada; carpeta si hay varias")
    p.add_argument("--format", choices=["svg", "dxf", "zip"],
                   help="por defecto: la extensión de -o, o dxf al usar carpeta")
    p.add_argument("--colors", type=int, default=1, help="1 = B/N; 2-16 = capas de color")
    p.add_argument("--threshold", type=int)
    p.add_argument("--invert", action="store_true")
    p.add_argument("--blur", type=int, default=0)
    p.add_argument("--no-curves", action="store_true", help="polígonos en vez de Bézier")
    p.add_argument("--smooth", type=float, default=1.0, help="0 = esquinas, 1.33 = redondo")
    p.add_argument("--opt-tolerance", type=float, default=0.2)
    p.add_argument("--epsilon", type=float, default=1.0)
    p.add_argument("--min-area", type=float, default=20.0)
    p.add_argument("--keep-background", action="store_true")
    p.add_argument("--centerline", action="store_true",
                   help="traza la línea central de los trazos finos (planos, firmas)")
    p.add_argument("--min-length", type=float, default=10.0, help="centerline: largo mínimo (px)")
    p.add_argument("--crop", type=int, nargs=4, metavar=("X0", "Y0", "X1", "Y1"),
                   help="recorta antes de vectorizar (píxeles de la imagen original)")
    p.add_argument("--max-dim", type=int, default=2000)
    p.add_argument("--scale", type=float, default=1.0, help="unidades DXF por píxel")
    p.add_argument("--width-mm", type=float, help="ancho final (anula --scale)")
    p.add_argument("--dxf-polyline", action="store_true",
                   help="aplana curvas a polilíneas (máxima compatibilidad)")
    p.add_argument("--tolerance", type=float, default=0.1)
    a = p.parse_args()

    o = Options(
        a.colors, a.threshold, a.invert, a.blur, not a.no_curves, a.smooth,
        a.opt_tolerance, a.epsilon, a.min_area, not a.keep_background, a.centerline, a.min_length, tuple(a.crop) if a.crop else None, a.max_dim,
        a.scale, a.width_mm, "polyline" if a.dxf_polyline else "spline", a.tolerance,
    )
    out = Path(a.output)
    multi = len(a.inputs) > 1 or out.is_dir() or not out.suffix
    for src in map(Path, a.inputs):
        if multi:
            out.mkdir(parents=True, exist_ok=True)
            fmt = a.format or "dxf"
            dest = out / f"{src.stem}.{fmt}"
        else:
            fmt = a.format or out.suffix.lstrip(".").lower()
            if fmt not in ("svg", "dxf", "zip"):
                p.error("la salida debe terminar en .svg, .dxf o .zip")
            dest = out
        body, _ = convert(src.read_bytes(), fmt, o, src.stem)
        dest.write_bytes(body)
        print(f"{src} -> {dest}")


if __name__ == "__main__":
    main()
