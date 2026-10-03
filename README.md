# image-to-dxf

Convierte imágenes (PNG, JPG, BMP, WebP…) a vectores **SVG** y **DXF**, con:

- **Curvas Bézier** suaves (trazado tipo Potrace) o polígonos.
- **Capas por color**: de 2 a 16 colores; cada color es una capa del DXF (con su color real) y un grupo del SVG.
- **Modo línea central** (`centerline`): para planos, firmas y texto fino; genera líneas abiertas (una por trazo) en vez de contornos dobles, y en el SVG las dibuja con trazo.
- **Corrección de perspectiva**: endereza fotos tomadas en ángulo. Detecta el panel solo (`auto_perspective`) o con 4 esquinas (`corners`); las esquinas se ajustan a los bordes reales con precisión subpíxel. En la web las marcas con clics sobre la foto.
- Limpieza automática de motas y ruido en cada capa de color.
- Modo blanco y negro con umbral automático (Otsu) para corte láser / CNC.
- Tamaño final en mm (`width_mm`) o por escala; el eje Y se invierte para no salir espejado en CAD.
- DXF con **splines** o con **polilíneas** (máxima compatibilidad con software CAM).
- **DWG** (AutoCAD R2000) además de DXF y SVG, vía LibreDWG. Ver "Formato DWG" abajo.
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
python -m app.cli plano.png -o plano.dxf --centerline --width-mm 300  # líneas finas
python -m app.cli a.png b.png c.jpg -o salida/ --format zip        # lote: SVG + DXF
```

## API

`POST /api/convert` (multipart): `file` y `format=svg|dxf|dwg|zip`, más las opciones de abajo.

```bash
curl -F file=@logo.png -F format=dxf -F colors=4 -F width_mm=120 localhost:8000/api/convert -o logo.dxf
```

## Formato DWG

DWG es un formato propietario de Autodesk; no hay escritor nativo en Python, así que el app genera un DXF y lo convierte con [LibreDWG](https://www.gnu.org/software/libredwg/) (`dxf2dwg`). Lo que debes saber:

- Sale en **DWG R2000** (AC1015), que abre cualquier versión posterior de AutoCAD y la mayoría de programas CAD. LibreDWG todavía no escribe versiones más nuevas con fiabilidad.
- Los colores de capa se convierten al color AutoCAD (ACI) más cercano: R2000 no admite RGB real. Si necesitas el color exacto, usa el DXF o el SVG.
- LibreDWG marca su escritor como experimental. Las pruebas leen el DWG de vuelta y comprueban entidades, capas y coordenadas, pero **no se ha abierto en AutoCAD**: si lo vas a usar para producción, ábrelo y revísalo antes. El DXF sigue siendo el formato más seguro.
- El **Dockerfile** ya compila LibreDWG. En local: instálalo (o compílalo) para que `dxf2dwg` esté en el `PATH`, o apunta `LIBREDWG_PREFIX` a su carpeta de instalación (por defecto `/opt/libredwg`). Si no está, el botón de DWG no aparece y la API responde `501`.
- `GET /api/capabilities` indica qué formatos ofrece el servidor.

```bash
python -m app.cli letrero.jpg -o letrero.dwg --auto-perspective --colors 2 --width-mm 300
```

## Opciones

| Opción | Por defecto | Efecto |
|---|---|---|
| `colors` | 1 | 1 = blanco/negro; 2–16 = una capa por color |
| `skip_background` | sí | En multicolor, ignora el color que domina el borde |
| `centerline` | no | Traza la línea central de los trazos finos (líneas abiertas) |
| `min_length` | 10 | Con `centerline`: descarta líneas más cortas (px), quita rebabas |
| `curves` | sí | Curvas Bézier; si no, polígonos |
| `smooth` | 1.0 | 0 = todo esquinas … 1.33 = muy redondeado |
| `opt_tolerance` | 0.2 | Mayor = menos nodos, curvas más simplificadas |
| `epsilon` | 1.0 | Simplificación de polígonos (`curves=false`) |
| `threshold` | auto | Umbral 0–255 (solo `colors=1`) |
| `invert` | no | Traza las zonas claras (solo `colors=1`) |
| `blur` | 0 | Suavizado previo para reducir ruido |
| `min_area` | 20 | Descarta manchas menores (px²) |
| `auto_perspective` | no | Detecta el panel de la foto y lo endereza |
| `corners` | – | 4 esquinas del panel `x1,y1,…,x4,y4` (CLI: `--corners x1 y1 … y4`) |
| `aspect` | auto | Proporción real ancho/alto del panel; si se conoce, evita que salga estirado |
| `inset` | 0 (auto: 0.01) | Fracción a recortar de cada borde tras enderezar (quita el filo del panel) |
| `snap` | sí | Ajusta las esquinas manuales a los bordes reales |
| `crop` | – | `x0,y0,x1,y1` en px: recorta antes de vectorizar (útil para fotos con fondo) |
| `straighten` | sí | Limpia el trazo: tramos casi rectos pasan a ser líneas exactas y los colineales se funden |
| `straight_tol` | 0.7 | Tolerancia de esa limpieza (px) |
| `axis_snap` | 3 | Alinea a horizontal/vertical exactos los lados a menos de estos grados (0 = no) |
| `adapt_light` | sí | Corrige la iluminación desigual de las fotos (centros de color locales) |
| `denoise` | no | Filtro bilateral previo; útil solo con ruido fuerte |
| `upscale` | auto | Supermuestreo 1–4 antes de trazar (auto: ×2 solo si la imagen mide < 600 px) |
| `max_dim` | 2000 | Reduce imágenes mayores para ir más rápido (el tamaño físico se conserva) |
| `width_mm` / `scale` | – / 1 | Tamaño del DXF: ancho final, o unidades por píxel |
| `dxf_curves` | spline | `spline` o `polyline` (aplana con `tolerance`, 0.1 mm) |

## Calidad

`python tools/benchmark.py` genera una imagen de referencia (texto, círculos, líneas), la degrada como una foto (desenfoque, ruido, JPEG, luz desigual), la vectoriza y mide el solape (IoU) con la original. Valores actuales: ~0.97 (antes de las mejoras: 0.94). Qué influye:

- Umbral en el punto medio entre tonos (no Otsu) y centros de color por mediana: evitan formas más gordas o flacas.
- Centros de color locales: absorben el degradado de luz de una foto.
- El trazado de polígonos usa el borde real del píxel (sin quedar 1 px más pequeño).

## Rendimiento

Una imagen de 2000 px tarda ~3 s en B/N y ~10 s con 6 colores (el trazador es Python puro).

## Pruebas

```bash
pip install -r requirements-dev.txt && pytest
```

## Limitaciones

- Por defecto vectoriza regiones rellenas: un trazo fino sale como contorno cerrado. Para trazos finos usa `centerline`.
- En `centerline`, los cruces se funden en un nodo y las líneas se cortan en cada cruce (cada tramo es una polilínea/spline aparte).
- Los colores se agrupan por k-means; los degradados quedan en bandas. Fotos muy detalladas necesitan más colores y salen pesadas.

## Fotos tomadas en ángulo

```bash
python -m app.cli letrero.jpg -o letrero.dxf --auto-perspective --colors 2 --width-mm 300
python -m app.cli letrero.jpg -o letrero.dxf --corners 53 53 791 53 789 1224 57 1227 --aspect 0.62 --colors 2
```

Con `aspect` (ancho/alto reales del panel, p. ej. 300/470 mm) el dibujo sale sin estirarse; sin él se estima de los bordes de la foto, que en perspectiva fuerte no es exacto. Endpoints: `POST /api/detect-panel` (devuelve las esquinas) y `POST /api/rectify` (vista previa PNG). El `crop` se aplica *después* de enderezar.

## Ejemplo: foto de un letrero (blanco sobre verde)

Recorta al panel y usa 2 colores; el verde (fondo) se ignora y quedan solo los gráficos blancos:

```bash
python -m app.cli letrero.jpg -o letrero.dxf --crop 62 52 795 1192 --colors 2 --width-mm 300
```
