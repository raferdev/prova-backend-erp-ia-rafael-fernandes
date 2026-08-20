import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// O front sempre chama `/api/...` relativo, e quem resolve o destino é um proxy: o Vite
// no desenvolvimento, o nginx no Compose.
//
// A alternativa seria habilitar CORS na API e embutir a URL dela no build. Isso troca uma
// linha de configuração por duas fontes de erro: origem liberada errada em produção, e
// build que precisa ser refeito quando o endereço da API muda. Proxy não tem nenhuma das
// duas, e de quebra o navegador nunca faz requisição cross-origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.ERP_API_URL ?? "http://localhost:8000",
        changeOrigin: true,
        rewrite: (caminho) => caminho.replace(/^\/api/, ""),
      },
    },
  },
});
