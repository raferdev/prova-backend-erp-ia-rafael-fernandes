# Multi-stage, mesma lógica do Dockerfile da API: o estágio de build carrega o Node e as
# dependências; o de runtime leva só os arquivos estáticos e um nginx.
#
# A imagem final não tem Node nem `node_modules` — nada que sirva de superfície de ataque
# num container que só entrega HTML, CSS e JS.

# ---------- build ----------
FROM node:22-alpine AS builder

WORKDIR /build

# Manifestos primeiro: enquanto as dependências não mudarem, o Docker reaproveita a camada
# de instalação mesmo que o código mude.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ---------- runtime ----------
FROM nginx:1.27-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /build/dist /usr/share/nginx/html

EXPOSE 80

# 127.0.0.1 e nao `localhost`: dentro do container, `localhost` resolve primeiro para ::1,
# e o nginx com `listen 80` so escuta em IPv4. O healthcheck falhava com "connection
# refused" enquanto o servidor respondia normalmente de fora.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --spider -q http://127.0.0.1/ || exit 1
