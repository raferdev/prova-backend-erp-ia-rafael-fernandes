"""Base Pydantic de toda a API.

Ter uma base controlada permite mudar o comportamento de *todos* os contratos em um
lugar so. Aqui ela resolve um problema concreto: `datetime` sem timezone.

O Postgres devolve `datetime` naive quando a coluna e `TIMESTAMP WITHOUT TIME ZONE`.
Serializado direto, o cliente recebe `2026-08-19T10:30:00` e nao tem como saber em que
fuso isso esta -- num ERP, onde datas de pedido e de faturamento tem peso contabil, isso
e defeito, nao detalhe. A base normaliza para UTC explicito na saida JSON.
"""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, field_serializer


class CustomModel(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        from_attributes=True,  # permite construir o schema direto do objeto do ORM
    )

    @field_serializer("*", when_used="json", check_fields=False)
    def _serialize_datetimes(self, value: Any) -> Any:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=ZoneInfo("UTC"))
            return value.strftime("%Y-%m-%dT%H:%M:%S%z")
        return value
