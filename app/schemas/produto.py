"""Contrato da API de produtos.

Uso Pydantic com folga aqui: cada regra que da para expressar no schema e uma regra que o
service nao precisa checar e que aparece sozinha na documentacao do /docs.

Detalhe idiomatico que nao existe no Node: levantar `ValueError` dentro de um validator
faz o FastAPI devolver 422 com a mensagem no corpo, ja formatada. Nao preciso capturar e
converter para HTTPException na mao.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import Field, field_validator

from app.schemas.base import CustomModel


class ProdutoBase(CustomModel):
    nome: str = Field(min_length=2, max_length=200)
    descricao: str | None = Field(default=None, max_length=1000)
    # ge=0 cobre a exigencia de preco nao negativo no contrato; a CheckConstraint no banco
    # cobre o mesmo no nivel do dado. As duas existem de proposito: a API nao e o unico
    # caminho de escrita (worker e migration tambem escrevem).
    preco: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    quantidade_estoque: int = Field(default=0, ge=0)
    estoque_minimo: int = Field(default=0, ge=0)
    ativo: bool = True

    @field_validator("nome")
    @classmethod
    def nome_precisa_ser_texto(cls, valor: str) -> str:
        limpo = valor.strip()
        if not limpo:
            raise ValueError("nome nao pode ser vazio ou so espacos")
        if limpo.isdigit():
            raise ValueError("nome nao pode ser apenas numerico")
        return limpo


class ProdutoCreate(ProdutoBase):
    pass


class ProdutoUpdate(CustomModel):
    """Atualizacao parcial: tudo opcional.

    Uso `exclude_unset` no service para distinguir "campo ausente" de "campo enviado como
    null". Sem isso, um PATCH com um campo so zeraria todo o resto.
    """

    nome: str | None = Field(default=None, min_length=2, max_length=200)
    descricao: str | None = Field(default=None, max_length=1000)
    preco: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    quantidade_estoque: int | None = Field(default=None, ge=0)
    estoque_minimo: int | None = Field(default=None, ge=0)
    ativo: bool | None = None

    _valida_nome = field_validator("nome")(ProdutoBase.nome_precisa_ser_texto.__func__)


class ProdutoResponse(ProdutoBase):
    id: uuid.UUID
    criado_em: datetime
    atualizado_em: datetime


class PaginaProdutos(CustomModel):
    itens: list[ProdutoResponse]
    total: int
    pagina: int
    tamanho: int
    paginas: int
