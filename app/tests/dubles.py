"""Dubles usados nos testes de unidade.

A existencia deste arquivo e o argumento pratico a favor da camada `repositories/`
(ADR 0001): da para exercitar a regra de negocio e a politica de cache inteira sem
Postgres e sem Redis no ar.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from redis.exceptions import RedisError

from app.models.produto import Produto
from app.schemas.filtros import FiltrosProduto, Paginacao


class FakeRedis:
    """Redis em memoria, com o mesmo contrato que `app.core.cache` usa.

    `incr` replica o comportamento real: numa chave inexistente, cria valendo 1.
    """

    def __init__(self) -> None:
        self.dados: dict[str, str] = {}
        self.indisponivel = False

    def _checa(self) -> None:
        if self.indisponivel:
            raise RedisError("redis fora do ar (simulado)")

    async def get(self, chave: str) -> str | None:
        self._checa()
        return self.dados.get(chave)

    async def set(self, chave: str, valor: str, ex: int | None = None) -> None:
        self._checa()
        self.dados[chave] = valor

    async def incr(self, chave: str) -> int:
        self._checa()
        novo = int(self.dados.get(chave, 0)) + 1
        self.dados[chave] = str(novo)
        return novo

    async def delete(self, *chaves: str) -> None:
        self._checa()
        for chave in chaves:
            self.dados.pop(chave, None)

    def chaves_de_listagem(self) -> list[str]:
        return [c for c in self.dados if ":list:" in c]


def produto_falso(**sobrescritas: Any) -> Produto:
    agora = datetime.now(UTC)
    padrao: dict[str, Any] = {
        "id": uuid.uuid4(),
        "nome": "Cabo HDMI 2m",
        "descricao": "Cabo HDMI 2.1",
        "preco": Decimal("39.90"),
        "quantidade_estoque": 10,
        "estoque_minimo": 2,
        "ativo": True,
        "criado_em": agora,
        "atualizado_em": agora,
    }
    return Produto(**{**padrao, **sobrescritas})


class RepositorioEspiao:
    """Repository dublado que conta quantas vezes cada metodo foi chamado.

    A contagem e o que permite afirmar "duas leituras iguais viraram uma consulta so",
    que e a assercao 1 do ADR 0007.
    """

    def __init__(self, produtos: list[Produto] | None = None) -> None:
        self.produtos = produtos if produtos is not None else [produto_falso()]
        self.chamadas_listar = 0
        self.chamadas_buscar = 0

    async def listar(
        self, filtros: FiltrosProduto, paginacao: Paginacao
    ) -> tuple[list[Produto], int]:
        self.chamadas_listar += 1
        return self.produtos, len(self.produtos)

    async def buscar_por_id(self, produto_id: uuid.UUID) -> Produto | None:
        self.chamadas_buscar += 1
        return next((p for p in self.produtos if p.id == produto_id), None)

    async def criar(self, dados: dict[str, Any]) -> Produto:
        produto = produto_falso(**dados)
        self.produtos.append(produto)
        return produto

    async def atualizar(self, produto: Produto, dados: dict[str, Any]) -> Produto:
        for campo, valor in dados.items():
            setattr(produto, campo, valor)
        return produto

    async def remover(self, produto: Produto) -> None:
        self.produtos = [p for p in self.produtos if p.id != produto.id]
