from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .vectorize import ImageError, Options, convert

STATIC = Path(__file__).parent / "static"
MAX_BYTES = 20 * 1024 * 1024

app = FastAPI(title="image-to-dxf")


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
        colors, threshold, invert, blur, curves, smooth, opt_tolerance, epsilon,
        min_area, skip_background, centerline, min_length, box, max_dim, scale, width_mm, dxf_curves, tolerance,
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


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
