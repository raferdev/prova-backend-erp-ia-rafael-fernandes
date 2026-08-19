# Multi-stage: o estagio `builder` carrega o gerenciador de pacotes e compila as
# dependencias; o estagio final leva apenas o virtualenv pronto e o codigo. Isso mantem
# a imagem de runtime pequena e sem toolchain de build (menor superficie de ataque).

# ---------- stage 1: build ----------
FROM python:3.12-slim AS builder

# uv no lugar de pip: resolve e instala ordens de magnitude mais rapido e usa lockfile
# deterministico, o que torna o build reproduzivel.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /build

# Copiamos so os manifestos primeiro: enquanto as dependencias nao mudarem, o Docker
# reaproveita esta camada mesmo que o codigo da aplicacao mude.
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project

# ---------- stage 2: runtime ----------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Usuario sem privilegios: container nao roda como root.
RUN useradd --create-home --uid 1000 appuser

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
