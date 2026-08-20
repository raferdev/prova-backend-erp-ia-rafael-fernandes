"""Testes do health check.

Estes testes controlam o estado das dependências em vez de torcer por ele.

A primeira versão afirmava que readiness devolvia 503 e passava localmente porque o
`conftest` usa credenciais `test/test`, que não existem no Postgres de desenvolvimento --
a conexão falhava por acidente. Na CI, onde as credenciais são as de verdade, a conexão
funcionava e o teste quebrava.

O teste estava certo sobre o comportamento e errado sobre como chegar nele: dependia de
um ambiente que ele não controla. Com `dependency_overrides` os dois caminhos ficam
determinísticos e o resultado não muda entre a minha máquina e a CI.
"""

from typing import Any

import pytest
from httpx import AsyncClient

from app.core.database import get_session
from app.core.redis import get_redis
from main import app


class SessaoIndisponivel:
    """Sessão que falha como o SQLAlchemy falharia com o banco fora."""

    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise ConnectionRefusedError("postgres fora do ar (simulado)")


class RedisIndisponivel:
    async def ping(self) -> Any:
        raise ConnectionRefusedError("redis fora do ar (simulado)")


@pytest.fixture
def dependencias_fora():
    app.dependency_overrides[get_session] = lambda: SessaoIndisponivel()
    app.dependency_overrides[get_redis] = lambda: RedisIndisponivel()
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def dependencias_ok():
    class SessaoSaudavel:
        async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
            return None

    class RedisSaudavel:
        async def ping(self) -> bool:
            return True

    app.dependency_overrides[get_session] = lambda: SessaoSaudavel()
    app.dependency_overrides[get_redis] = lambda: RedisSaudavel()
    yield
    app.dependency_overrides.clear()


async def test_health_retorna_ok(client: AsyncClient) -> None:
    """Liveness não toca em dependência nenhuma, então não precisa de fixture.

    Se este teste algum dia precisar de banco, é sinal de que o endpoint deixou de ser
    liveness -- e aí uma queda do Postgres passaria a reiniciar a API em loop.
    """
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "erp-pedidos-estoque"}


async def test_readiness_ok_quando_as_dependencias_respondem(
    client: AsyncClient, dependencias_ok
) -> None:
    response = await client.get("/health/ready")

    assert response.status_code == 200
    corpo = response.json()
    assert corpo["status"] == "ready"
    assert all(dep["healthy"] for dep in corpo["dependencies"])


async def test_readiness_degrada_quando_tudo_esta_fora(
    client: AsyncClient, dependencias_fora
) -> None:
    """Falha vira 503 estruturado, e não 500.

    É o que o load balancer espera: uma resposta dizendo "não me mande tráfego agora",
    com o detalhe de qual dependência caiu.
    """
    response = await client.get("/health/ready")

    assert response.status_code == 503
    corpo = response.json()
    assert corpo["status"] == "degraded"
    assert {dep["name"] for dep in corpo["dependencies"]} == {"postgres", "redis"}
    assert all(not dep["healthy"] for dep in corpo["dependencies"])
    assert all(dep["detail"] for dep in corpo["dependencies"])


async def test_readiness_degrada_com_apenas_uma_dependencia_fora(client: AsyncClient) -> None:
    """Uma fonte fora não pode mascarar a outra que está de pé.

    O corpo precisa dizer qual caiu; sem isso, quem investiga um incidente começa
    checando as duas.
    """

    class SessaoSaudavel:
        async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
            return None

    app.dependency_overrides[get_session] = lambda: SessaoSaudavel()
    app.dependency_overrides[get_redis] = lambda: RedisIndisponivel()
    try:
        response = await client.get("/health/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    por_nome = {dep["name"]: dep for dep in response.json()["dependencies"]}
    assert por_nome["postgres"]["healthy"] is True
    assert por_nome["redis"]["healthy"] is False
