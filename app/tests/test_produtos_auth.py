"""Protecao das rotas de produto.

A autenticacao esta declarada no router inteiro, entao basta um teste por verbo para
garantir que ninguem nasceu desprotegido. Estes testes nao precisam de banco: o
OAuth2PasswordBearer rejeita antes de qualquer consulta.
"""

import uuid

import pytest
from httpx import AsyncClient

ID = uuid.uuid4()


@pytest.mark.parametrize(
    ("metodo", "caminho"),
    [
        ("get", "/produtos"),
        ("post", "/produtos"),
        ("get", f"/produtos/{ID}"),
        ("patch", f"/produtos/{ID}"),
        ("delete", f"/produtos/{ID}"),
    ],
)
async def test_rota_exige_token(client: AsyncClient, metodo: str, caminho: str) -> None:
    resposta = await getattr(client, metodo)(caminho)

    assert resposta.status_code == 401


async def test_token_invalido_e_rejeitado(client: AsyncClient) -> None:
    resposta = await client.get("/produtos", headers={"Authorization": "Bearer isto-nao-e-um-jwt"})

    assert resposta.status_code == 401
