"""Regra de negocio de produto, incluindo a politica de cache do ADR 0007.

O service recebe o repository e o cliente Redis por construtor. E isso que permite testar
a regra com um repository dublado, sem Postgres no ar -- a inversao de dependencia que
justifica manter a camada `repositories/` (ADR 0001).

Quem decide o que pode ser cacheado e este arquivo, nao o router: o worker de estoque
tambem passa por aqui e tambem precisa invalidar.
"""

import uuid

from redis.asyncio import Redis

from app.core import cache
from app.models.produto import Produto
from app.repositories.produto import ProdutoRepository
from app.schemas.filtros import FiltrosProduto, Paginacao
from app.schemas.produto import PaginaProdutos, ProdutoCreate, ProdutoResponse, ProdutoUpdate


class ProdutoNaoEncontrado(Exception):
    """Erro de dominio. O router traduz para 404; o service nao conhece HTTP."""


class ProdutoService:
    def __init__(self, repository: ProdutoRepository, redis: Redis) -> None:
        self.repository = repository
        self.redis = redis

    async def listar(self, filtros: FiltrosProduto, paginacao: Paginacao) -> PaginaProdutos:
        cacheavel = not filtros.toca_estoque()

        criterios = {
            **filtros.model_dump(mode="json"),
            "pagina": paginacao.pagina,
            "tamanho": paginacao.tamanho,
        }
        chave = await cache.chave_listagem(self.redis, criterios) if cacheavel else None

        if chave:
            guardado = await cache.ler_json(self.redis, chave)
            if guardado is not None:
                return PaginaProdutos.model_validate(guardado)

        itens, total = await self.repository.listar(filtros, paginacao)
        pagina = PaginaProdutos(
            itens=[ProdutoResponse.model_validate(item) for item in itens],
            total=total,
            pagina=paginacao.pagina,
            tamanho=paginacao.tamanho,
            paginas=(total + paginacao.tamanho - 1) // paginacao.tamanho,
        )

        if chave:
            await cache.gravar_json(self.redis, chave, pagina.model_dump(mode="json"))

        return pagina

    async def buscar(self, produto_id: uuid.UUID) -> ProdutoResponse:
        chave = cache.chave_detalhe(produto_id)

        guardado = await cache.ler_json(self.redis, chave)
        if guardado is not None:
            return ProdutoResponse.model_validate(guardado)

        produto = await self._obrigatorio(produto_id)
        resposta = ProdutoResponse.model_validate(produto)

        # Nao gravo cache negativo (404). Isso deixa a porta aberta para cache penetration
        # se alguem varrer ids inexistentes, mas com UUID o risco e baixo e evita ter que
        # invalidar "nao existe" no momento da criacao. Registrado no ADR 0007.
        await cache.gravar_json(self.redis, chave, resposta.model_dump(mode="json"))
        return resposta

    async def criar(self, dados: ProdutoCreate) -> ProdutoResponse:
        produto = await self.repository.criar(dados.model_dump())
        # Produto novo nao tem detalhe em cache para apagar, mas muda as listagens.
        await cache.invalidar_listagens(self.redis)
        return ProdutoResponse.model_validate(produto)

    async def atualizar(self, produto_id: uuid.UUID, dados: ProdutoUpdate) -> ProdutoResponse:
        produto = await self._obrigatorio(produto_id)

        # exclude_unset distingue "campo ausente" de "campo enviado como null". Sem isso
        # um PATCH com um campo so zeraria todo o resto do produto.
        alteracoes = dados.model_dump(exclude_unset=True)
        if alteracoes:
            produto = await self.repository.atualizar(produto, alteracoes)

        # Invalidacao depois do commit, nunca antes: se eu invalidasse primeiro, uma
        # leitura concorrente poderia repovoar o cache com o valor antigo antes do commit.
        await cache.invalidar_produto(self.redis, produto_id)
        return ProdutoResponse.model_validate(produto)

    async def remover(self, produto_id: uuid.UUID) -> None:
        produto = await self._obrigatorio(produto_id)
        await self.repository.remover(produto)
        await cache.invalidar_produto(self.redis, produto_id)

    async def _obrigatorio(self, produto_id: uuid.UUID) -> Produto:
        produto = await self.repository.buscar_por_id(produto_id)
        if produto is None:
            raise ProdutoNaoEncontrado(str(produto_id))
        return produto
