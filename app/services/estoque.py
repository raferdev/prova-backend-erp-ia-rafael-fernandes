"""Regra de negocio de movimentacao de estoque e alerta. Implementa o ADR 0008.

Este service e o unico ponto do projeto chamado tanto pela API quanto pelo worker. E por
isso que a invalidacao de cache mora em `core/cache.py` e e disparada aqui, e nao no
router: o worker escreve no `produto` sem passar por HTTP nenhum.
"""

import logging
import uuid

from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError

from app.core import cache
from app.models.produto import Produto
from app.repositories.alerta import AlertaRepository
from app.repositories.movimento import MovimentoRepository
from app.repositories.produto import ProdutoRepository
from app.schemas.produto import ProdutoResponse

logger = logging.getLogger(__name__)


class EstoqueInsuficiente(Exception):
    """Baixa maior que o saldo. O router traduz para 409."""


class ProdutoInexistente(Exception):
    """Movimentacao pedida para um id que nao existe."""


class EstoqueService:
    def __init__(
        self,
        produtos: ProdutoRepository,
        alertas: AlertaRepository,
        movimentos: MovimentoRepository,
        redis: Redis,
    ) -> None:
        self.produtos = produtos
        self.alertas = alertas
        self.movimentos = movimentos
        self.redis = redis

    async def ajustar(
        self,
        produto_id: uuid.UUID,
        delta: int,
        motivo: str,
        referencia: str | None = None,
    ) -> ProdutoResponse:
        """Movimenta o saldo, registra o movimento e invalida o cache do produto.

        `delta` negativo e baixa, positivo e reposicao.

        `referencia` e a chave de idempotencia, e na pratica e o id do job do arq. Fila
        entrega pelo menos uma vez: se o worker commitar a baixa e morrer antes de
        confirmar o job, a reentrega aplicaria o delta de novo. Com a referencia, a
        segunda execucao percebe que ja aplicou e devolve o saldo atual sem mexer nele.

        Sem referencia (chamada direta, sem fila) o comportamento e o de sempre: aplica.
        """
        if referencia and await self.movimentos.ja_registrado(referencia):
            logger.info("movimento %s ja aplicado, ignorando reentrega", referencia)
            produto_atual = await self.produtos.buscar_por_id(produto_id)
            if produto_atual is None:
                raise ProdutoInexistente(str(produto_id))
            return ProdutoResponse.model_validate(produto_atual)

        try:
            produto = await self.produtos.ajustar_estoque(produto_id, delta)
        except IntegrityError as erro:
            # A CheckConstraint de estoque nao negativo abortou a transacao. Isso e o
            # comportamento correto: melhor falhar a baixa do que registrar saldo negativo.
            await self.produtos.session.rollback()
            raise EstoqueInsuficiente(str(produto_id)) from erro

        if produto is None:
            raise ProdutoInexistente(str(produto_id))

        if referencia:
            await self.movimentos.registrar(
                produto_id=produto_id,
                referencia=referencia,
                delta=delta,
                saldo_apos=produto.quantidade_estoque,
                motivo=motivo,
            )

        await cache.invalidar_produto(self.redis, produto_id)
        logger.info(
            "estoque ajustado: produto=%s delta=%+d saldo=%d motivo=%s",
            produto_id,
            delta,
            produto.quantidade_estoque,
            motivo,
        )
        return ProdutoResponse.model_validate(produto)

    async def verificar_produto(self, produto: Produto) -> str:
        """Abre ou resolve o alerta de um produto. Devolve o que aconteceu.

        Idempotente: abrir duas vezes o mesmo alerta e um no-op garantido pelo indice
        unico parcial, nao por checagem previa em Python (que seria uma corrida).
        """
        if produto.quantidade_estoque <= produto.estoque_minimo:
            abriu = await self.alertas.abrir_se_nao_houver(produto)
            return "aberto" if abriu else "ja_estava_aberto"

        resolvidos = await self.alertas.resolver_abertos(produto.id)
        return "resolvido" if resolvidos else "sem_alteracao"

    async def verificar_catalogo(self) -> dict[str, int]:
        """Varredura completa: a rede de seguranca do caminho por evento.

        Pega o que o evento perdeu -- worker fora do ar, dado alterado direto no banco, ou
        `estoque_minimo` editado sem o estoque mudar (esse ultimo nao dispara movimentacao
        nenhuma e passaria despercebido para sempre).
        """
        resumo = {"abertos": 0, "resolvidos": 0, "ja_abertos": 0}

        for produto in await self.produtos.listar_com_estoque_baixo():
            if await self.alertas.abrir_se_nao_houver(produto):
                resumo["abertos"] += 1
            else:
                resumo["ja_abertos"] += 1

        for produto in await self.produtos.listar_com_estoque_saudavel():
            resumo["resolvidos"] += await self.alertas.resolver_abertos(produto.id)

        logger.info("varredura de estoque concluida: %s", resumo)
        return resumo
