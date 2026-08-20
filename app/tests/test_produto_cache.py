"""Testes da politica de cache do ADR 0007.

Cada teste aqui corresponde a uma das assercoes que listei no ADR antes de implementar.
Rodam sem Postgres e sem Redis: repository dublado e Redis em memoria.
"""

from decimal import Decimal

import pytest

from app.core import cache
from app.schemas.filtros import FiltrosProduto, Paginacao
from app.schemas.produto import ProdutoUpdate
from app.services.produto import ProdutoNaoEncontrado, ProdutoService
from app.tests.dubles import FakeRedis, RepositorioEspiao, produto_falso


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def repositorio() -> RepositorioEspiao:
    return RepositorioEspiao()


@pytest.fixture
def servico(repositorio: RepositorioEspiao, redis: FakeRedis) -> ProdutoService:
    return ProdutoService(repositorio, redis)


async def test_segunda_leitura_igual_nao_consulta_o_banco(servico, repositorio, redis):
    """Assercao 1: duas leituras iguais resultam em uma consulta so."""
    filtros, paginacao = FiltrosProduto(), Paginacao()

    primeira = await servico.listar(filtros, paginacao)
    segunda = await servico.listar(filtros, paginacao)

    assert repositorio.chamadas_listar == 1
    assert primeira.itens[0].id == segunda.itens[0].id


async def test_ordem_dos_filtros_nao_duplica_cache(servico, redis):
    """A normalizacao do fingerprint faz filtros equivalentes cairem na mesma chave."""
    paginacao = Paginacao()

    await servico.listar(FiltrosProduto(nome="cabo", preco_min=Decimal("1")), paginacao)
    await servico.listar(FiltrosProduto(preco_min=Decimal("1"), nome="cabo"), paginacao)

    assert len(redis.chaves_de_listagem()) == 1


async def test_atualizar_invalida_a_leitura_seguinte(servico, repositorio, redis):
    """Assercao 2: depois de um update, a leitura seguinte nao vem do cache antigo."""
    produto = repositorio.produtos[0]
    filtros, paginacao = FiltrosProduto(), Paginacao()

    await servico.listar(filtros, paginacao)
    assert repositorio.chamadas_listar == 1

    await servico.atualizar(produto.id, ProdutoUpdate(preco=Decimal("75.00")))

    await servico.listar(filtros, paginacao)
    assert repositorio.chamadas_listar == 2


async def test_incr_invalida_listagens_de_filtros_diferentes_de_uma_vez(
    servico, repositorio, redis
):
    """Assercao 3: um INCR derruba todas as listagens, sem varrer o keyspace."""
    paginacao = Paginacao()
    await servico.listar(FiltrosProduto(nome="cabo"), paginacao)
    await servico.listar(FiltrosProduto(nome="teclado"), paginacao)
    await servico.listar(FiltrosProduto(preco_max=Decimal("100")), paginacao)
    assert len(redis.chaves_de_listagem()) == 3
    assert repositorio.chamadas_listar == 3

    await cache.invalidar_listagens(redis)

    # As chaves antigas continuam existindo em memoria (somem por TTL), mas ficaram
    # inalcancaveis: o namespace mudou, entao toda leitura volta a bater no banco.
    await servico.listar(FiltrosProduto(nome="cabo"), paginacao)
    await servico.listar(FiltrosProduto(nome="teclado"), paginacao)
    assert repositorio.chamadas_listar == 5


async def test_filtro_de_estoque_baixo_nao_entra_em_cache(servico, repositorio, redis):
    """Assercao 4: consulta que depende de estoque nunca grava chave."""
    filtros = FiltrosProduto(apenas_estoque_baixo=True)
    paginacao = Paginacao()

    await servico.listar(filtros, paginacao)
    await servico.listar(filtros, paginacao)

    assert redis.chaves_de_listagem() == []
    assert repositorio.chamadas_listar == 2


async def test_invalidacao_do_worker_tem_o_mesmo_efeito(servico, repositorio, redis):
    """Assercao 5: o worker invalida chamando o mesmo modulo, sem passar por router."""
    produto = repositorio.produtos[0]
    filtros, paginacao = FiltrosProduto(), Paginacao()

    await servico.listar(filtros, paginacao)
    await servico.buscar(produto.id)
    assert repositorio.chamadas_listar == 1

    await cache.invalidar_produto(redis, produto.id)

    await servico.listar(filtros, paginacao)
    assert repositorio.chamadas_listar == 2
    assert cache.chave_detalhe(produto.id) not in redis.dados


async def test_aplicacao_continua_funcionando_com_redis_fora(servico, repositorio, redis):
    """Assercao 6: Redis indisponivel deixa a aplicacao lenta, nao quebrada."""
    redis.indisponivel = True
    filtros, paginacao = FiltrosProduto(), Paginacao()

    pagina = await servico.listar(filtros, paginacao)
    assert pagina.total == 1

    produto = repositorio.produtos[0]
    atualizado = await servico.atualizar(produto.id, ProdutoUpdate(preco=Decimal("10.00")))
    assert atualizado.preco == Decimal("10.00")

    assert repositorio.chamadas_listar == 1


async def test_buscar_produto_inexistente_levanta_erro_de_dominio(servico):
    import uuid

    with pytest.raises(ProdutoNaoEncontrado):
        await servico.buscar(uuid.uuid4())


async def test_criar_produto_invalida_listagens(servico, repositorio, redis):
    filtros, paginacao = FiltrosProduto(), Paginacao()
    await servico.listar(filtros, paginacao)

    from app.schemas.produto import ProdutoCreate

    await servico.criar(ProdutoCreate(nome="Item novo", preco=Decimal("5.00")))

    await servico.listar(filtros, paginacao)
    assert repositorio.chamadas_listar == 2


async def test_atualizacao_parcial_nao_zera_os_outros_campos(servico, repositorio):
    produto = repositorio.produtos[0]
    nome_original = produto.nome

    atualizado = await servico.atualizar(produto.id, ProdutoUpdate(preco=Decimal("99.00")))

    assert atualizado.preco == Decimal("99.00")
    assert atualizado.nome == nome_original
    assert atualizado.descricao is not None


def test_produto_falso_ajuda_a_ler_os_testes():
    assert produto_falso(nome="X").nome == "X"
