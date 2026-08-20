"""Testes de integração do repositório de produtos, contra Postgres de verdade.

Este arquivo fecha o maior buraco que a medição de cobertura revelou: `repositories/
produto.py` estava em 26%. Todos os testes de regra de negócio usam dublê, então o SQL
que de fato roda em produção quase não era exercitado — e bug de filtro não levanta
exceção, devolve o conjunto errado com cara de certo.

O que testo aqui é só o que depende do banco: tradução de filtro para SQL, paginação com
COUNT separado, e o UPDATE atômico. Regra de negócio continua sendo testada com dublê, que
é rápido.

Pulam sozinhos quando não há Postgres acessível.
"""

import asyncio
import os
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.produto import Produto
from app.repositories.produto import ProdutoRepository
from app.schemas.filtros import FiltrosProduto, Paginacao

DSN = (
    f"postgresql+asyncpg://{os.getenv('PG_USER', 'erp')}:"
    f"{os.getenv('PG_PASSWORD', 'erp_local_password')}@"
    f"{os.getenv('PG_HOST', 'localhost')}:{os.getenv('PG_PORT', '5432')}/"
    f"{os.getenv('PG_DB', 'erp')}"
)

# Prefixo único por execução: os testes filtram só o que eles mesmos criaram, então rodam
# num banco que já tem o seed sem depender de tabela vazia.
MARCA = f"zztest-{uuid.uuid4().hex[:8]}"


def sem_banco() -> None:
    """Sem Postgres, pula localmente e falha na CI.

    Pular na CI seria pior do que não ter o teste: o pipeline ficaria verde sem nunca ter
    exercitado o SQL, que é exatamente o que estes testes existem para cobrir. Confiança
    falsa é pior que ausência de teste, porque ninguém vai procurar o buraco.
    """
    recado = "Postgres indisponivel: rode `docker compose up -d postgres`"
    if os.getenv("CI"):
        pytest.fail(f"{recado} (pular nao e aceitavel na CI)")
    pytest.skip(recado)


@pytest.fixture
async def engine():
    motor = create_async_engine(DSN)
    try:
        async with motor.connect():
            pass
    except Exception:  # noqa: BLE001
        await motor.dispose()
        sem_banco()
    yield motor
    await motor.dispose()


@pytest.fixture
async def repo(engine):
    fabrica = async_sessionmaker(engine, expire_on_commit=False)
    async with fabrica() as sessao:
        repositorio = ProdutoRepository(sessao)
        criados: list[Produto] = []

        async def criar(nome: str, preco: str, estoque: int, minimo: int = 5, ativo: bool = True):
            produto = await repositorio.criar(
                {
                    "nome": f"{MARCA} {nome}",
                    "preco": Decimal(preco),
                    "quantidade_estoque": estoque,
                    "estoque_minimo": minimo,
                    "ativo": ativo,
                }
            )
            criados.append(produto)
            return produto

        repositorio.criar_para_teste = criar  # type: ignore[attr-defined]
        yield repositorio

        for produto in criados:
            await sessao.delete(produto)
        await sessao.commit()


def filtros(**kwargs) -> FiltrosProduto:
    """Todo teste filtra pela marca desta execução, para não ver o seed nem os vizinhos."""
    return FiltrosProduto(nome=MARCA, **kwargs)


