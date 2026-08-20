"""Contratos de movimentacao de estoque e alerta."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.base import CustomModel


class AjusteEstoque(CustomModel):
    delta: int = Field(
        description="Negativo baixa, positivo repoe. Zero e recusado por nao ter efeito.",
    )
    motivo: str = Field(min_length=3, max_length=200)

    @field_validator("delta")
    @classmethod
    def delta_precisa_ter_efeito(cls, valor: int) -> int:
        if valor == 0:
            raise ValueError("delta zero nao movimenta estoque")
        return valor


class AjusteAceito(CustomModel):
    """Resposta 202: o ajuste foi enfileirado, nao executado.

    Devolvo o `job_id` para o cliente conseguir correlacionar com o log do worker. Num
    sistema maior aqui entraria tambem a URL de consulta do status do job.
    """

    job_id: str
    produto_id: uuid.UUID
    situacao: Literal["enfileirado"] = "enfileirado"


class AlertaResponse(CustomModel):
    id: uuid.UUID
    produto_id: uuid.UUID
    status: str
    quantidade_no_alerta: int
    estoque_minimo_no_alerta: int
    criado_em: datetime
    resolvido_em: datetime | None = None


class MovimentoResponse(CustomModel):
    id: uuid.UUID
    produto_id: uuid.UUID
    delta: int
    saldo_apos: int
    motivo: str
    referencia: str
    criado_em: datetime
