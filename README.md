# image-to-dxf

Convierte imágenes (PNG, JPG, BMP, WebP…) a vectores **SVG** y **DXF**, con:

- **Curvas Bézier** suaves (trazado tipo Potrace) o polígonos.
- **Capas por color**: de 2 a 16 colores; cada color es una capa del DXF (con su color real) y un grupo del SVG.
- Modo blanco y negro con umbral automático (Otsu) para corte láser / CNC.
- Tamaño final en mm (`width_mm`) o por escala; el eje Y se invierte para no salir espejado en CAD.
- DXF con **splines** o con **polilíneas** (máxima compatibilidad con software CAM).
- Interfaz web, API REST, línea de comandos (por lotes) y Docker.

## Instalación

```bash
pip install -r requirements.txt
```

## Interfaz web

```bash
uvicorn app.main:app --reload     # http://localhost:8000
# o con Docker:
docker build -t image-to-dxf . && docker run -p 8000:8000 image-to-dxf
```

## Línea de comandos

```bash
python -m app.cli logo.png -o logo.dxf --width-mm 100              # B/N, 100 mm de ancho
python -m app.cli foto.jpg -o foto.dxf --colors 5 --width-mm 200   # 5 capas de color
python -m app.cli logo.png -o logo.dxf --dxf-polyline              # sin splines
python -m app.cli a.png b.png c.jpg -o salida/ --format zip        # lote: SVG + DXF
```

## API

`POST /api/convert` (multipart): `file` y `format=svg|dxf|zip`, más las opciones de abajo.

```bash
curl -F file=@logo.png -F format=dxf -F colors=4 -F width_mm=120 localhost:8000/api/convert -o logo.dxf
```

## Opciones

| Opción | Por defecto | Efecto |
|---|---|---|
| `colors` | 1 | 1 = blanco/negro; 2–16 = una capa por color |
| `skip_background` | sí | En multicolor, ignora el color que domina el borde |
| `curves` | sí | Curvas Bézier; si no, polígonos |
| `smooth` | 1.0 | 0 = todo esquinas … 1.33 = muy redondeado |
| `opt_tolerance` | 0.2 | Mayor = menos nodos, curvas más simplificadas |
| `epsilon` | 1.0 | Simplificación de polígonos (`curves=false`) |
| `threshold` | auto | Umbral 0–255 (solo `colors=1`) |
| `invert` | no | Traza las zonas claras (solo `colors=1`) |
| `blur` | 0 | Suavizado previo para reducir ruido |
| `min_area` | 20 | Descarta manchas menores (px²) |
| `max_dim` | 2000 | Reduce imágenes mayores para ir más rápido (el tamaño físico se conserva) |
| `width_mm` / `scale` | – / 1 | Tamaño del DXF: ancho final, o unidades por píxel |
| `dxf_curves` | spline | `spline` o `polyline` (aplana con `tolerance`, 0.1 mm) |

## Rendimiento

Una imagen de 2000 px tarda ~3 s en B/N y ~10 s con 6 colores (el trazador es Python puro).

## Pruebas

```bash
pip install -r requirements-dev.txt && pytest
```

## Limitaciones

- Vectoriza regiones rellenas (siluetas y áreas de color), no líneas centrales: un trazo fino se convierte en un contorno cerrado.
- Los colores se agrupan por k-means; los degradados quedan en bandas. Fotos muy detalladas necesitan más colores y salen pesadas.
