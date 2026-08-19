# ADR 0001 — Organizar por camada, não por domínio

**Data:** 2026-08-19 · **Status:** aceito

## Contexto

Venho de NestJS, onde a organização por módulo de domínio é o padrão do framework. Meu
instinto inicial foi replicar isso aqui. Antes de escrever o CRUD fui checar como a
comunidade Python resolve, porque não queria inventar convenção nem justificar escolha
com "é assim que eu faço".

Duas referências apareceram como padrão de fato:
`fastapi/full-stack-fastapi-template` (o template oficial) e
`zhanymkanov/fastapi-best-practices`.

A segunda recomenda o oposto do que acabei fazendo, o que me obrigou a olhar com cuidado.

## Opções que considerei

**A. Por domínio** (`app/produtos/router.py`, `app/produtos/service.py`), inspirado no
Dispatch da Netflix. É o que o `fastapi-best-practices` recomenda.

**B. Por camada** (`app/routers/`, `app/services/`, `app/repositories/`), que é o que o
template oficial usa na prática: `app/api/routes/`, `app/core/`, `app/models.py`,
`app/crud.py`.

**C. Copiar o template oficial inteiro** e adaptar.

## Decisão

Fiquei com **B, por camada**.

O que decidiu foi ler a frase inteira da recomendação em vez do título dela:

> "Many example projects and tutorials organize projects by file type (e.g., crud,
> routers, models), which works well for microservices or smaller projects. However,
> this approach didn't scale well for our monolith with many domains and modules."

O critério não é "domínio é melhor". É porte e número de domínios. Este serviço é um
bounded context só (Pedidos e Estoque), que é literalmente o caso em que a própria
referência indica organizar por tipo. Organizar por domínio aqui produziria `app/produtos/`
com seis arquivos de uma classe cada.

A opção C eu descartei depois de olhar a árvore real do template: ele não tem Redis,
cache, fila nem worker, e os quatro são requisito desta prova. Ele serve como referência
de convenção, não como base.

## Consequências

O que eu ganho: a estrutura bate exatamente com a que descrevi na resposta teórica, e a
separação de camadas fica explícita para quem lê.

O que eu pago: se este serviço crescer para vários domínios no mesmo processo, essa
estrutura começa a incomodar. A migração é mecânica (as camadas já estão separadas, muda
só o eixo de agrupamento), mas é trabalho.

**Divergência que assumo:** o `fastapi-best-practices` coloca o SQL dentro de
`service.py` e não tem camada de repository. Mantive `repositories/` porque é ela que
permite testar service com repository mockado, sem Postgres no ar. Custa uma indireção a
mais e eu acho o custo justo.

## Como validei

Não confiei no README das referências. Listei a árvore real do template oficial:

```
$ curl -sL "https://api.github.com/repos/fastapi/full-stack-fastapi-template/git/trees/master?recursive=1" | ...
backend/app/api/routes/items.py
backend/app/api/routes/login.py
backend/app/core/config.py
backend/app/core/db.py
backend/app/crud.py
backend/app/models.py
```

Confirma duas coisas: ele organiza por tipo de arquivo (não por domínio), e não existe
nenhum módulo de Redis, cache ou worker na árvore.
