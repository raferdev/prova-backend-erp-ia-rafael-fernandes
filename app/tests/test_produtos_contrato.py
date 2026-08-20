"""Contrato HTTP da listagem de produtos.

Este arquivo existe por causa de um bug que passou despercebido: declarar dois modelos
Pydantic como `Query()` no mesmo endpoint faz o FastAPI parar de expandi-los em parametros
individuais e passar a exigir dois query params chamados `filtros` e `paginacao`. Nao ha
erro no boot nem no lint -- so um contrato errado.

O teste olha o schema OpenAPI, que e o contrato publicado, e nao a assinatura da funcao.
"""

from main import app

PARAMETROS_ESPERADOS = {
    "nome",
    "preco_min",
    "preco_max",
    "apenas_estoque_baixo",
    "estoque_min",
    "estoque_max",
    "ativo",
    "pagina",
    "tamanho",
}


def parametros_da_listagem() -> set[str]:
    operacao = app.openapi()["paths"]["/produtos"]["get"]
    return {p["name"] for p in operacao.get("parameters", [])}


def test_filtros_e_paginacao_viram_query_params_individuais():
    assert parametros_da_listagem() == PARAMETROS_ESPERADOS


def test_listagem_nao_expoe_parametros_agregados():
    """Se `filtros` ou `paginacao` aparecerem como nome de query param, a expansao quebrou."""
    assert not {"filtros", "paginacao", "consulta"} & parametros_da_listagem()


def test_listagem_nao_pede_corpo_de_requisicao():
    """Modelo Pydantic sem `Query()` viraria request body num GET."""
    assert "requestBody" not in app.openapi()["paths"]["/produtos"]["get"]
