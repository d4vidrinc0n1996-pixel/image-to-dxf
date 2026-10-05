# --- Etapa 1: compila LibreDWG (escribe DWG a partir de DXF) ---
FROM python:3.11-slim-bookworm AS libredwg
ARG LIBREDWG_VERSION=0.13.3
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential curl xz-utils ca-certificates \
 && rm -rf /var/lib/apt/lists/*
# Si la compilación falla, la imagen se construye igual y el app avisa que DWG no está disponible.
RUN mkdir -p /opt/libredwg && ( \
      curl -fsSL "https://github.com/LibreDWG/libredwg/releases/download/${LIBREDWG_VERSION}/libredwg-${LIBREDWG_VERSION}.tar.xz" \
        | tar xJ -C /tmp \
   && cd "/tmp/libredwg-${LIBREDWG_VERSION}" \
   && ./configure --prefix=/opt/libredwg --disable-bindings --disable-python \
   && make -j2 && make install \
   ) || echo "AVISO: LibreDWG no se pudo compilar; el formato DWG quedará desactivado"

# --- Etapa 2: el app ---
FROM python:3.11-slim-bookworm
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=libredwg /opt/libredwg /opt/libredwg
ENV LIBREDWG_PREFIX=/opt/libredwg PATH=/opt/libredwg/bin:$PATH LD_LIBRARY_PATH=/opt/libredwg/lib
# Comprobación en el build: si falta, el log lo dirá claramente
RUN (dxf2dwg --version && echo "DWG OK: LibreDWG instalado") || echo "AVISO: dxf2dwg NO disponible; DWG desactivado"
COPY app app
ENV PORT=8000
EXPOSE 8000
# Render (y otros) asignan el puerto en $PORT
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
