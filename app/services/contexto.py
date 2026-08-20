"""Agrega, em paralelo, o contexto necessario para uma venda.

E o caso de uso descrito na Parte 1 como "sincrono quando o fluxo depende da resposta
agora": o modulo de Pedidos precisa de cliente, credito e prazo ao mesmo tempo, e de
nenhum deles depois.

Quem vem do Node reconhece a forma: e `Promise.allSettled`, nao `Promise.all`. A diferenca
importa e e a razao de `return_exceptions=True` estar aqui -- com `Promise.all` (ou
`gather` sem esse argumento), a primeira falha derruba o conjunto e joga fora as respostas
que ja tinham chegado.
"""

import asyncio
import time

from app.integracoes.base import RespostaFonte, consultar
from app.integracoes.mocks import ClientesAPI, FinanceiroAPI, LogisticaAPI
from app.schemas.contexto import ContextoDeVenda, FonteConsultada

# Orcamento do endpoint inteiro. Escolhido para caber com folga em um checkout: acima
# disso o usuario ja considerou o sistema travado, e responder degradado e melhor que
# responder tarde.
ORCAMENTO_TOTAL = 2.0
TIMEOUT_POR_FONTE = 0.8


class ContextoService:
    def __init__(
        self,
        clientes: ClientesAPI,
        financeiro: FinanceiroAPI,
        logistica: LogisticaAPI,
    ) -> None:
        self.clientes = clientes
        self.financeiro = financeiro
        self.logistica = logistica

    async def montar(self, cliente_id: str) -> ContextoDeVenda:
        inicio = time.monotonic()

        # As tres saem juntas. A latencia total tende a da fonte mais lenta, nao a soma:
        # e o ganho inteiro deste desenho, e ha um teste que afirma isso em numeros.
        resultados = await asyncio.gather(
            consultar(
                "clientes",
                lambda: self.clientes.buscar(cliente_id),
                timeout_por_tentativa=TIMEOUT_POR_FONTE,
                orcamento_total=ORCAMENTO_TOTAL,
            ),
            consultar(
                "financeiro",
                lambda: self.financeiro.situacao(cliente_id),
                timeout_por_tentativa=TIMEOUT_POR_FONTE,
                orcamento_total=ORCAMENTO_TOTAL,
            ),
            consultar(
                "logistica",
                lambda: self.logistica.prazo(cliente_id),
                timeout_por_tentativa=TIMEOUT_POR_FONTE,
                orcamento_total=ORCAMENTO_TOTAL,
            ),
            # Sem isto, uma excecao que escapasse de `consultar` cancelaria as irmas e
            # descartaria trabalho ja concluido. `consultar` nao deixa escapar, mas a
            # garantia fica declarada aqui e nao dependendo do comportamento dela.
            return_exceptions=True,
        )

        fontes = [
            self._normalizar(nome, r)
            for nome, r in zip(("clientes", "financeiro", "logistica"), resultados, strict=True)
        ]
        indisponiveis = [f.fonte for f in fontes if f.status != "ok"]

        return ContextoDeVenda(
            cliente_id=cliente_id,
            completo=not indisponiveis,
            fontes_indisponiveis=indisponiveis,
            latencia_total_ms=int((time.monotonic() - inicio) * 1000),
            clientes=fontes[0],
            financeiro=fontes[1],
            logistica=fontes[2],
        )

    @staticmethod
    def _normalizar(nome: str, resultado: RespostaFonte | BaseException) -> FonteConsultada:
        """Converte o resultado bruto do gather no contrato da API.

        Trata tambem o caso de `gather` ter devolvido uma excecao: nesse ponto ela ja e um
        bug meu, e nao uma falha da fonte, mas virar 500 seria punir o cliente pelo meu
        erro quando as outras duas fontes responderam.
        """
        if isinstance(resultado, BaseException):
            return FonteConsultada(
                fonte=nome,
                status="erro",
                latencia_ms=0,
                tentativas=0,
                detalhe=f"falha inesperada: {type(resultado).__name__}",
            )

        return FonteConsultada(
            fonte=resultado.fonte,
            status=resultado.status,
            dados=resultado.dados,
            latencia_ms=resultado.latencia_ms,
            tentativas=resultado.tentativas,
            detalhe=resultado.detalhe,
        )
