from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

import cv2

from .perspective import detect_panel
from .vectorize import ImageError, Options, convert, decode, prepare

STATIC = Path(__file__).parent / "static"
MAX_BYTES = 20 * 1024 * 1024

app = FastAPI(title="image-to-dxf")


def parse_corners(text: str | None):
    if not text:
        return None
    try:
        v = [float(x) for x in text.split(",")]
        assert len(v) == 8
    except (ValueError, AssertionError):
        raise HTTPException(422, "corners debe ser x1,y1,x2,y2,x3,y3,x4,y4")
    return [(v[i], v[i + 1]) for i in range(0, 8, 2)]


@app.post("/api/convert")
async def api_convert(
    file: UploadFile = File(...),
    format: Literal["svg", "dxf", "zip"] = Form("dxf"),
    colors: int = Form(1, ge=1, le=16),
    threshold: int | None = Form(None, ge=0, le=255),
    invert: bool = Form(False),
    blur: int = Form(0, ge=0, le=31),
    curves: bool = Form(True),
    smooth: float = Form(1.0, ge=0, le=1.34),
    opt_tolerance: float = Form(0.2, ge=0, le=5),
    epsilon: float = Form(1.0, ge=0, le=50),
    min_area: float = Form(20.0, ge=0),
    skip_background: bool = Form(True),
    centerline: bool = Form(False),
    min_length: float = Form(10.0, ge=0),
    crop: str | None = Form(None, description="x0,y0,x1,y1 en píxeles"),
    corners: str | None = Form(None, description="4 esquinas del panel: x1,y1,...,x4,y4"),
    auto_perspective: bool = Form(False),
    aspect: float | None = Form(None, gt=0),
    inset: float = Form(0.0, ge=0, le=0.2),
    denoise: bool = Form(True),
    upscale: int | None = Form(None, ge=1, le=4),
    max_dim: int = Form(2000, ge=100, le=6000),
    scale: float = Form(1.0, gt=0),
    width_mm: float | None = Form(None, gt=0),
    dxf_curves: Literal["spline", "polyline"] = Form("spline"),
    tolerance: float = Form(0.1, gt=0),
):
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "Imagen demasiado grande (máx. 20 MB)")
    box = None
    if crop:
        try:
            box = tuple(int(v) for v in crop.split(","))
            assert len(box) == 4
        except (ValueError, AssertionError):
            raise HTTPException(422, "crop debe ser x0,y0,x1,y1")
    opts = Options(
        colors=colors, threshold=threshold, invert=invert, blur=blur, curves=curves,
        smooth=smooth, opt_tolerance=opt_tolerance, epsilon=epsilon, min_area=min_area,
        skip_background=skip_background, centerline=centerline, min_length=min_length,
        crop=box, corners=parse_corners(corners), auto_perspective=auto_perspective,
        aspect=aspect, inset=inset, denoise=denoise, upscale=upscale, max_dim=max_dim, scale=scale,
        width_mm=width_mm, dxf_curves=dxf_curves, tolerance=tolerance,
    )
    stem = Path(file.filename or "imagen").stem
    try:
        body, mime = convert(data, format, opts, stem)
    except (ImageError, ValueError) as e:
        raise HTTPException(400, str(e))
    name = f"{stem}.{format}"
    return Response(
        body, media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.post("/api/detect-panel")
async def api_detect_panel(file: UploadFile = File(...)):
    """Busca las 4 esquinas del panel en la foto (arriba-izq, arriba-der, abajo-der, abajo-izq)."""
    try:
        img = decode(await file.read(MAX_BYTES + 1))
    except ImageError as e:
        raise HTTPException(400, str(e))
    c = detect_panel(img)
    return {
        "width": img.shape[1],
        "height": img.shape[0],
        "corners": None if c is None else [[round(x, 1), round(y, 1)] for x, y in c],
    }


@app.post("/api/rectify")
async def api_rectify(
    file: UploadFile = File(...),
    corners: str | None = Form(None),
    auto_perspective: bool = Form(False),
    aspect: float | None = Form(None, gt=0),
    inset: float = Form(0.0, ge=0, le=0.2),
):
    """Vista previa (PNG) de la imagen enderezada."""
    opts = Options(corners=parse_corners(corners), auto_perspective=auto_perspective, aspect=aspect, inset=inset)
    try:
        img = prepare(await file.read(MAX_BYTES + 1), opts)
    except (ImageError, ValueError) as e:
        raise HTTPException(400, str(e))
    return Response(cv2.imencode(".png", img)[1].tobytes(), media_type="image/png")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
