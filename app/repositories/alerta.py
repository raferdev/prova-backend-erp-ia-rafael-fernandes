"""Acesso a dados dos alertas de estoque.

A idempotencia mora aqui, e ela e do banco: `ON CONFLICT DO NOTHING` sobre o indice unico
parcial. Checar "ja existe alerta aberto?" em Python antes de inserir seria uma corrida --
dois workers checariam ao mesmo tempo, os dois veriam que nao existe e os dois inseririam.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alerta import AlertaEstoque, StatusAlerta
from app.models.produto import Produto


class AlertaRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def abrir_se_nao_houver(self, produto: Produto) -> bool:
        """Abre alerta para o produto. Devolve True se abriu, False se ja havia um aberto.

        `index_where` precisa reproduzir o predicado do indice parcial *literalmente*.
        Passar a expressao do ORM (`AlertaEstoque.status == StatusAlerta.ABERTO`) parece
        equivalente e nao e: ela renderiza como bind parameter (`status = $1`), e o
        Postgres so casa o ON CONFLICT com um indice parcial quando consegue provar que os
        predicados sao os mesmos -- o que ele nao faz com valor que so existe em tempo de
        execucao. O erro e `there is no unique or exclusion constraint matching the ON
        CONFLICT specification`, que nao diz nada sobre a causa.
        """
        comando = (
            insert(AlertaEstoque)
            .values(
                produto_id=produto.id,
                status=StatusAlerta.ABERTO,
                quantidade_no_alerta=produto.quantidade_estoque,
                estoque_minimo_no_alerta=produto.estoque_minimo,
            )
            .on_conflict_do_nothing(
                index_elements=["produto_id"],
                index_where=text("status = 'aberto'"),
            )
        )
        resultado = await self.session.execute(comando)
        await self.session.commit()
        return resultado.rowcount > 0

    async def resolver_abertos(self, produto_id: uuid.UUID) -> int:
        """Marca como resolvido em vez de apagar: o historico e o motivo da tabela existir."""
        comando = (
            update(AlertaEstoque)
            .where(
                AlertaEstoque.produto_id == produto_id,
                AlertaEstoque.status == StatusAlerta.ABERTO,
            )
            .values(status=StatusAlerta.RESOLVIDO, resolvido_em=datetime.now(UTC))
        )
        resultado = await self.session.execute(comando)
        await self.session.commit()
        return resultado.rowcount

    async def listar(self, apenas_abertos: bool = True, limite: int = 100) -> list[AlertaEstoque]:
        consulta = select(AlertaEstoque).order_by(AlertaEstoque.criado_em.desc()).limit(limite)
        if apenas_abertos:
            consulta = consulta.where(AlertaEstoque.status == StatusAlerta.ABERTO)
        resultado = await self.session.execute(consulta)
        return list(resultado.scalars().all())

    async def listar_por_produto(self, produto_id: uuid.UUID) -> list[AlertaEstoque]:
        """Historico completo de um produto, aberto e resolvido."""
        resultado = await self.session.execute(
            select(AlertaEstoque)
            .where(AlertaEstoque.produto_id == produto_id)
            .order_by(AlertaEstoque.criado_em)
        )
        return list(resultado.scalars().all())

    async def contar_abertos(self) -> int:
        total = await self.session.scalar(
            select(func.count())
            .select_from(AlertaEstoque)
            .where(AlertaEstoque.status == StatusAlerta.ABERTO)
        )
        return int(total or 0)
