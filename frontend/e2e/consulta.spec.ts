import { expect, test } from "@playwright/test";

import { entrar } from "./apoio";

/**
 * O parser determinístico da Parte 5, verificado pela interface.
 *
 * Metade destes testes é sobre o que ele recusa, e é a metade que importa: um parser que
 * chuta devolve número errado com aparência de certo, e quem lê a tela decide compra com
 * esse número.
 */
test.describe("Consulta em linguagem natural", () => {
  test.beforeEach(async ({ page }) => {
    await entrar(page);
    await page.getByTestId("aba-consulta").click();
  });

  async function perguntar(page: import("@playwright/test").Page, texto: string) {
    await page.getByTestId("pergunta").fill(texto);
    await page.getByTestId("perguntar").click();
  }

  test("pergunta sobre estoque mostra a interpretação e os filtros aplicados", async ({
    page,
  }) => {
    await perguntar(page, "produtos com estoque abaixo de 10");

    await expect(page.getByTestId("interpretacao")).toContainText("estoque");
    await expect(page.getByTestId("interpretacao")).toContainText("10");
    // Os filtros aplicados na tela são o que torna a resposta conferível: sem eles, o
    // número seria só um número sem procedência.
    await expect(page.getByTestId("filtros-aplicados")).toContainText("estoque_max");
    await expect(page.getByTestId("total-consulta")).toContainText("produto(s)");
  });

  test("pergunta sobre preço filtra por preço, e não por estoque", async ({ page }) => {
    await perguntar(page, "produtos com preço acima de 200");

    await expect(page.getByTestId("filtros-aplicados")).toContainText("preco_min");
    await expect(page.getByTestId("filtros-aplicados")).not.toContainText("estoque");
  });

  test("contagem não devolve a lista", async ({ page }) => {
    await perguntar(page, "quantos produtos estão em falta");

    await expect(page.getByTestId("interpretacao")).toContainText("Contar");
    await expect(page.getByTestId("total-consulta")).toBeVisible();
    await expect(page.getByTestId("itens-consulta")).toHaveCount(0);
  });

  test("pergunta ambígua é recusada com as duas interpretações", async ({ page }) => {
    // "abaixo de 10" — dez de quê? Chutar estoque quando a pessoa queria preço é o bug
    // que este comportamento existe para impedir.
    await perguntar(page, "produtos abaixo de 10");

    await expect(page.getByTestId("recusa")).toBeVisible();
    await expect(page.getByTestId("motivo-recusa")).toContainText("estoque ou preço");
    await expect(page.getByTestId("sugestoes").getByRole("button")).toHaveCount(2);
    await expect(page.getByTestId("resultado")).toHaveCount(0);
  });

  test("clicar numa sugestão resolve a ambiguidade", async ({ page }) => {
    await perguntar(page, "produtos abaixo de 10");
    await page.getByTestId("sugestoes").getByRole("button").first().click();

    await expect(page.getByTestId("resultado")).toBeVisible();
    await expect(page.getByTestId("recusa")).toHaveCount(0);
  });

  test("pergunta fora do domínio é recusada sem quebrar a tela", async ({ page }) => {
    await perguntar(page, "qual a previsão do tempo amanhã");

    await expect(page.getByTestId("recusa")).toBeVisible();
    await expect(page.getByTestId("resultado")).toHaveCount(0);
  });

  test("entrada hostil não derruba a aplicação", async ({ page }) => {
    await perguntar(page, "'; DROP TABLE produto; --");

    // A tela continua utilizável, e o catálogo continua existindo.
    await expect(page.getByTestId("recusa")).toBeVisible();
    await page.getByTestId("aba-produtos").click();
    await expect(page.getByTestId("linha-produto").first()).toBeVisible();
  });
});
