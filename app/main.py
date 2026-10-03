from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .vectorize import ImageError, Options, to_dxf, to_svg, vectorize

STATIC = Path(__file__).parent / "static"
MAX_BYTES = 20 * 1024 * 1024

app = FastAPI(title="image-to-dxf")


@app.post("/api/convert")
async def convert(
    file: UploadFile = File(...),
    format: Literal["svg", "dxf"] = Form("dxf"),
    threshold: int | None = Form(None, ge=0, le=255),
    invert: bool = Form(False),
    blur: int = Form(0, ge=0, le=31),
    epsilon: float = Form(1.0, ge=0, le=50),
    min_area: float = Form(20.0, ge=0),
    scale: float = Form(1.0, gt=0),
):
    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "Imagen demasiado grande (máx. 20 MB)")
    opts = Options(threshold, invert, blur, epsilon, min_area, scale)
    try:
        vec = vectorize(data, opts)
    except ImageError as e:
        raise HTTPException(400, str(e))
    stem = Path(file.filename or "imagen").stem
    if format == "svg":
        body, mime = to_svg(vec).encode(), "image/svg+xml"
    else:
        body, mime = to_dxf(vec, scale), "application/dxf"
    return Response(
        body,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{stem}.{format}"'},
    )


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
