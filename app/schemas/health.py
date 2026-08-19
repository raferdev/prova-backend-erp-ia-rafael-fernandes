"""Contrato de saida dos endpoints de health."""

from typing import Literal

from pydantic import Field

from app.schemas.base import CustomModel


class HealthResponse(CustomModel):
    status: Literal["ok"] = "ok"
    service: str = "erp-pedidos-estoque"


class DependencyStatus(CustomModel):
    name: str
    healthy: bool
    detail: str | None = None


class ReadinessResponse(CustomModel):
    status: Literal["ready", "degraded"]
    dependencies: list[DependencyStatus] = Field(default_factory=list)
