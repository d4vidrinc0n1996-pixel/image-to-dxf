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
    p.add_argument("--no-denoise", action="store_true", help="no filtrar el ruido de la foto")
    p.add_argument("--upscale", type=int, help="supermuestreo 1-4 (por defecto automático)")
    p.add_argument("--corners", type=float, nargs=8, metavar="N",
                   help="4 esquinas del panel en la foto: x1 y1 x2 y2 x3 y3 x4 y4 (endereza la perspectiva)")
    p.add_argument("--auto-perspective", action="store_true", help="detecta el panel y lo endereza")
    p.add_argument("--aspect", type=float, help="ancho/alto real del panel (opcional)")
    p.add_argument("--inset", type=float, default=0.0, help="recorte de borde tras enderezar (0-0.2)")
    p.add_argument("--max-dim", type=int, default=2000)
    p.add_argument("--scale", type=float, default=1.0, help="unidades DXF por píxel")
    p.add_argument("--width-mm", type=float, help="ancho final (anula --scale)")
    p.add_argument("--dxf-polyline", action="store_true",
                   help="aplana curvas a polilíneas (máxima compatibilidad)")
    p.add_argument("--tolerance", type=float, default=0.1)
    a = p.parse_args()

    o = Options(
        colors=a.colors, threshold=a.threshold, invert=a.invert, blur=a.blur,
        curves=not a.no_curves, smooth=a.smooth, opt_tolerance=a.opt_tolerance,
        epsilon=a.epsilon, min_area=a.min_area, skip_background=not a.keep_background,
        centerline=a.centerline, min_length=a.min_length,
        crop=tuple(a.crop) if a.crop else None,
        corners=[(a.corners[i], a.corners[i + 1]) for i in range(0, 8, 2)] if a.corners else None,
        auto_perspective=a.auto_perspective, aspect=a.aspect, inset=a.inset, denoise=not a.no_denoise,
        upscale=a.upscale, max_dim=a.max_dim, scale=a.scale, width_mm=a.width_mm,
        dxf_curves="polyline" if a.dxf_polyline else "spline", tolerance=a.tolerance,
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
