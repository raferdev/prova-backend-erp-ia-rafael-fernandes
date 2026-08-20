"""Tabela de produto.

Convencoes de nome seguem o que fixei no ADR 0006: singular, snake_case, sufixo `_em`
para datetime. As CheckConstraints tem nome explicito de proposito -- a naming convention
so consegue gerar `produto_preco_nao_negativo_check` se a constraint tiver `name`.
Constraint anonima vira migration que sobe e nao desce.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, Integer, Numeric, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Produto(Base):
    __tablename__ = "produto"
    __table_args__ = (
        CheckConstraint("preco >= 0", name="preco_nao_negativo"),
        CheckConstraint("quantidade_estoque >= 0", name="estoque_nao_negativo"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    nome: Mapped[str] = mapped_column(String(200), index=True)
    descricao: Mapped[str | None] = mapped_column(String(1000), default=None)

    # Numeric e nao Float: float binario nao representa 0.10 exatamente, e num ERP o erro
    # de arredondamento vira divergencia contabil. asyncpg devolve Decimal para NUMERIC.
    preco: Mapped[Decimal] = mapped_column(Numeric(12, 2), index=True)

    quantidade_estoque: Mapped[int] = mapped_column(Integer, default=0)
    # Limiar por produto: "estoque baixo" nao e um numero fixo global. Uma fabrica de
    # parafusos e um fornecedor de motores nao tem o mesmo ponto de alerta.
    estoque_minimo: Mapped[int] = mapped_column(Integer, default=0)

    ativo: Mapped[bool] = mapped_column(Boolean, default=True)

    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
