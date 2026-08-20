"""Testes do endpoint assíncrono (Parte 2).

O que estes testes tentam provar, em ordem de importância:

1. as três fontes realmente vão em paralelo, medido em milissegundos e não por inspeção;
2. uma fonte fora do ar não derruba as outras duas;
3. falha nunca é entregue como resultado vazio;
4. o retry existe e é limitado pelo orçamento total.
"""

import asyncio
import time

import pytest

from app.integracoes.base import consultar
from app.integracoes.mocks import (
    ClientesAPI,
    Comportamento,
    FinanceiroAPI,
    LogisticaAPI,
    ServicoIndisponivel,
)
from app.services.contexto import ContextoService


def montar_servico(**comportamentos: Comportamento) -> ContextoService:
    return ContextoService(
        clientes=ClientesAPI(
            nome="clientes", comportamento=comportamentos.get("clientes", Comportamento.NORMAL)
        ),
        financeiro=FinanceiroAPI(
            nome="financeiro",
            comportamento=comportamentos.get("financeiro", Comportamento.NORMAL),
        ),
        logistica=LogisticaAPI(
            nome="logistica", comportamento=comportamentos.get("logistica", Comportamento.NORMAL)
        ),
    )


async def test_caminho_feliz_traz_as_tres_fontes():
    contexto = await montar_servico().montar("cli-1")

    assert contexto.completo is True
    assert contexto.fontes_indisponiveis == []
    assert contexto.clientes.dados["nome"] == "Comercio Silva Ltda"
    assert contexto.financeiro.dados["limite_credito"] == "50000.00"
    assert contexto.logistica.dados["prazo_dias_uteis"] == 3


async def test_as_fontes_vao_em_paralelo_e_nao_em_sequencia():
    """A prova do desenho, em números.

    Cada mock dorme 300ms. Em sequência isso daria 900ms; em paralelo, pouco mais de 300.
    A folga de 250ms é para não deixar o teste instável em máquina carregada, e ainda
    assim fica muito abaixo do tempo sequencial.
    """
    servico = ContextoService(
        clientes=ClientesAPI(nome="clientes", latencia_normal=0.3),
        financeiro=FinanceiroAPI(nome="financeiro", latencia_normal=0.3),
        logistica=LogisticaAPI(nome="logistica", latencia_normal=0.3),
    )

    inicio = time.monotonic()
    contexto = await servico.montar("cli-1")
    decorrido = time.monotonic() - inicio

    assert contexto.completo is True
    assert decorrido < 0.55, f"levou {decorrido:.2f}s, parece sequencial"


async def test_fonte_fora_do_ar_nao_derruba_as_outras():
    contexto = await montar_servico(financeiro=Comportamento.FORA).montar("cli-1")

    assert contexto.completo is False
    assert contexto.fontes_indisponiveis == ["financeiro"]

    assert contexto.financeiro.status == "erro"
    assert contexto.clientes.status == "ok"
    assert contexto.logistica.status == "ok"
    assert contexto.clientes.dados is not None


async def test_falha_nao_e_entregue_como_resultado_vazio():
    """O teste que mais importa neste arquivo.

    Se o Financeiro cai e a resposta trouxesse `saldo_devedor: 0` ou `{}`, o módulo de
    Pedidos concluiria que o cliente está limpo e liberaria a venda. Falha tem que ser
    reconhecível como falha.
    """
    contexto = await montar_servico(financeiro=Comportamento.FORA).montar("cli-1")

    assert contexto.financeiro.dados is None
    assert contexto.financeiro.status != "ok"
    assert contexto.financeiro.detalhe is not None
    assert "financeiro" in contexto.fontes_indisponiveis


async def test_fonte_lenta_vira_timeout_sem_travar_a_resposta():
    """O mock lento dorme 5s; o orçamento total é de 2s."""
    inicio = time.monotonic()
    contexto = await montar_servico(logistica=Comportamento.LENTO).montar("cli-1")
    decorrido = time.monotonic() - inicio

    assert contexto.logistica.status == "timeout"
    assert contexto.logistica.dados is None
    assert contexto.clientes.status == "ok"
    assert decorrido < 2.5, f"o orcamento total nao segurou: {decorrido:.2f}s"


async def test_todas_as_fontes_fora_ainda_responde():
    """Degradação total continua sendo resposta, não erro."""
    contexto = await montar_servico(
        clientes=Comportamento.FORA,
        financeiro=Comportamento.FORA,
        logistica=Comportamento.FORA,
    ).montar("cli-1")

    assert contexto.completo is False
    assert set(contexto.fontes_indisponiveis) == {"clientes", "financeiro", "logistica"}
    assert all(
        f.dados is None for f in (contexto.clientes, contexto.financeiro, contexto.logistica)
    )


async def test_retry_recupera_falha_transitoria():
    """O mock instável falha na primeira e responde na segunda."""
    contexto = await montar_servico(clientes=Comportamento.INSTAVEL).montar("cli-1")

    assert contexto.clientes.status == "ok"
    assert contexto.clientes.tentativas == 2
    assert contexto.completo is True


async def test_retry_respeita_o_orcamento_total():
    """Sem orçamento, timeout por tentativa vezes tentativas viraria a latência real.

    Aqui a operação nunca responde. Com 1s por tentativa e 5 tentativas seriam 5s; o
    orçamento de 0.4s corta antes.
    """

    async def nunca_responde():
        await asyncio.sleep(10)

    inicio = time.monotonic()
    resposta = await consultar(
        "travada",
        nunca_responde,
        timeout_por_tentativa=1.0,
        orcamento_total=0.4,
        max_tentativas=5,
    )
    decorrido = time.monotonic() - inicio

    assert resposta.status == "timeout"
    assert resposta.dados is None
    assert decorrido < 0.9, f"o orcamento nao foi respeitado: {decorrido:.2f}s"


async def test_erro_inesperado_da_fonte_vira_degradacao_e_nao_excecao():
    async def explode():
        raise ServicoIndisponivel("conexao recusada")

    resposta = await consultar(
        "quebrada", explode, timeout_por_tentativa=0.5, orcamento_total=1.0, max_tentativas=1
    )

    assert resposta.status == "erro"
    assert resposta.dados is None
    assert "ServicoIndisponivel" in resposta.detalhe


@pytest.mark.parametrize("comportamento", [Comportamento.FORA, Comportamento.LENTO])
async def test_endpoint_responde_200_mesmo_degradado(client, comportamento):
    """Degradação graciosa é 200 com aviso, não 502.

    Um 502 aqui jogaria fora as duas fontes que responderam.
    """
    from app.core.security import usuario_autenticado
    from main import app

    app.dependency_overrides[usuario_autenticado] = lambda: None
    try:
        resposta = await client.get(
            f"/integracoes/contexto-de-venda/cli-1?simular_financeiro={comportamento.value}"
        )
    finally:
        app.dependency_overrides.clear()

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["completo"] is False
    assert corpo["fontes_indisponiveis"] == ["financeiro"]
    assert corpo["financeiro"]["dados"] is None
    assert corpo["clientes"]["dados"] is not None
