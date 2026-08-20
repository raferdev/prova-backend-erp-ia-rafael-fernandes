"""Servicos mock dos outros modulos do ERP.

Sao mocks porque a prova pede fontes simuladas, e porque integrar de verdade com tres
servicos que nao existem nao provaria nada. O que importa e que a assinatura seja
identica a de um cliente HTTP real (funcao async que pode demorar, falhar ou responder),
para que trocar o mock por `httpx` nao mude nada em `services/contexto.py`.

Os modulos escolhidos vem da divisao de bounded contexts da Parte 1: Clientes, Financeiro
e Logistica. O modulo de Pedidos e Estoque precisa dos tres ao mesmo tempo, e de nenhum
deles depois -- e o caso classico de chamada sincrona paralela.

`Comportamento` existe para a degradacao ser demonstravel sem eu ter que derrubar nada:
o endpoint aceita `?simular=` e os testes injetam o cenario direto.
"""

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any


class Comportamento(StrEnum):
    NORMAL = "normal"
    LENTO = "lento"
    FORA = "fora"
    INSTAVEL = "instavel"


class ServicoIndisponivel(Exception):
    """Equivalente a um 503 ou a uma conexao recusada do servico real."""


@dataclass
class FonteMock:
    """Base dos mocks: concentra a simulacao de latencia e falha."""

    nome: str
    latencia_normal: float = 0.05
    latencia_lenta: float = 5.0
    comportamento: Comportamento = Comportamento.NORMAL
    _chamadas: int = 0

    async def _simular(self) -> None:
        self._chamadas += 1

        if self.comportamento is Comportamento.FORA:
            raise ServicoIndisponivel(f"{self.nome} recusou a conexao")

        if self.comportamento is Comportamento.LENTO:
            await asyncio.sleep(self.latencia_lenta)
            return

        if self.comportamento is Comportamento.INSTAVEL:
            # Falha na primeira e responde na segunda: e o caso que justifica ter retry.
            await asyncio.sleep(self.latencia_normal)
            if self._chamadas == 1:
                raise ServicoIndisponivel(f"{self.nome} instavel")
            return

        await asyncio.sleep(self.latencia_normal)


class ClientesAPI(FonteMock):
    async def buscar(self, cliente_id: str) -> dict[str, Any]:
        await self._simular()
        return {
            "id": cliente_id,
            "nome": "Comercio Silva Ltda",
            "documento": "12.345.678/0001-90",
            "segmento": "varejo",
            "ativo": True,
        }


class FinanceiroAPI(FonteMock):
    async def situacao(self, cliente_id: str) -> dict[str, Any]:
        await self._simular()
        return {
            "cliente_id": cliente_id,
            "limite_credito": str(Decimal("50000.00")),
            "saldo_devedor": str(Decimal("12350.40")),
            "faturas_vencidas": 0,
            "bloqueado": False,
        }


class LogisticaAPI(FonteMock):
    async def prazo(self, cliente_id: str) -> dict[str, Any]:
        await self._simular()
        return {
            "cliente_id": cliente_id,
            "transportadora": "Expresso Sul",
            "prazo_dias_uteis": 3,
            "cobertura": True,
        }
