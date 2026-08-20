"""Acesso a dados de produto. Unico lugar do projeto que monta SQL de produto.

Sigo SQL-first: filtro, contagem e paginacao acontecem no Postgres. Trazer as linhas e
filtrar em laco Python funciona com dados de teste e derrete com catalogo real.
"""

import uuid
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.produto import Produto
from app.schemas.filtros import FiltrosProduto, Paginacao


class ProdutoRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _aplicar_filtros(self, consulta: Select, filtros: FiltrosProduto) -> Select:
        if filtros.nome:
            # ilike com % dos dois lados: busca parcial sem diferenciar maiusculas.
            consulta = consulta.where(Produto.nome.ilike(f"%{filtros.nome}%"))
        if filtros.preco_min is not None:
            consulta = consulta.where(Produto.preco >= filtros.preco_min)
        if filtros.preco_max is not None:
            consulta = consulta.where(Produto.preco <= filtros.preco_max)
        if filtros.apenas_estoque_baixo:
            # Comparacao entre colunas: o limiar e por produto, nao um numero fixo.
            consulta = consulta.where(Produto.quantidade_estoque <= Produto.estoque_minimo)
        if filtros.ativo is not None:
            consulta = consulta.where(Produto.ativo.is_(filtros.ativo))
        return consulta

    async def listar(
        self, filtros: FiltrosProduto, paginacao: Paginacao
    ) -> tuple[list[Produto], int]:
        """Devolve a pagina e o total que atende aos filtros.

        O total sai de um COUNT separado sobre os mesmos filtros, sem LIMIT. Contar o
        tamanho da lista paginada daria sempre no maximo `tamanho`, o que quebraria o
        calculo de numero de paginas.
        """
        base = self._aplicar_filtros(select(Produto), filtros)

        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))

        consulta = base.order_by(Produto.nome).limit(paginacao.tamanho).offset(paginacao.offset)
        resultado = await self.session.execute(consulta)

        return list(resultado.scalars().all()), int(total or 0)

    async def buscar_por_id(self, produto_id: uuid.UUID) -> Produto | None:
        return await self.session.get(Produto, produto_id)

    async def criar(self, dados: dict[str, Any]) -> Produto:
        produto = Produto(**dados)
        self.session.add(produto)
        await self.session.commit()
        # refresh para trazer o que o banco preencheu (criado_em, atualizado_em).
        await self.session.refresh(produto)
        return produto

    async def atualizar(self, produto: Produto, dados: dict[str, Any]) -> Produto:
        for campo, valor in dados.items():
            setattr(produto, campo, valor)
        await self.session.commit()
        await self.session.refresh(produto)
        return produto

    async def remover(self, produto: Produto) -> None:
        await self.session.delete(produto)
        await self.session.commit()
