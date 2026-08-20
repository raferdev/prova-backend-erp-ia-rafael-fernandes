"""Importar os models aqui registra as tabelas no `Base.metadata`.

O `alembic/env.py` importa este pacote. Sem estes imports o autogenerate nao enxerga
tabela nenhuma e gera uma migration vazia -- ou, pior, um DROP de tudo que ja existe.
"""

from app.models.produto import Produto
from app.models.usuario import Usuario

__all__ = ["Produto", "Usuario"]
