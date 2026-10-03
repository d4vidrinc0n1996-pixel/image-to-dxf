"""DXF -> DWG con LibreDWG (`dxf2dwg`). DWG es un formato propietario: no hay escritor nativo en Python."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

PREFIX = Path(os.environ.get("LIBREDWG_PREFIX", "/opt/libredwg"))


class DwgUnavailable(RuntimeError):
    """No hay conversor DXF->DWG instalado en este equipo."""


class DwgError(RuntimeError):
    """El conversor falló o produjo un archivo inválido."""


def converter() -> str | None:
    """Ruta de `dxf2dwg` (en el PATH o en el prefijo de instalación), o None."""
    found = shutil.which("dxf2dwg")
    if found:
        return found
    cand = PREFIX / "bin" / "dxf2dwg"
    return str(cand) if cand.exists() else None


def available() -> bool:
    return converter() is not None


def dxf_to_dwg(dxf: bytes, timeout: float = 90) -> bytes:
    """Convierte un DXF (R2000) a DWG R2000."""
    exe = converter()
    if not exe:
        raise DwgUnavailable("El formato DWG no está disponible en este servidor (falta dxf2dwg / LibreDWG)")
    env = dict(os.environ)
    lib = PREFIX / "lib"
    if lib.exists():
        env["LD_LIBRARY_PATH"] = f"{lib}:{env.get('LD_LIBRARY_PATH', '')}"
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp, "in.dxf"), Path(tmp, "out.dwg")
        src.write_bytes(dxf)
        try:
            r = subprocess.run(
                [exe, "--as", "r2000", "-y", "-o", str(dst), str(src)],
                capture_output=True, timeout=timeout, env=env,
            )
        except subprocess.TimeoutExpired:
            raise DwgError("La conversión a DWG tardó demasiado")
        if r.returncode != 0 or not dst.exists():
            raise DwgError("No se pudo convertir a DWG: " + r.stderr.decode(errors="replace")[-300:])
        out = dst.read_bytes()
    # un DWG válido empieza con la versión ("AC1015" = R2000) y no es casi vacío
    if not out.startswith(b"AC10") or len(out) < 2000:
        raise DwgError("El conversor produjo un DWG inválido")
    return out
