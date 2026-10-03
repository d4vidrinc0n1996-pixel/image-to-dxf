# image-to-dxf

Convierte imágenes (PNG, JPG, BMP…) a vectores **SVG** y a **DXF** (contornos cerrados, en mm).

## Instalación

```bash
pip install -r requirements.txt
```

## Interfaz web

```bash
uvicorn app.main:app --reload
```
Abre http://localhost:8000, sube una imagen, ajusta opciones y descarga el DXF.

## Línea de comandos

```bash
python -m app.cli logo.png -o logo.dxf --scale 0.1   # 0.1 mm por píxel
python -m app.cli logo.png -o logo.svg --threshold 128
```

## Opciones

| Opción | Efecto |
|---|---|
| `threshold` | Umbral 0-255; sin valor usa Otsu automático |
| `invert` | Traza las zonas claras en vez de las oscuras |
| `blur` | Suavizado previo para reducir ruido |
| `epsilon` | Simplificación de los contornos (px); mayor = menos puntos |
| `min_area` | Descarta manchas más pequeñas que esta área |
| `scale` | Unidades DXF (mm) por píxel |

## Pruebas

```bash
pip install -r requirements-dev.txt && pytest
```

## Notas

Traza siluetas en blanco y negro (ideal para corte láser/CNC). El DXF usa polilíneas cerradas con el eje Y invertido para que no salga espejado en CAD.
