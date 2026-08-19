"""Endpoints de health.

Separamos *liveness* de *readiness* de proposito:

- `/health` (liveness): o processo esta de pe? Nao toca em dependencia nenhuma.
  E o que o orquestrador usa para decidir reiniciar o container. Se ele checasse o
  Postgres, uma queda do banco derrubaria a API inteira em loop de restart.
- `/health/ready` (readiness): as dependencias respondem? E o que o load balancer usa
  para decidir mandar trafego. Aqui uma falha significa "nao me mande request agora",
  nao "me mate".
"""

from fastapi import APIRouter, Depends, Response, status
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.redis import get_redis
from app.schemas.health import DependencyStatus, HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@router.get("/health/ready", response_model=ReadinessResponse)
async def readiness(
    response: Response,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> ReadinessResponse:
    dependencies: list[DependencyStatus] = []

    try:
        await session.execute(text("SELECT 1"))
        dependencies.append(DependencyStatus(name="postgres", healthy=True))
    except Exception as exc:  # noqa: BLE001 - queremos reportar qualquer falha
        dependencies.append(
            DependencyStatus(name="postgres", healthy=False, detail=str(exc))
        )

    try:
        await redis.ping()
        dependencies.append(DependencyStatus(name="redis", healthy=True))
    except Exception as exc:  # noqa: BLE001
        dependencies.append(DependencyStatus(name="redis", healthy=False, detail=str(exc)))

    all_healthy = all(dep.healthy for dep in dependencies)
    if not all_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status="ready" if all_healthy else "degraded",
        dependencies=dependencies,
    )
