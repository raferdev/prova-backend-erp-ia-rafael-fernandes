import { expect, test } from "@playwright/test";

import { entrar } from "./apoio";

test.describe("Catálogo", () => {
  test.beforeEach(async ({ page }) => entrar(page));

  test("lista produtos do seed", async ({ page }) => {
    await expect(page.getByTestId("linha-produto").first()).toBeVisible();
    await expect(page.getByTestId("total")).toContainText("produto(s)");
  });

  test("filtro por nome reduz o resultado", async ({ page }) => {
    // Espero a tabela carregar antes de contar. Sem isso, `count()` roda com a lista ainda
    // vazia e devolve 0 — a asserção falharia por corrida do teste, não por defeito da tela.
    await expect(page.getByTestId("linha-produto").first()).toBeVisible();
    const antes = await page.getByTestId("linha-produto").count();

    await page.getByTestId("filtro-nome").fill("cabo");

    await expect(page.getByTestId("linha-produto")).toHaveCount(1);
    expect(antes).toBeGreaterThan(1);
    await expect(page.getByTestId("linha-produto").first()).toContainText("Cabo");
  });

  test("filtro sem correspondência mostra estado vazio, e não tabela em branco", async ({
    page,
  }) => {
    await page.getByTestId("filtro-nome").fill("xyzabc-nao-existe");

    await expect(page.getByTestId("sem-resultado")).toBeVisible();
  });

  test("estoque baixo marca as linhas e usa o mínimo de cada produto", async ({ page }) => {
    await page.getByTestId("filtro-estoque-baixo").check();

    const linhas = page.getByTestId("linha-produto");

    // Espera determinística: enquanto a requisição do filtro está no ar, a tabela ainda
    // mostra as linhas antigas. Esperar só por "a primeira linha existe" pegava a lista
    // não filtrada e o teste falhava de forma intermitente — passava sozinho e falhava em
    // paralelo. Aqui espero até que nenhuma linha visível esteja sem a tag "repor".
    await expect(linhas.filter({ hasNotText: "repor" })).toHaveCount(0);
    await expect(linhas.first()).toBeVisible();

    // Todo produto listado precisa ter saldo <= mínimo. O limiar é por produto, então não
    // dá para conferir contra um número fixo — é a regra que um `WHERE qtd < 10` erraria.
    const contagem = await linhas.count();
    for (let i = 0; i < contagem; i++) {
      const celulas = linhas.nth(i).locator("td");
      const estoque = Number((await celulas.nth(2).innerText()).replace(/\D+/g, ""));
      const minimo = Number(await celulas.nth(3).innerText());
      expect(estoque).toBeLessThanOrEqual(minimo);
    }
  });

  test("paginação avança sem repetir produto", async ({ page }) => {
    await expect(page.getByTestId("pagina-atual")).toContainText("1 de");

    const primeiraPagina = await page.getByTestId("linha-produto").allInnerTexts();
    await page.getByTestId("pagina-proxima").click();

    await expect(page.getByTestId("pagina-atual")).toContainText("2 de");
    const segundaPagina = await page.getByTestId("linha-produto").allInnerTexts();

    for (const linha of segundaPagina) {
      expect(primeiraPagina).not.toContain(linha);
    }
  });

  test("filtrar estando na página 2 não deixa o usuário numa página vazia", async ({
    page,
  }) => {
    // Verifico a consequência para o usuário, e não o número da página.
    //
    // A primeira versão deste teste afirmava que `pagina-atual` passaria a mostrar "1 de",
    // e era impossível de satisfazer: quando o resultado filtrado cabe em uma página, o
    // controle de paginação some da tela. O teste falhava com a aplicação correta.
    //
    // O que de fato importa é que filtrar na página 2 mostre o resultado, e não uma tela
    // vazia — que é o que aconteceria se a página não fosse reiniciada, porque o offset
    // continuaria além do fim.
    await page.getByTestId("pagina-proxima").click();
    await expect(page.getByTestId("pagina-atual")).toContainText("2 de");

    await page.getByTestId("filtro-nome").fill("cabo");

    await expect(page.getByTestId("linha-produto")).toHaveCount(1);
    await expect(page.getByTestId("sem-resultado")).toHaveCount(0);
  });
});
