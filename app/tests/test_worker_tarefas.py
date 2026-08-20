"""Testes das tarefas do worker.

A varredura tolerar schema não migrado não é refinamento: num clone novo, seguindo o
README, o `docker compose up` sobe o worker antes de alguém rodar `alembic upgrade head`.
Foi encontrado clonando o repositório do zero, não lendo o código.
"""

from typing import Any

import pytest
from sqlalchemy.exc import ProgrammingError

from app.workers import tarefas


class ErroDoDriver(Exception):
    """Imita a exceção do asyncpg, que carrega o sqlstate."""

    def __init__(self, sqlstate: str) -> None:
        super().__init__(f"erro {sqlstate}")
        self.sqlstate = sqlstate


def erro_de_banco(sqlstate: str) -> ProgrammingError:
    return ProgrammingError("SELECT 1", {}, ErroDoDriver(sqlstate))


async def test_varredura_adia_quando_o_schema_nao_existe(monkeypatch):
    async def explode(_ctx: dict[str, Any]):
        raise erro_de_banco("42P01")

    monkeypatch.setattr(tarefas, "_varrer", explode)

    resultado = await tarefas.verificar_estoque_baixo({})

    assert resultado["adiado"] is True
    assert resultado["abertos"] == 0


async def test_outro_erro_de_sql_continua_estourando(monkeypatch):
    """Só o 42P01 é tolerado.

    Engolir qualquer ProgrammingError transformaria SQL quebrado numa varredura que
    "funciona" devolvendo zero — o pior resultado possível, porque parece saudável.
    """

    async def explode(_ctx: dict[str, Any]):
        raise erro_de_banco("42703")  # undefined_column

    monkeypatch.setattr(tarefas, "_varrer", explode)

    with pytest.raises(ProgrammingError):
        await tarefas.verificar_estoque_baixo({})


async def test_varredura_normal_devolve_o_resumo(monkeypatch):
    async def varredura(_ctx: dict[str, Any]):
        return {"abertos": 2, "resolvidos": 1, "ja_abertos": 3}

    monkeypatch.setattr(tarefas, "_varrer", varredura)

    assert await tarefas.verificar_estoque_baixo({}) == {
        "abertos": 2,
        "resolvidos": 1,
        "ja_abertos": 3,
    }
