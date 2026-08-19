# ADR 0002 — SQLAlchemy 2.0 async + Alembic como camada de persistência

**Data:** 2026-08-19 · **Status:** aceito

## Contexto

Precisava escolher ORM. No mundo Node eu usaria TypeORM ou Prisma, e a pergunta que fiz
foi qual é o equivalente com a mesma maturidade em Python, considerando que a aplicação é
async e que a prova pede Postgres.

## Opções que considerei

**SQLModel.** É o que o template oficial do FastAPI usa, e é do mesmo autor do FastAPI.
Sintaxe muito boa.

**SQLAlchemy 2.0** com driver `asyncpg`.

**Tortoise ORM.** Async nativo, API parecida com a do Django.

## Decisão

SQLAlchemy 2.0 com `asyncpg`, e Alembic para migrations.

Descartei o SQLModel por um motivo específico: ele funde o model do ORM e o schema da API
na mesma classe. Isso é conveniente e é exatamente o que eu não quero aqui, porque a
estrutura que defini no [ADR 0001](0001-estrutura-em-camadas.md) separa `schemas/` de
`models/`. Com classe única, qualquer coluna nova que eu adicionar na tabela vaza para a
resposta da API por padrão. Num ERP isso é caminho para expor custo de compra num endpoint
de catálogo.

Tortoise eu descartei por maturidade e tamanho de ecossistema, não por defeito técnico.

Ponto que decidi junto: a aplicação **não** cria tabelas no boot. `create_all()` é
confortável em dev e insustentável em produção, e ter dois caminhos diferentes de criação
de schema entre dev e prod é como se descobre em produção que faltava um índice. O
`lifespan` em `main.py` está deliberadamente vazio disso.

## Consequências

Ganho: `async` de ponta a ponta, sem bloquear o event loop num serviço que é quase todo
I/O. E migrations versionadas de verdade.

Pago: SQLAlchemy 2.0 async tem mais cerimônia que SQLModel. `expire_on_commit=False` na
sessão é um exemplo — sem isso, ler um atributo do objeto depois do commit dispara um
SELECT novo, que em contexto async vira erro num lugar inesperado. É o tipo de detalhe
que eu não teria antecipado vindo de TypeORM, e que está comentado no código.

## Como validei

Alembic conectando no Postgres do Compose, com a URL vinda das settings da aplicação:

```
$ POSTGRES_HOST=localhost uv run alembic current
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
```

Sem revisão aplicada ainda, que é o esperado nesse ponto. O que isso prova é que a
configuração conecta e que o dialeto reconhecido é Postgres, não SQLite por engano.
