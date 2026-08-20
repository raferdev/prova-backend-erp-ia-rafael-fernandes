"""Testes de integração do alerta, contra Postgres de verdade.

Este arquivo existe por causa de um bug que os testes de unidade não tinham como pegar.

O `ON CONFLICT` do alerta precisa casar com o índice único parcial. Eu passei o predicado
como expressão do ORM, que renderiza como bind parameter, e o Postgres recusou com
`there is no unique or exclusion constraint matching the ON CONFLICT specification`. O
dublê de repository passou tranquilo: ele reimplementa o invariante em Python, então
validava a minha intenção em vez do meu SQL.

É a fronteira honesta do teste com dublê. Dublê prova regra de negócio; garantia de banco
só o banco prova.

Pulam sozinhos quando não há Postgres acessível, para não quebrar a suíte de quem só quer
rodar os testes rápidos.
"""

import os
import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.alerta import AlertaEstoque, StatusAlerta
from app.models.produto import Produto
from app.repositories.alerta import AlertaRepository
from app.tests.test_integracao_produto_repo import sem_banco

DSN = (
    f"postgresql+asyncpg://{os.getenv('PG_USER', 'erp')}:"
    f"{os.getenv('PG_PASSWORD', 'erp_local_password')}@"
    f"{os.getenv('PG_HOST', 'localhost')}:{os.getenv('PG_PORT', '5432')}/"
    f"{os.getenv('PG_DB', 'erp')}"
)


@pytest.fixture
async def session():
    engine = create_async_engine(DSN)
    try:
        async with engine.connect():
            pass
    except Exception:  # noqa: BLE001
        await engine.dispose()
        sem_banco()

    fabrica = async_sessionmaker(engine, expire_on_commit=False)
    async with fabrica() as sessao:
        yield sessao
    await engine.dispose()


@pytest.fixture
async def produto(session):
    """Produto descartável, removido no fim. O alerta cai junto pelo ON DELETE CASCADE."""
    item = Produto(
        nome=f"Produto de teste {uuid.uuid4().hex[:8]}",
        preco=10,
        quantidade_estoque=0,
        estoque_minimo=5,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)

    yield item

    await session.delete(item)
    await session.commit()


async def test_on_conflict_casa_com_o_indice_parcial(session, produto):
    """O teste que teria pego o bug: exercita o SQL real, não a intenção."""
    repositorio = AlertaRepository(session)

    assert await repositorio.abrir_se_nao_houver(produto) is True


async def test_indice_parcial_impede_segundo_alerta_aberto(session, produto):
    """Idempotência garantida pelo banco, não por checagem prévia em Python.

    Checar "já existe?" antes de inserir seria uma corrida: dois workers checariam ao
    mesmo tempo, os dois veriam que não existe e os dois inseririam.
    """
    repositorio = AlertaRepository(session)

    assert await repositorio.abrir_se_nao_houver(produto) is True
    assert await repositorio.abrir_se_nao_houver(produto) is False
    assert await repositorio.abrir_se_nao_houver(produto) is False

    assert len(await repositorio.listar_por_produto(produto.id)) == 1


async def test_resolver_libera_espaco_para_um_alerta_novo(session, produto):
    """Depois de resolvido, o índice parcial deixa abrir outro: o predicado só cobre 'aberto'.

    É o que permite o ciclo faltou -> repôs -> faltou de novo gerar histórico, em vez de
    um alerta eterno.
    """
    repositorio = AlertaRepository(session)
    await repositorio.abrir_se_nao_houver(produto)

    assert await repositorio.resolver_abertos(produto.id) == 1
    assert await repositorio.abrir_se_nao_houver(produto) is True

    todos = await repositorio.listar_por_produto(produto.id)
    assert len(todos) == 2
    assert sum(1 for a in todos if a.status == StatusAlerta.ABERTO) == 1


async def test_alerta_guarda_o_estado_do_momento(session, produto):
    """Ler um alerta antigo tem que mostrar o estoque de então, não o de hoje."""
    repositorio = AlertaRepository(session)
    await repositorio.abrir_se_nao_houver(produto)

    alerta = (await repositorio.listar_por_produto(produto.id))[0]

    assert isinstance(alerta, AlertaEstoque)
    assert alerta.quantidade_no_alerta == 0
    assert alerta.estoque_minimo_no_alerta == 5
    assert alerta.resolvido_em is None
