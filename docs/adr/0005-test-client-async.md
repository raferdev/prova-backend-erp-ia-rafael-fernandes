# ADR 0005 — Client de teste async desde o início

**Data:** 2026-08-19 · **Status:** aceito, substitui a escolha inicial

## Contexto

Escrevi os primeiros testes com o `TestClient` do Starlette, que é o caminho que a
documentação do FastAPI mostra e o que estava na minha frente. Funcionou: dois testes
passando no primeiro try.

Depois, lendo o `fastapi-best-practices`, encontrei a seção *"Set tests client async from
day 0"*, com um aviso direto: testes de integração com banco async e client síncrono
levam a erro de event loop mais adiante.

## Decisão

Trocar para `httpx.AsyncClient` com `ASGITransport`, e tornar os testes `async`.

Aceitei o argumento por dois motivos. O primeiro é que o custo de trocar cresce com o
número de testes: agora eram dois, e a migração levou minutos. Com o CRUD, o worker e a
parte assíncrona escritos, seria reescrever a suíte inteira. O segundo é que o problema
descrito é exatamente o que vou encontrar: a Parte 3 tem testes que tocam Postgres através
de uma engine async compartilhada, que é a receita do `attached to a different loop`.

Também troquei porque o `TestClient` estava emitindo um `DeprecationWarning` pedindo
`httpx2`. Não era a razão principal, mas a troca resolveu isso de brinde.

## Consequências

Ganho: a suíte não precisa ser reescrita quando entrarem testes de integração.

Pago: os testes ficam `async`, o que exige `asyncio_mode = "auto"` no pytest e um detalhe
que eu não sabia: o `ASGITransport` **não** executa o `lifespan` da aplicação. Para os
testes atuais isso é desejável, mas se algum dia eu depender de inicialização feita no
`lifespan`, o teste não vai vê-la. Está comentado no `conftest.py` para não me pegar
desprevenido depois.

## Como validei

```
$ uv run pytest
app/tests/test_health.py ..                                              [100%]
============================== 2 passed in 0.04s ===============================
```

Mesmos dois testes, mesmo comportamento verificado, agora async e sem warning.
