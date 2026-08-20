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

A primeira migration foi gerada e as três decisões apareceram nela.

O nome do arquivo saiu legível, com a data e o slug:

```
Generating alembic/versions/2026-08-20_cria_tabelas_produto_e_usuario.py ... done
```

O autogenerate nomeou tudo pela convenção, em vez de deixar nome automático:

```
sa.CheckConstraint('preco >= 0', name=op.f('produto_preco_nao_negativo_check')),
sa.PrimaryKeyConstraint('id', name=op.f('produto_pkey'))
op.create_index(op.f('produto_nome_idx'), 'produto', ['nome'])
```

Nome bonito, porém, não prova reversibilidade. O que prova é o round-trip completo:

```
$ alembic upgrade head
INFO  Running upgrade  -> 16f29a063f8e, cria tabelas produto e usuario
$ alembic downgrade base
INFO  Running downgrade 16f29a063f8e -> , cria tabelas produto e usuario
$ alembic upgrade head
INFO  Running upgrade  -> 16f29a063f8e, cria tabelas produto e usuario
```

Sobe, desce até o vazio e sobe de novo, sem erro. E as constraints existem no banco com o
nome previsto:

```
$ psql -U erp -d erp -c "\d produto"
Indexes:
    "produto_pkey" PRIMARY KEY, btree (id)
    "produto_nome_idx" btree (nome)
Check constraints:
    "produto_estoque_nao_negativo_check" CHECK (quantidade_estoque >= 0)
    "produto_preco_nao_negativo_check" CHECK (preco >= 0::numeric)
```
