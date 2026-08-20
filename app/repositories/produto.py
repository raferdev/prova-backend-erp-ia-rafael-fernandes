"""Acesso a dados de produto. Unico lugar do projeto que monta SQL de produto.

Sigo SQL-first: filtro, contagem e paginacao acontecem no Postgres. Trazer as linhas e
filtrar em laco Python funciona com dados de teste e derrete com catalogo real.
"""

import uuid
from typing import Any

from sqlalchemy import Select, func, select, update
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

    async def ajustar_estoque(self, produto_id: uuid.UUID, delta: int) -> Produto | None:
        """Soma `delta` ao saldo em um UPDATE atomico. Devolve o produto ja atualizado.

        Deliberadamente NAO faco ler-somar-gravar. Com dois workers concorrentes, os dois
        leriam 10, os dois gravariam 9, e duas baixas virariam uma -- perda de atualizacao
        silenciosa, o pior tipo. Aqui quem resolve o conflito e o proprio Postgres.

        Saldo negativo nao e tratado aqui: a CheckConstraint `produto_estoque_nao_negativo`
        faz a transacao falhar, e o service traduz isso para erro de dominio. Deixar a
        garantia no banco cobre tambem quem escrever por fora desta funcao.
        """
        comando = (
            update(Produto)
            .where(Produto.id == produto_id)
            .values(quantidade_estoque=Produto.quantidade_estoque + delta)
            .returning(Produto)
        )
        resultado = await self.session.execute(comando)
        produto = resultado.scalar_one_or_none()
        if produto is None:
            await self.session.rollback()
            return None
        await self.session.commit()
        return produto

    async def listar_com_estoque_baixo(self, limite: int = 500) -> list[Produto]:
        """Produtos em que o saldo caiu ate o limiar do proprio produto.

        Usada pela varredura periodica. Com catalogo grande isto vira varredura paginada
        ou incremental por `atualizado_em`; no escopo atual, uma query so resolve.
        """
        consulta = (
            select(Produto)
            .where(
                Produto.ativo.is_(True),
                Produto.quantidade_estoque <= Produto.estoque_minimo,
            )
            .order_by(Produto.nome)
            .limit(limite)
        )
        resultado = await self.session.execute(consulta)
        return list(resultado.scalars().all())

    async def listar_com_estoque_saudavel(self, limite: int = 500) -> list[Produto]:
        """O complemento: usada para resolver alertas de produtos que se recuperaram."""
        consulta = (
            select(Produto).where(Produto.quantidade_estoque > Produto.estoque_minimo).limit(limite)
        )
        resultado = await self.session.execute(consulta)
        return list(resultado.scalars().all())
