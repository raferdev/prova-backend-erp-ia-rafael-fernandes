"""Testes do worker de estoque. Cobre as asserções listadas no ADR 0008.

A asserção 7 (os quatro containers sobem e o worker consome da fila) não cabe aqui:
é verificada com o Compose de pé, e a saída está registrada no ADR.
"""

import uuid

import pytest

from app.core import cache
from app.services.estoque import EstoqueInsuficiente, EstoqueService, ProdutoInexistente
from app.tests.dubles import (
    AlertaRepositorioFalso,
    FakeRedis,
    MovimentoRepositorioFalso,
    RepositorioEspiao,
    produto_falso,
)


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def produto():
    return produto_falso(quantidade_estoque=10, estoque_minimo=3)


@pytest.fixture
def produtos(produto) -> RepositorioEspiao:
    return RepositorioEspiao([produto])


@pytest.fixture
def alertas() -> AlertaRepositorioFalso:
    return AlertaRepositorioFalso()


@pytest.fixture
def movimentos() -> MovimentoRepositorioFalso:
    return MovimentoRepositorioFalso()


@pytest.fixture
def servico(produtos, alertas, movimentos, redis) -> EstoqueService:
    return EstoqueService(produtos, alertas, movimentos, redis)


async def test_ajuste_invalida_o_cache_do_produto(servico, produto, redis):
    """Asserção 1: o worker escreve e o cache do produto cai, sem passar por router."""
    chave = cache.chave_detalhe(produto.id)
    await redis.set(chave, '{"preco": "39.90"}')

    await servico.ajustar(produto.id, -2, "venda")

    assert chave not in redis.dados
    assert await redis.get(cache.CHAVE_VERSAO) == "1"


async def test_baixa_abaixo_do_minimo_abre_um_alerta(servico, produto, alertas):
    """Asserção 2."""
    await servico.ajustar(produto.id, -8, "venda")
    assert produto.quantidade_estoque == 2

    await servico.verificar_produto(produto)

    assert len(alertas.abertos(produto.id)) == 1


async def test_verificar_tres_vezes_mantem_um_alerta_so(servico, produto, alertas):
    """Asserção 3: idempotência. É o índice único parcial que garante isso no banco."""
    await servico.ajustar(produto.id, -8, "venda")

    for _ in range(3):
        await servico.verificar_produto(produto)

    assert len(alertas.abertos(produto.id)) == 1


async def test_reposicao_resolve_o_alerta_sem_apagar(servico, produto, alertas):
    """Asserção 4: resolve preservando o histórico."""
    await servico.ajustar(produto.id, -8, "venda")
    await servico.verificar_produto(produto)

    await servico.ajustar(produto.id, 20, "reposicao")
    situacao = await servico.verificar_produto(produto)

    assert situacao == "resolvido"
    assert alertas.abertos(produto.id) == []
    # O alerta continua existindo, agora resolvido: apagar destruiria a auditoria.
    assert len(alertas.alertas) == 1
    assert alertas.alertas[0]["status"] == "resolvido"
    assert alertas.alertas[0]["resolvido_em"] is not None


async def test_reentrega_do_mesmo_job_nao_aplica_o_delta_duas_vezes(servico, produto, movimentos):
    """Asserção 5, parte que mais me preocupava.

    Fila entrega pelo menos uma vez. Se o worker commitar a baixa e morrer antes de
    confirmar o job, o arq reentrega com o mesmo job_id. Sem a chave de idempotência,
    `max_tries = 3` poderia baixar o mesmo estoque três vezes.
    """
    referencia = "job:abc123"

    await servico.ajustar(produto.id, -4, "venda", referencia=referencia)
    assert produto.quantidade_estoque == 6

    await servico.ajustar(produto.id, -4, "venda", referencia=referencia)
    await servico.ajustar(produto.id, -4, "venda", referencia=referencia)

    assert produto.quantidade_estoque == 6
    assert len(movimentos.movimentos) == 1


async def test_referencias_diferentes_aplicam_normalmente(servico, produto, movimentos):
    """O contrário da anterior: idempotência não pode virar bloqueio de movimentação."""
    await servico.ajustar(produto.id, -1, "venda", referencia="job:1")
    await servico.ajustar(produto.id, -1, "venda", referencia="job:2")

    assert produto.quantidade_estoque == 8
    assert len(movimentos.movimentos) == 2


async def test_baixar_mais_do_que_existe_falha_sem_saldo_negativo(servico, produto, produtos):
    """Asserção 6: melhor falhar a baixa do que registrar saldo negativo."""
    with pytest.raises(EstoqueInsuficiente):
        await servico.ajustar(produto.id, -50, "venda")

    assert produto.quantidade_estoque == 10
    assert produtos.session.rollbacks == 1


async def test_ajuste_em_produto_inexistente_levanta_erro_de_dominio(servico):
    with pytest.raises(ProdutoInexistente):
        await servico.ajustar(uuid.uuid4(), -1, "venda")


async def test_varredura_abre_e_resolve_no_mesmo_passe(redis, alertas, movimentos):
    """A varredura é a rede de segurança do caminho por evento."""
    em_falta = produto_falso(nome="Em falta", quantidade_estoque=0, estoque_minimo=5)
    saudavel = produto_falso(nome="Saudavel", quantidade_estoque=50, estoque_minimo=5)
    produtos = RepositorioEspiao([em_falta, saudavel])
    servico = EstoqueService(produtos, alertas, movimentos, redis)

    primeiro = await servico.verificar_catalogo()
    assert primeiro["abertos"] == 1
    assert len(alertas.abertos(em_falta.id)) == 1

    segundo = await servico.verificar_catalogo()
    assert segundo["abertos"] == 0
    assert segundo["ja_abertos"] == 1

    em_falta.quantidade_estoque = 99
    terceiro = await servico.verificar_catalogo()
    assert terceiro["resolvidos"] == 1
    assert alertas.abertos() == []


async def test_varredura_pega_mudanca_de_estoque_minimo(redis, alertas, movimentos):
    """O caso que só a varredura pega.

    Editar o `estoque_minimo` sem mexer no estoque não gera movimentação nenhuma, então
    o caminho por evento nunca dispara. Sem a varredura, esse produto ficaria em falta
    para sempre sem alerta.
    """
    produto = produto_falso(quantidade_estoque=4, estoque_minimo=2)
    servico = EstoqueService(RepositorioEspiao([produto]), alertas, movimentos, redis)

    assert (await servico.verificar_catalogo())["abertos"] == 0

    produto.estoque_minimo = 10

    assert (await servico.verificar_catalogo())["abertos"] == 1
