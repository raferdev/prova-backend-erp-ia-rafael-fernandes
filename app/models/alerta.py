"""Alerta de estoque baixo. Implementa a tabela decidida no ADR 0008.

O detalhe que carrega o desenho e o indice unico parcial: no maximo um alerta `aberto` por
produto. A idempotencia da tarefa fica garantida pelo banco, nao por codigo -- a varredura
pode rodar a cada minuto por uma semana sem duplicar alerta, e a tarefa fica segura para
retry, que e requisito de qualquer fila.
"""

import uuid
from datetime import datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StatusAlerta(StrEnum):
    ABERTO = "aberto"
    RESOLVIDO = "resolvido"


class AlertaEstoque(Base):
    __tablename__ = "alerta_estoque"
    __table_args__ = (
        CheckConstraint(
            "status IN ('aberto', 'resolvido')",
            name="status_valido",
        ),
        # Enum nativo do Postgres daria a mesma garantia, mas ALTER TYPE em migration e
        # desconfortavel. String + CheckConstraint migra sem cerimonia (ADR 0008).
        Index(
            "alerta_estoque_produto_aberto_idx",
            "produto_id",
            unique=True,
            postgresql_where=sa.text("status = 'aberto'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    produto_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("produto.id", ondelete="CASCADE"), index=True
    )

    status: Mapped[str] = mapped_column(String(20), default=StatusAlerta.ABERTO)

    # Guardo os valores do momento do alerta. Sem isso, ler um alerta de tres meses atras
    # mostraria o estoque de hoje e o historico nao significaria nada.
    quantidade_no_alerta: Mapped[int] = mapped_column(Integer)
    estoque_minimo_no_alerta: Mapped[int] = mapped_column(Integer)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolvido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
