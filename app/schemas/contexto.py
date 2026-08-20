"""Contrato do contexto de venda.

O formato foi desenhado em torno de uma regra: **o cliente da API precisa conseguir
distinguir "nao ha debito" de "nao consegui consultar o debito"**. Por isso cada fonte
tem status proprio no corpo da resposta, e `dados` vem `null` quando a fonte falhou --
nunca um objeto vazio ou um valor padrao, que seriam lidos como resposta legitima.
"""

from typing import Any, Literal

from app.schemas.base import CustomModel


class FonteConsultada(CustomModel):
    fonte: str
    status: Literal["ok", "timeout", "erro"]
    dados: Any | None = None
    latencia_ms: int
    tentativas: int
    detalhe: str | None = None


class ContextoDeVenda(CustomModel):
    cliente_id: str

    # `completo` responde de uma vez a pergunta que o consumidor faz primeiro. Sem ele,
    # cada cliente da API teria que reimplementar a varredura dos status.
    completo: bool
    fontes_indisponiveis: list[str] = []
    latencia_total_ms: int

    clientes: FonteConsultada
    financeiro: FonteConsultada
    logistica: FonteConsultada

    @property
    def pode_liberar_venda(self) -> bool:
        """Nao exposto na resposta de proposito: quem decide liberar venda e o modulo de
        Pedidos, com a politica dele. Este endpoint entrega contexto, nao veredito.
        """
        return self.completo
