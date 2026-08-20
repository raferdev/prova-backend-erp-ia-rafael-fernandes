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

from app.core.database import SessionLocal
from app.repositories.alerta import AlertaRepository
from app.repositories.movimento import MovimentoRepository
from app.repositories.produto import ProdutoRepository
from app.services.estoque import EstoqueService

logger = logging.getLogger(__name__)


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


async def verificar_estoque_baixo(ctx: dict[str, Any]) -> dict[str, int]:
    """Varredura completa do catalogo. E a rede de seguranca do caminho por evento."""
    async with SessionLocal() as session:
        servico = EstoqueService(
            ProdutoRepository(session),
            AlertaRepository(session),
            MovimentoRepository(session),
            ctx["redis_cache"],
        )
        return await servico.verificar_catalogo()