class TestFiltros:
    async def test_faixa_de_preco_inclui_os_extremos(self, repo):
        await repo.criar_para_teste("barato", "10.00", 5)
        await repo.criar_para_teste("meio", "50.00", 5)
        await repo.criar_para_teste("caro", "90.00", 5)

        itens, total = await repo.listar(
            filtros(preco_min=Decimal("10.00"), preco_max=Decimal("50.00")), Paginacao()
        )

        assert total == 2
        assert {i.preco for i in itens} == {Decimal("10.00"), Decimal("50.00")}

    async def test_busca_por_nome_ignora_maiusculas(self, repo):
        await repo.criar_para_teste("Cabo HDMI", "10.00", 5)

        _, total = await repo.listar(FiltrosProduto(nome=f"{MARCA} cabo hdmi"), Paginacao())

        assert total == 1

    async def test_estoque_baixo_compara_com_o_minimo_de_cada_produto(self, repo):
        """A comparação é entre colunas, não com um número fixo.

        Um produto com 8 unidades pode estar em falta e outro com 8 pode estar sobrando,
        dependendo do limiar de cada um. É a regra que um `WHERE quantidade < 10` erraria.
        """
        await repo.criar_para_teste("em falta", "10.00", estoque=8, minimo=20)
        await repo.criar_para_teste("sobrando", "10.00", estoque=8, minimo=2)

        itens, total = await repo.listar(filtros(apenas_estoque_baixo=True), Paginacao())

        assert total == 1
        assert itens[0].estoque_minimo == 20

    async def test_estoque_baixo_inclui_o_limiar_exato(self, repo):
        """Igual ao mínimo já é alerta: é o ponto de reposição, não o de ruptura."""
        await repo.criar_para_teste("no limiar", "10.00", estoque=5, minimo=5)

        _, total = await repo.listar(filtros(apenas_estoque_baixo=True), Paginacao())

        assert total == 1

    async def test_estoque_baixo_ignora_produto_inativo(self, repo):
        """Alertar reposição de item descontinuado é ruído."""
        await repo.criar_para_teste("inativo em falta", "10.00", estoque=0, minimo=9, ativo=False)

        _, total = await repo.listar(filtros(apenas_estoque_baixo=True), Paginacao())

        assert total == 0

    async def test_faixa_numerica_de_estoque(self, repo):
        await repo.criar_para_teste("vazio", "10.00", estoque=0)
        await repo.criar_para_teste("cheio", "10.00", estoque=100)

        _, total = await repo.listar(filtros(estoque_max=10), Paginacao())

        assert total == 1

    async def test_filtros_combinados_sao_conjuncao(self, repo):
        """Filtros somam restrições. Se virassem OR, a lista viria maior e ninguém notaria."""
        await repo.criar_para_teste("alvo", "20.00", estoque=1, minimo=10)
        await repo.criar_para_teste("preco fora", "900.00", estoque=1, minimo=10)

        _, total = await repo.listar(
            filtros(preco_max=Decimal("50.00"), apenas_estoque_baixo=True), Paginacao()
        )

        assert total == 1


class TestPaginacao:
    async def test_total_ignora_o_limite_da_pagina(self, repo):
        """O COUNT é separado de propósito.

        Contar a lista paginada daria no máximo `tamanho`, e o número de páginas sairia
        sempre 1 — um bug que só aparece quando o catálogo cresce.
        """
        for i in range(5):
            await repo.criar_para_teste(f"item {i}", "10.00", 5)

        itens, total = await repo.listar(filtros(), Paginacao(pagina=1, tamanho=2))

        assert len(itens) == 2
        assert total == 5

    async def test_paginas_nao_se_sobrepoem(self, repo):
        for i in range(5):
            await repo.criar_para_teste(f"item {i}", "10.00", 5)

        primeira, _ = await repo.listar(filtros(), Paginacao(pagina=1, tamanho=2))
        segunda, _ = await repo.listar(filtros(), Paginacao(pagina=2, tamanho=2))

        assert {p.id for p in primeira}.isdisjoint({p.id for p in segunda})

    async def test_pagina_alem_do_fim_vem_vazia_com_total_correto(self, repo):
        await repo.criar_para_teste("unico", "10.00", 5)

        itens, total = await repo.listar(filtros(), Paginacao(pagina=99, tamanho=20))

        assert itens == []
        assert total == 1


class TestAjusteAtomicoDeEstoque:
    async def test_soma_o_delta_e_devolve_o_produto(self, repo):
        produto = await repo.criar_para_teste("alvo", "10.00", estoque=10)

        atualizado = await repo.ajustar_estoque(produto.id, -4)

        assert atualizado.quantidade_estoque == 6

    async def test_check_constraint_impede_saldo_negativo(self, repo):
        """A garantia é do banco, e não do Python.

        Deixá-la no banco cobre também quem escrever por fora do service.
        """
        produto = await repo.criar_para_teste("alvo", "10.00", estoque=3)

        with pytest.raises(IntegrityError):
            await repo.ajustar_estoque(produto.id, -10)

        await repo.session.rollback()

    async def test_produto_inexistente_devolve_none(self, repo):
        assert await repo.ajustar_estoque(uuid.uuid4(), -1) is None

    async def test_ajustes_concorrentes_nao_perdem_atualizacao(self, engine, repo):
        """O motivo de o UPDATE ser atômico, verificado com sessões separadas.

        Ler-somar-gravar aqui daria 9 em vez de 5: as duas transações leriam 10, as duas
        gravariam 9, e cinco baixas virariam uma. É perda de atualização silenciosa, o pior
        tipo de bug de estoque.
        """
        produto = await repo.criar_para_teste("disputado", "10.00", estoque=10)
        fabrica = async_sessionmaker(engine, expire_on_commit=False)

        async def baixar_um():
            async with fabrica() as sessao:
                await ProdutoRepository(sessao).ajustar_estoque(produto.id, -1)

        await asyncio.gather(*(baixar_um() for _ in range(5)))

        final = await repo.buscar_por_id(produto.id)
        await repo.session.refresh(final)
        assert final.quantidade_estoque == 5
