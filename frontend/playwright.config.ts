import { defineConfig, devices } from "@playwright/test";

/**
 * Os testes rodam contra a stack de verdade: Vite servindo o front e a API do Compose
 * atrás do proxy. Não há mock de rede em lugar nenhum.
 *
 * É uma escolha com custo: o suite precisa de `docker compose up` antes. Em troca, ele
 * verifica o que interessa — que o front, a API, o Postgres e o Redis conversam. Um E2E
 * com fetch mockado testaria o meu mock.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",

  use: {
    // Com `E2E_BASE_URL` definido, os testes rodam contra um front já servido — é o caso da
    // CI, que sobe o Compose inteiro (nginx incluído) antes. Sem ele, o Playwright levanta
    // o Vite sozinho, que é o fluxo local.
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5173",
    // Rastro só do que falhou: o vídeo e o trace de um teste verde são lixo de CI.
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    locale: "pt-BR",
  },

  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: "npm run dev",
        url: "http://localhost:5173",
        reuseExistingServer: !process.env.CI,
        timeout: 60_000,
      },
});
