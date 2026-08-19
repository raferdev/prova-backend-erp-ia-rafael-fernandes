# ADR 0006 — Fixar convenções antes da primeira migration

**Data:** 2026-08-19 · **Status:** aceito

## Contexto

O CRUD da Parte 3 vai gerar a primeira migration. Duas configurações do Alembic e do
SQLAlchemy só têm efeito sobre migrations criadas **depois** delas, então ou entram agora
ou o histórico nasce inconsistente.

## Decisão

Três coisas, antes de qualquer `alembic revision`.

**1. Naming convention de índices e constraints** no `metadata` do `Base`
(`app/core/database.py`). Sem isso, o SQLAlchemy nomeia constraints com o esquema dele, e
algumas ficam sem nome previsível. Importa porque o `downgrade` de uma migration gera
`DROP CONSTRAINT <nome>`: se o nome não for determinístico, a migration sobe e não desce.
Migration que não reverte é a que te deixa preso às 3h da manhã.

**2. `file_template` no `alembic.ini`**, no formato `2026-08-19_cria_tabela_produto.py`.
O padrão do Alembic nomeia por hash de revisão, o que torna o diretório de migrations
ilegível em code review. O slug passa a ser obrigatório e tem que descrever a mudança.

**3. Tirar o DSN do `alembic.ini`.** O `alembic init` gera um
`sqlalchemy.url = driver://user:pass@localhost/dbname` no arquivo, que é versionado. Removi
a chave e passei a montar a URL no `env.py` a partir das mesmas settings da aplicação.
Fonte única de credencial, e nenhuma senha em arquivo commitado.

Aproveitei e liguei `compare_type=True` no `env.py`. Vem desligado por padrão, o que faz o
autogenerate ignorar em silêncio uma coluna que mudou de `NUMERIC(10,2)` para
`NUMERIC(12,2)`. Num sistema com valor monetário isso não pode passar despercebido.

## Consequências

Nenhum custo real, desde que feito agora. Feito depois, exigiria migration manual para
renomear constraints existentes.

Um efeito prático a registrar: como a URL vem das settings, rodar `alembic` a partir do
host esbarra no `POSTGRES_HOST=postgres` do `.env`, que é o hostname do Compose e não
resolve fora dele. Ou roda dentro do container, ou prefixa com
`POSTGRES_HOST=localhost`. Não é elegante e é o preço de ter uma fonte de config só;
prefiro assim do que ter um DSN duplicado que sai de sincronia.

## Como validei

```
$ POSTGRES_HOST=localhost uv run alembic current
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
```

Conecta e reconhece o dialeto Postgres, com a URL vinda das settings e nenhum DSN no
`alembic.ini`. A prova real das convenções de nome vem com a primeira migration gerada,
na Parte 3.
