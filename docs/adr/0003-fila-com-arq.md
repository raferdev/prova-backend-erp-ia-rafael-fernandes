# ADR 0003 — `arq` como fila de background

**Data:** 2026-08-19 · **Status:** aceito

## Contexto

A prova pede um worker de fila para uma tarefa real do domínio (recalcular estoque,
alertar estoque baixo, gerar relatório). No Node eu usaria BullMQ, que é Redis puro. Queria
o equivalente mais direto disso em Python.

## Opções que considerei

**`BackgroundTasks` do próprio FastAPI.** Zero dependência nova.

**Celery.** O padrão histórico do ecossistema.

**RQ.** Simples, Redis-only.

**`arq`.** Redis-only e async nativo.

## Decisão

`arq`.

`BackgroundTasks` eu descartei primeiro, e vale registrar por quê, porque é a opção que
parece de graça. Ela roda no mesmo processo do worker web, sem retry, sem visibilidade e
sem persistência: se o processo morre, a tarefa some. A régua que adotei é a do
`fastapi-best-practices`, e ela é boa: *se você seria acordado de madrugada porque a
tarefa se perdeu, ela não pertence a `BackgroundTasks`*. Baixa de estoque num ERP se
encaixa nisso sem discussão.

Entre os três restantes: RQ é síncrono, e adotar RQ significaria ter dois modelos de
concorrência convivendo no mesmo repositório, o que é confuso de explicar e pior de
debugar. Celery resolve tudo, mas traz broker, backend de resultado, pools e um
vocabulário próprio que é desproporcional a um worker só.

`arq` roda no mesmo event loop, usa o Redis que já está no stack por causa do cache e dos
locks, e a API é pequena o bastante para caber na cabeça.

## Consequências

Ganho: uma dependência de infra a menos e um modelo de concorrência só.

Pago: `arq` tem comunidade bem menor que Celery. Se eu precisasse de agendamento
complexo, rate limiting por fila ou dead-letter sofisticado, essa escolha começaria a
apertar. Para o escopo aqui, não aperta.

## Como validei

O worker existe e consome da fila. As tarefas e o desenho delas estão no
[ADR 0008](0008-worker-de-estoque.md); aqui fica o que valida a escolha do `arq` em si.

Sobe como serviço do Compose e reporta saúde pelo próprio mecanismo do arq
(`arq --check`), sem eu ter que inventar healthcheck:

```
SERVICE    STATUS
worker     Up 22 seconds (healthy)
```

Processa job enfileirado pela API e roda cron:

```
14:28:30  eb75bf71:ajustar_estoque ● {'saldo': 108, 'alerta': 'resolvido'}
14:28:00  cron:verificar_estoque_baixo ● {'abertos': 0, 'resolvidos': 0, 'ja_abertos': 4}
```

O que confirmou a escolha na prática: as tarefas são `async` e chamam o mesmo
`EstoqueService` que a API usa, com o mesmo `AsyncSession` e o mesmo cliente Redis. Com RQ
(síncrono) eu teria dois modelos de concorrência no mesmo repositório e precisaria de uma
camada de adaptação só para reaproveitar a regra de negócio.

O que continua verdade do lado do custo: a comunidade do `arq` é pequena, e a documentação
de casos menos comuns é rasa. `run_at_startup` no cron e o formato do `ctx` eu descobri
lendo o código-fonte, não a documentação.
