"""Contrato da consulta em linguagem natural.

O formato existe para a resposta ser **auditável**: quem pergunta consegue conferir o que
o sistema entendeu antes de confiar no número. `interpretacao` vem sempre em português e
`filtros_aplicados` mostra a consulta estruturada que de fato rodou.

Sem isso, a resposta seria um número sem procedência -- e num ERP número sem procedência
não serve para decidir compra.
"""

from typing import Any

from app.schemas.base import CustomModel
from app.schemas.produto import ProdutoResponse


class PerguntaNatural(CustomModel):
    pergunta: str


class RespostaConsultaNatural(CustomModel):
    pergunta: str
    entendida: bool

    interpretacao: str | None = None
    filtros_aplicados: dict[str, Any] | None = None

    total: int | None = None
    itens: list[ProdutoResponse] | None = None

    # Preenchidos quando o parser recusa. `ambiguidade` distingue "não entendi nada" de
    # "entendi pela metade e não vou chutar o resto".
    ambiguidade: str | None = None
    motivo: str | None = None
    sugestoes: list[str] = []
