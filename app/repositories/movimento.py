"""Acesso ao livro de movimentacoes de estoque."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.movimento import MovimentoEstoque


class MovimentoRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ja_registrado(self, referencia: str) -> bool:
        existente = await self.session.scalar(
            select(MovimentoEstoque.id).where(MovimentoEstoque.referencia == referencia)
        )
        return existente is not None

    async def registrar(
        self,
        produto_id: uuid.UUID,
        referencia: str,
        delta: int,
        saldo_apos: int,
        motivo: str,
    ) -> MovimentoEstoque:
        movimento = MovimentoEstoque(
            produto_id=produto_id,
            referencia=referencia,
            delta=delta,
            saldo_apos=saldo_apos,
            motivo=motivo,
        )
        self.session.add(movimento)
        await self.session.commit()
        await self.session.refresh(movimento)
        return movimento

    async def historico(self, produto_id: uuid.UUID, limite: int = 50) -> list[MovimentoEstoque]:
        resultado = await self.session.execute(
            select(MovimentoEstoque)
            .where(MovimentoEstoque.produto_id == produto_id)
            .order_by(MovimentoEstoque.criado_em.desc())
            .limit(limite)
        )
        return list(resultado.scalars().all())
