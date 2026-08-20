"""Tabela de usuario, usada apenas para autenticar e emitir JWT.

Num ERP real este dominio pertenceria ao servico de Clientes/Identidade (ver a divisao de
bounded contexts da Parte 1), e este servico so validaria o token emitido por ele. Mantenho
uma tabela local porque a prova pede JWT funcionando num servico so.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Usuario(Base):
    __tablename__ = "usuario"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    # Guardo hash, nunca a senha. O nome do campo diz isso para quem ler o model depois.
    senha_hash: Mapped[str] = mapped_column(String(128))
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
