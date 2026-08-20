/**
 * Cliente da API do ERP.
 *
 * Todas as chamadas são relativas a `/api`, resolvidas por proxy (Vite no dev, nginx no
 * Compose). O front nunca sabe o endereço real da API, então mudar de ambiente não exige
 * rebuild.
 */

export type Produto = {
  id: string;
  nome: string;
  descricao: string | null;
  preco: string;
  quantidade_estoque: number;
  estoque_minimo: number;
  ativo: boolean;
};

export type Pagina = {
  itens: Produto[];
  total: number;
  pagina: number;
  tamanho: number;
  paginas: number;
};

export type RespostaConsulta = {
  pergunta: string;
  entendida: boolean;
  interpretacao: string | null;
  filtros_aplicados: Record<string, unknown> | null;
  total: number | null;
  itens: Produto[] | null;
  ambiguidade: string | null;
  motivo: string | null;
  sugestoes: string[];
};

export type Alerta = {
  id: string;
  produto_id: string;
  status: string;
  quantidade_no_alerta: number;
  estoque_minimo_no_alerta: number;
  criado_em: string;
};

export class ErroApi extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

const CHAVE_TOKEN = "erp.token";

export const sessao = {
  token: () => localStorage.getItem(CHAVE_TOKEN),
  guardar: (token: string) => localStorage.setItem(CHAVE_TOKEN, token),
  encerrar: () => localStorage.removeItem(CHAVE_TOKEN),
};

async function requisitar<T>(caminho: string, init: RequestInit = {}): Promise<T> {
  const token = sessao.token();
  const resposta = await fetch(`/api${caminho}`, {
    ...init,
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });

  // 401 aqui é token expirado ou inválido. Limpo a sessão para a aplicação voltar ao login
  // em vez de ficar num limbo em que a tela existe e nenhuma chamada funciona.
  if (resposta.status === 401) {
    sessao.encerrar();
    throw new ErroApi("Sessão expirada. Entre novamente.", 401);
  }

  if (!resposta.ok) {
    const detalhe = await resposta.json().catch(() => null);
    throw new ErroApi(detalhe?.detail ?? `Erro ${resposta.status}`, resposta.status);
  }

  return resposta.json() as Promise<T>;
}

export async function autenticar(email: string, senha: string): Promise<string> {
  // O endpoint espera form-urlencoded, e não JSON: é o formato do OAuth2PasswordRequestForm,
  // que também é o que faz o botão "Authorize" do /docs funcionar.
  const corpo = new URLSearchParams({ username: email, password: senha });

  const resposta = await fetch("/api/auth/token", { method: "POST", body: corpo });
  if (!resposta.ok) {
    throw new ErroApi("E-mail ou senha inválidos.", resposta.status);
  }

  const { access_token } = (await resposta.json()) as { access_token: string };
  sessao.guardar(access_token);
  return access_token;
}

export type FiltrosProduto = {
  nome?: string;
  preco_max?: string;
  apenas_estoque_baixo?: boolean;
  pagina?: number;
  tamanho?: number;
};

export function listarProdutos(filtros: FiltrosProduto = {}): Promise<Pagina> {
  const busca = new URLSearchParams();
  for (const [chave, valor] of Object.entries(filtros)) {
    if (valor !== undefined && valor !== "" && valor !== false) {
      busca.set(chave, String(valor));
    }
  }
  return requisitar<Pagina>(`/produtos?${busca}`);
}

export function perguntar(pergunta: string): Promise<RespostaConsulta> {
  return requisitar<RespostaConsulta>("/consultas/produtos", {
    method: "POST",
    body: JSON.stringify({ pergunta }),
  });
}

export function listarAlertas(): Promise<Alerta[]> {
  return requisitar<Alerta[]>("/alertas?apenas_abertos=true");
}
