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
from sqlalchemy.exc import IntegrityError

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


class SessaoFalsa:
    """Sessao minima: so o que o service usa no caminho de erro."""

    def __init__(self) -> None:
        self.rollbacks = 0

    async def rollback(self) -> None:
        self.rollbacks += 1


class RepositorioEspiao:
    """Repository dublado que conta quantas vezes cada metodo foi chamado.

    A contagem e o que permite afirmar "duas leituras iguais viraram uma consulta so",
    que e a assercao 1 do ADR 0007.
    """

    def __init__(self, produtos: list[Produto] | None = None) -> None:
        self.produtos = produtos if produtos is not None else [produto_falso()]
        self.chamadas_listar = 0
        self.chamadas_buscar = 0
        # O service chama `session.rollback()` ao traduzir IntegrityError para erro de
        # dominio. O dubl precisa oferecer a mesma superficie.
        self.session = SessaoFalsa()

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

    async def ajustar_estoque(self, produto_id: uuid.UUID, delta: int) -> Produto | None:
        produto = next((p for p in self.produtos if p.id == produto_id), None)
        if produto is None:
            return None
        novo = produto.quantidade_estoque + delta
        if novo < 0:
            # Reproduz o efeito da CheckConstraint `produto_estoque_nao_negativo`. O dubl
            # imita o banco; a garantia de verdade continua sendo do Postgres.
            raise IntegrityError("check constraint", None, Exception("estoque negativo"))
        produto.quantidade_estoque = novo
        return produto

    async def listar_com_estoque_baixo(self, limite: int = 500) -> list[Produto]:
        return [p for p in self.produtos if p.ativo and p.quantidade_estoque <= p.estoque_minimo]

    async def listar_com_estoque_saudavel(self, limite: int = 500) -> list[Produto]:
        return [p for p in self.produtos if p.quantidade_estoque > p.estoque_minimo]


class AlertaRepositorioFalso:
    """Alertas em memoria.

    Reproduz o invariante do indice unico parcial: no maximo um alerta `aberto` por
    produto. Vale dizer o que este dubl NAO prova -- que o Postgres realmente impede a
    corrida entre dois workers inserindo ao mesmo tempo. Essa garantia e do indice, e esta
    verificada separadamente contra o banco real.
    """

    def __init__(self) -> None:
        self.alertas: list[dict[str, Any]] = []

    def abertos(self, produto_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
        return [
            a
            for a in self.alertas
            if a["status"] == "aberto" and (produto_id is None or a["produto_id"] == produto_id)
        ]

    async def abrir_se_nao_houver(self, produto: Produto) -> bool:
        if self.abertos(produto.id):
            return False
        self.alertas.append(
            {
                "produto_id": produto.id,
                "status": "aberto",
                "quantidade_no_alerta": produto.quantidade_estoque,
                "estoque_minimo_no_alerta": produto.estoque_minimo,
                "resolvido_em": None,
            }
        )
        return True

    async def resolver_abertos(self, produto_id: uuid.UUID) -> int:
        alvos = self.abertos(produto_id)
        for alerta in alvos:
            alerta["status"] = "resolvido"
            alerta["resolvido_em"] = datetime.now(UTC)
        return len(alvos)


class MovimentoRepositorioFalso:
    """Livro de movimentacoes em memoria, com `referencia` unica."""

    def __init__(self) -> None:
        self.movimentos: list[dict[str, Any]] = []

    async def ja_registrado(self, referencia: str) -> bool:
        return any(m["referencia"] == referencia for m in self.movimentos)

    async def registrar(
        self,
        produto_id: uuid.UUID,
        referencia: str,
        delta: int,
        saldo_apos: int,
        motivo: str,
    ) -> dict[str, Any]:
        movimento = {
            "produto_id": produto_id,
            "referencia": referencia,
            "delta": delta,
            "saldo_apos": saldo_apos,
            "motivo": motivo,
        }
        self.movimentos.append(movimento)
        return movimento
