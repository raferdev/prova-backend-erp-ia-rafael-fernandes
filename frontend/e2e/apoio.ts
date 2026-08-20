import { expect, type Page } from "@playwright/test";

export const CREDENCIAIS = { email: "admin@erp.local", senha: "admin123" };

/** Faz login pela interface, e não injetando token.
 *
 * Injetar o token direto no localStorage seria mais rápido, e pularia justamente o pedaço
 * que quero verificar: que o front fala com `/auth/token` no formato certo (form-urlencoded,
 * não JSON) e guarda o que recebe.
 */
export async function entrar(page: Page) {
  await page.goto("/");
  await page.getByTestId("email").fill(CREDENCIAIS.email);
  await page.getByTestId("senha").fill(CREDENCIAIS.senha);
  await page.getByTestId("entrar").click();
  await expect(page.getByTestId("aba-produtos")).toBeVisible();
}
