# ADR 0004 — Separar liveness de readiness

**Data:** 2026-08-19 · **Status:** aceito

## Contexto

Precisava de um `/health` para o healthcheck do Compose. A implementação óbvia é um
endpoint que checa Postgres e Redis e devolve 200 se ambos respondem.

## Decisão

Dois endpoints, com propósitos diferentes:

- `GET /health` não toca em dependência nenhuma. Responde se o processo está de pé.
- `GET /health/ready` checa Postgres e Redis e devolve 503 se algum falhar, dizendo qual.

O motivo é que o endpoint óbvio tem um efeito colateral ruim. O orquestrador usa liveness
para decidir **reiniciar** o container. Se o liveness consultasse o banco, uma queda do
Postgres colocaria a API inteira em loop de restart, por um problema que não é dela, e
que restart nenhum resolve. Pior: ela reiniciaria justo quando o banco voltasse e as
conexões precisassem ser reestabelecidas com calma.

Readiness é a pergunta diferente: "posso receber tráfego agora?". Falha ali significa
"me tire do balanceador", não "me mate".

## Consequências

Dois endpoints em vez de um, e a necessidade de lembrar qual vai em qual lugar do
orquestrador. O `docker-compose.yml` aponta o healthcheck para `/health`, de propósito.

O readiness devolve o erro de cada dependência no corpo da resposta. Isso é ótimo para
debug e é informação interna: se este serviço ficasse exposto sem gateway na frente, essa
resposta precisaria ser enxugada.

## Como validei

Com tudo no ar:

```
$ curl -s http://localhost:8000/health/ready
{"status":"ready","dependencies":[{"name":"postgres","healthy":true,"detail":null},{"name":"redis","healthy":true,"detail":null}]}
```

E o caminho de falha, que é o que realmente importa: existe um teste que roda **sem**
Postgres e Redis no ar e verifica que a resposta é 503 degradado com as duas dependências
listadas, em vez de um 500 genérico
(`app/tests/test_health.py::test_readiness_reporta_dependencias_indisponiveis`).
