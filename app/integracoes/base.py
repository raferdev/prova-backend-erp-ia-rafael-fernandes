"""Chamada resiliente a servicos externos.

Esta e a peca que transforma "tres chamadas em paralelo" em algo que da para colocar em
producao. Ela resolve tres coisas que o `asyncio.gather` sozinho nao resolve.

**Timeout por fonte.** `gather` espera todo mundo. Sem timeout individual, a fonte mais
lenta define a latencia do endpoint inteiro, e uma fonte pendurada trava a resposta para
sempre.

**Orcamento total.** Timeout por tentativa multiplicado por numero de tentativas e o erro
classico: 1s de timeout com 3 tentativas vira 3s de latencia para aquela fonte. Cada
tentativa aqui so acontece se ainda houver orcamento, e a janela dela e o menor entre o
timeout configurado e o que sobrou.

**Falha nunca vira dado.** A funcao devolve um objeto com `status`, e nunca `None`
disfarcado de resposta. Num ERP isso e a diferenca entre "o cliente nao tem debito" e "eu
nao consegui saber se o cliente tem debito".
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)

StatusFonte = Literal["ok", "timeout", "erro"]


@dataclass(slots=True)
class RespostaFonte:
    """O que uma consulta a uma fonte externa devolve, tendo dado certo ou nao."""

    fonte: str
    status: StatusFonte
    dados: Any | None = None
    latencia_ms: int = 0
    tentativas: int = 1
    detalhe: str | None = None

    @property
    def disponivel(self) -> bool:
        return self.status == "ok"


def _decorrido_ms(inicio: float) -> int:
    return int((time.monotonic() - inicio) * 1000)


async def consultar(
    fonte: str,
    operacao: Callable[[], Awaitable[Any]],
    *,
    timeout_por_tentativa: float,
    orcamento_total: float,
    max_tentativas: int = 2,
    espera_entre_tentativas: float = 0.05,
) -> RespostaFonte:
    """Executa `operacao` com timeout, retry limitado e orcamento total.

    Retento tambem em timeout, e nao so em erro, porque a causa mais comum de timeout
    curto e um pico passageiro. O que torna isso seguro e o orcamento: sem ele, retentar
    timeout e a receita para transformar uma fonte lenta em endpoint travado.

    Nao retento indefinidamente nem uso backoff exponencial longo. Este e um caminho
    sincrono com um usuario esperando do outro lado; o que nao respondeu rapido duas vezes
    deve virar degradacao, nao mais espera.
    """
    inicio = time.monotonic()
    status: StatusFonte = "erro"
    detalhe = "nao executada"
    tentativa = 0

    while tentativa < max_tentativas:
        restante = orcamento_total - (time.monotonic() - inicio)
        if restante <= 0:
            detalhe = "orcamento total esgotado"
            status = "timeout"
            break

        tentativa += 1
        janela = min(timeout_por_tentativa, restante)

        try:
            async with asyncio.timeout(janela):
                dados = await operacao()
        except TimeoutError:
            status, detalhe = "timeout", f"nao respondeu em {janela:.2f}s"
            logger.warning("fonte %s: timeout na tentativa %d", fonte, tentativa)
        except Exception as erro:  # noqa: BLE001 - qualquer falha vira degradacao
            status, detalhe = "erro", f"{type(erro).__name__}: {erro}"
            logger.warning("fonte %s: falhou na tentativa %d (%s)", fonte, tentativa, erro)
        else:
            return RespostaFonte(
                fonte=fonte,
                status="ok",
                dados=dados,
                latencia_ms=_decorrido_ms(inicio),
                tentativas=tentativa,
            )

        if tentativa < max_tentativas:
            await asyncio.sleep(espera_entre_tentativas)

    return RespostaFonte(
        fonte=fonte,
        status=status,
        dados=None,
        latencia_ms=_decorrido_ms(inicio),
        tentativas=max(tentativa, 1),
        detalhe=detalhe,
    )
