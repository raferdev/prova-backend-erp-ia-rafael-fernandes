"""Testes do health check.

`/health` e testado sem nenhuma dependencia de infra de proposito: se este teste
precisasse de Postgres no ar, ele deixaria de ser um teste de liveness.
"""

from fastapi.testclient import TestClient


def test_health_retorna_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "erp-pedidos-estoque"}


def test_readiness_reporta_dependencias_indisponiveis(client: TestClient) -> None:
    """Sem Postgres/Redis no ar, readiness deve degradar -- e nao explodir com 500.

    Esse e o comportamento que o load balancer espera: uma resposta estruturada
    dizendo "nao me mande trafego", com o detalhe de qual dependencia falhou.
    """
    response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert {dep["name"] for dep in body["dependencies"]} == {"postgres", "redis"}
