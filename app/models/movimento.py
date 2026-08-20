"""Livro de movimentacoes de estoque.

Existe por dois motivos que se reforcam.

O primeiro e correcao: fila entrega **pelo menos uma vez**. Se o worker commitar a baixa e
morrer antes de confirmar o job, o arq reentrega e o `delta` seria aplicado de novo. O
`job_id` unico transforma a reentrega em no-op -- a mesma tecnica de `ON CONFLICT` que o
alerta usa.

O segundo e de dominio: ERP sem historico de movimentacao nao responde "por que o saldo
deste item caiu 40 unidades ontem", que e a primeira pergunta de qualquer auditoria de
inventario. O saldo em `produto` passa a ser o agregado; aqui fica o extrato.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MovimentoEstoque(Base):
    __tablename__ = "movimento_estoque"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    produto_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("produto.id", ondelete="CASCADE"), index=True
    )

    # Chave de idempotencia. Unica: a segunda tentativa de gravar a mesma referencia
    # conflita e a movimentacao nao e aplicada de novo.
    referencia: Mapped[str] = mapped_column(String(120), unique=True)

    delta: Mapped[int] = mapped_column(Integer)
    saldo_apos: Mapped[int] = mapped_column(Integer)
    motivo: Mapped[str] = mapped_column(String(200))

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
