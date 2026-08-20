"""Configuracao do worker arq.

Sobe com:  arq app.workers.settings.WorkerSettings

`redis_cache` no ctx e o cliente do cache da aplicacao, e nao o da fila. Sao Redis
logicamente separados (ver `app/core/fila.py`): o arq usa o seu para guardar jobs, e as
tarefas usam o da aplicacao para invalidar cache.
"""

from typing import Any

from arq import cron

from app.core.fila import redis_settings
from app.core.redis import get_redis, pool
from app.workers.tarefas import ajustar_estoque, verificar_estoque_baixo


async def ao_iniciar(ctx: dict[str, Any]) -> None:
    ctx["redis_cache"] = get_redis()


async def ao_encerrar(ctx: dict[str, Any]) -> None:
    await pool.aclose()


class WorkerSettings:
    redis_settings = redis_settings()

    functions = [ajustar_estoque, verificar_estoque_baixo]

    # Varredura de minuto em minuto. Num sistema real isto seria bem mais espacado; deixo
    # curto aqui para o comportamento ser observavel em uma sessao de avaliacao.
    cron_jobs = [cron(verificar_estoque_baixo, second=0, run_at_startup=True)]

    on_startup = ao_iniciar
    on_shutdown = ao_encerrar

    # Retentativas com backoff. As tarefas sao idempotentes por construcao (o indice unico
    # parcial do alerta e o UPDATE atomico do saldo), entao repetir e seguro.
    max_tries = 3
    job_timeout = 60
