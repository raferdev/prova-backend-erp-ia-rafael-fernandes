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

Ainda não. O worker entra na Parte 3 junto com o CRUD, e este ADR passa a ter seção de
validação quando existir tarefa rodando de verdade. Registro a decisão agora porque ela
já influenciou o `docker-compose.yml` e a escolha do Redis.
