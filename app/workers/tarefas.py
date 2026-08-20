"""Tarefas de background. Implementa as duas tarefas decididas no ADR 0008.

Cada tarefa abre a propria sessao de banco. Sessao do SQLAlchemy nao e segura para
compartilhar entre jobs concorrentes, e um job pode rodar minutos depois do anterior --
reaproveitar sessao daria conexao morta.

O cliente Redis, ao contrario, vem do `ctx`: ele e criado uma vez no startup do worker e
reaproveitado. Abrir e fechar conexao a cada job desperdicaria handshake e, pior, fechar um
pool compartilhado derrubaria os jobs vizinhos.

As tarefas montam o mesmo `EstoqueService` que a API usa. Se a regra fosse reescrita aqui,
worker e API divergiriam, e divergencia de regra aparece como bug de dado -- o mais caro
de diagnosticar.
"""

import logging
import uuid
from typing import Any

from sqlalchemy.exc import ProgrammingError

from app.core.database import SessionLocal
from app.repositories.alerta import AlertaRepository
from app.repositories.movimento import MovimentoRepository
from app.repositories.produto import ProdutoRepository
from app.services.estoque import EstoqueService

logger = logging.getLogger(__name__)

# 42P01 = undefined_table no Postgres.
TABELA_INEXISTENTE = "42P01"


async def ajustar_estoque(
    ctx: dict[str, Any],
    produto_id: str,
    delta: int,
    motivo: str = "ajuste manual",
) -> dict[str, Any]:
    """Movimenta o saldo, invalida o cache e verifica o alerta do produto.

    A verificacao acontece dentro da mesma tarefa em vez de virar job novo: sao duas
    operacoes sobre o mesmo produto, e separa-las abriria uma janela em que o saldo mudou
    mas o alerta ainda reflete o valor antigo.
    """
    identificador = uuid.UUID(produto_id)

    # O id do job vira chave de idempotencia. Numa reentrega (fila entrega pelo menos uma
    # vez) o job_id e o mesmo, entao o service reconhece que ja aplicou e nao duplica a
    # movimentacao. Sem isto, `max_tries = 3` poderia baixar o estoque tres vezes.
    referencia = f"job:{ctx['job_id']}"

    async with SessionLocal() as session:
        produtos = ProdutoRepository(session)
        servico = EstoqueService(
            produtos,
            AlertaRepository(session),
            MovimentoRepository(session),
            ctx["redis_cache"],
        )

        produto = await servico.ajustar(identificador, delta, motivo, referencia=referencia)

        modelo = await produtos.buscar_por_id(identificador)
        situacao = await servico.verificar_produto(modelo) if modelo else "produto_removido"

    return {
        "produto_id": produto_id,
        "saldo": produto.quantidade_estoque,
        "alerta": situacao,
    }


async def verificar_estoque_baixo(ctx: dict[str, Any]) -> dict[str, Any]:
    """Varredura completa do catalogo. E a rede de seguranca do caminho por evento.

    Tolera o schema ainda nao migrado. Isso nao e hipotese: num clone novo, seguindo o
    README, o `docker compose up` sobe o worker antes de alguem rodar `alembic upgrade
    head`, e a varredura de startup batia numa tabela inexistente. A tarefa se recuperava
    sozinha no ciclo seguinte, mas cuspia um traceback como primeira coisa que a pessoa via.

    Trato so o 42P01 (tabela inexistente), e nao qualquer ProgrammingError: SQL quebrado
    tem que continuar estourando alto.
    """
    try:
        return await _varrer(ctx)
    except ProgrammingError as erro:
        if getattr(erro.orig, "sqlstate", None) != TABELA_INEXISTENTE:
            raise
        logger.warning(
            "schema ainda nao migrado; a varredura tenta de novo no proximo ciclo. "
            "Rode: docker compose exec api alembic upgrade head"
        )
        return {"abertos": 0, "resolvidos": 0, "ja_abertos": 0, "adiado": True}


async def _varrer(ctx: dict[str, Any]) -> dict[str, int]:
    async with SessionLocal() as session:
        servico = EstoqueService(
            ProdutoRepository(session),
            AlertaRepository(session),
            MovimentoRepository(session),
            ctx["redis_cache"],
        )
        return await servico.verificar_catalogo()
