import { expect, test } from "@playwright/test";

import { CREDENCIAIS, entrar } from "./apoio";

test.describe("Autenticação", () => {
  test("login com credenciais válidas dá acesso ao catálogo", async ({ page }) => {
    await entrar(page);

    await expect(page.getByTestId("tabela-produtos")).toBeVisible();
  });

  test("senha errada não entra e mostra o motivo", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("email").fill(CREDENCIAIS.email);
    await page.getByTestId("senha").fill("senha-errada");
    await page.getByTestId("entrar").click();

    await expect(page.getByTestId("erro-login")).toBeVisible();
    await expect(page.getByTestId("aba-produtos")).toHaveCount(0);
  });

  test("a mensagem de erro não revela se o e-mail existe", async ({ page }) => {
    // Duas mensagens diferentes para "usuário não existe" e "senha errada" entregam ao
    // atacante uma lista de e-mails válidos. A API responde igual nos dois casos, e este
    // teste garante que o front não estrague isso mostrando algo mais específico.
    await page.goto("/");
    await page.getByTestId("email").fill("nao-existe@erp.local");
    await page.getByTestId("senha").fill("qualquer-coisa");
    await page.getByTestId("entrar").click();

    const comEmailInexistente = await page.getByTestId("erro-login").textContent();

    await page.getByTestId("email").fill(CREDENCIAIS.email);
    await page.getByTestId("senha").fill("senha-errada");
    await page.getByTestId("entrar").click();

    await expect(page.getByTestId("erro-login")).toHaveText(comEmailInexistente!);
  });

  test("sair limpa a sessão e recarregar não volta autenticado", async ({ page }) => {
    await entrar(page);
    await page.getByTestId("sair").click();

    await expect(page.getByTestId("entrar")).toBeVisible();

    await page.reload();
    await expect(page.getByTestId("entrar")).toBeVisible();
  });

  test("token inválido no navegador volta para o login", async ({ page }) => {
    // Simula token expirado: a aplicação tem que voltar ao login em vez de ficar num
    // limbo em que a tela existe e nenhuma chamada funciona.
    await page.goto("/");
    await page.evaluate(() => localStorage.setItem("erp.token", "isto-nao-e-um-jwt"));
    await page.reload();

    await expect(page.getByTestId("entrar")).toBeVisible({ timeout: 10_000 });
  });
});
