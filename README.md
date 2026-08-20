# Prova Técnica Back-end (ERP + IA) — Rafael Fernandes

Módulo de Pedidos e Estoque de um ERP, em FastAPI, conversando (conceitualmente) com os
módulos de Financeiro e Clientes.

Projeto em andamento. O que já está pronto e o que falta está em
[Progresso](#progresso), e o raciocínio por trás de cada escolha está em
[`docs/adr/`](docs/adr/).

O desafio de IA tem duas metades: a consulta em linguagem natural está implementada em
`POST /consultas/produtos` (parser determinístico, sem LLM em runtime), e o design de
agente com tool calling, MCP e guardrails está em
[`docs/parte-5-agente-ia.md`](docs/parte-5-agente-ia.md). O servidor MCP descrito nesse
documento também foi implementado — ver [Servidor MCP](#servidor-mcp).

## Como rodar

Precisa de Docker e Docker Compose.

```bash
cp .env.example .env
docker compose up --build
```

Sobem quatro containers na ordem certa, respeitando healthcheck. A API fica em
`http://localhost:8000`.

```
$ docker compose ps --format "table {{.Service}}\t{{.Status}}"
SERVICE    STATUS
api        Up 22 seconds (healthy)
postgres   Up 24 hours (healthy)
redis      Up 24 hours (healthy)
worker     Up 22 seconds (healthy)
```

O `worker` usa a mesma imagem da API com comando diferente, e reporta saúde pelo mecanismo
do próprio arq (`arq --check`).

Para conferir que a API alcança as dependências de verdade:

```
$ curl -s http://localhost:8000/health/ready
{"status":"ready","dependencies":[{"name":"postgres","healthy":true,"detail":null},{"name":"redis","healthy":true,"detail":null}]}
```

São dois endpoints de health, com propósitos diferentes: `/health` só diz que o processo
está de pé e não toca em dependência nenhuma, `/health/ready` checa Postgres e Redis e
devolve 503 se algum falhar. O porquê da separação está no
[ADR 0004](docs/adr/0004-liveness-separado-de-readiness.md).

A documentação interativa fica em `/docs`, e só em ambientes de desenvolvimento.

### Usando a API

Todas as rotas de `/produtos` exigem JWT. O token sai de `/auth/token`:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token \
  -d "username=admin@erp.local&password=admin123" | jq -r .access_token)

curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/produtos?nome=cabo&preco_max=50&pagina=1&tamanho=20"
```

| Rota | O que faz |
|---|---|
| `POST /auth/token` | autentica e devolve o JWT |
| `GET /produtos` | lista com filtros e paginação, servida de cache |
| `GET /produtos/{id}` | detalhe, servido de cache |
| `POST /produtos` | cria, invalida as listagens |
| `PATCH /produtos/{id}` | atualiza parcialmente, invalida detalhe e listagens |
| `DELETE /produtos/{id}` | remove, invalida detalhe e listagens |
| `POST /produtos/{id}/estoque` | enfileira uma movimentação, responde 202 com o `job_id` |
| `GET /produtos/{id}/movimentos` | histórico de movimentação do produto |
| `GET /alertas` | alertas de estoque baixo, abertos por padrão |
| `GET /integracoes/contexto-de-venda/{cliente_id}` | consulta três módulos em paralelo, degrada sem falhar |
| `POST /consultas/produtos` | pergunta em linguagem natural sobre o catálogo, sem LLM |

Filtros disponíveis na listagem: `nome` (busca parcial), `preco_min`, `preco_max`,
`ativo` e `apenas_estoque_baixo`. Este último compara `quantidade_estoque` com o
`estoque_minimo` de cada produto, porque o ponto de alerta não é um número global.

A movimentação de estoque responde 202 porque vai para a fila. É adequado para o que
tolera consistência eventual — reposição, ajuste de inventário, devolução. O caminho de
reserva de pedido, que precisa de resposta síncrona sob lock, não deve usar este endpoint;
está registrado no [ADR 0008](docs/adr/0008-worker-de-estoque.md).

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"delta":100,"motivo":"reposicao do fornecedor"}' \
  http://localhost:8000/produtos/$ID/estoque
```

### Servidor MCP

Expõe as ferramentas do ERP a um agente. Não chama LLM nenhum: quem chama modelo é o
cliente do outro lado, então isto não esbarra na restrição do enunciado.

```bash
uv run python -m app.mcp.servidor
```

| Ferramenta | Classe |
|---|---|
| `consultar_estoque` | leitura |
| `consultar_alertas` | leitura |
| `perguntar_sobre_catalogo` | leitura, usa o parser determinístico |
| `preparar_ajuste_estoque` | escrita, devolve preview e não altera nada |
| `confirmar_ajuste_estoque` | escrita, executa o preview confirmado |

Ele fala com a API por HTTP e JWT, e não com o banco direto. É o que faz o agente herdar
exatamente as permissões do token que carrega, em vez de virar um usuário robô com acesso
total. O raciocínio completo está no [ADR 0010](docs/adr/0010-servidor-mcp.md).

Ação destrutiva acontece em duas etapas: `preparar` devolve um preview com valores
resolvidos ("Baixar 3 unidades de Cabo HDMI 2m, saldo 120 ficará 117") e um token de dois
minutos; `confirmar` executa, e o token vale uma única vez. O preview é onde a alucinação
morre — se o modelo errou o produto, quem lê vê o nome errado antes de confirmar.

Para plugar num cliente MCP, aponte para o módulo:

```json
{
  "mcpServers": {
    "erp": {
      "command": "uv",
      "args": ["run", "--directory", "/caminho/para/o/repo", "python", "-m", "app.mcp.servidor"],
      "env": { "ERP_API_URL": "http://localhost:8000" }
    }
  }
}
```

### Migrações

O schema é responsabilidade do Alembic. A aplicação não cria tabelas no boot, para dev e
produção seguirem o mesmo caminho.

```bash
docker compose exec api alembic upgrade head
docker compose exec api python -m app.core.seed
```

O seed é idempotente: rodar duas vezes não duplica nada. Ele cria cinco produtos e um
usuário de desenvolvimento (`admin@erp.local` / `admin123`, sobrescrevíveis por
`SEED_USUARIO_EMAIL` e `SEED_USUARIO_SENHA`). Não é usuário de produção.

Para criar uma migração nova:

```bash
docker compose exec api alembic revision --autogenerate -m "cria tabela produto"
```

O slug é obrigatório e vira o nome do arquivo:
`alembic/versions/2026-08-19_cria_tabela_produto.py`.

Rodando do host em vez do container, o `POSTGRES_HOST` do `.env` aponta para o hostname do
Compose e não resolve. Prefixe: `POSTGRES_HOST=localhost uv run alembic upgrade head`.

### Desenvolvimento local

O projeto usa [uv](https://docs.astral.sh/uv/):

```bash
uv sync
uv run uvicorn main:app --reload
```

## Estrutura

O fluxo é sempre `router → service → repository`, sem atalhos.

```
app/
  routers/       # endpoints HTTP: recebem o request, chamam o service, devolvem a response
  services/      # regra de negócio, testável isoladamente (mockando o repository)
  repositories/  # único ponto que fala com o banco
  schemas/       # modelos Pydantic (contrato da API)
  models/        # modelos do ORM (tabelas)
  core/          # config, conexão de banco, Redis, segurança/JWT
  workers/       # tarefas de fila
  integracoes/   # gateways para outros modulos do ERP (Clientes, Financeiro, Logistica)
  mcp/           # servidor MCP: expoe ferramentas do ERP a um agente
  tests/         # espelha a estrutura acima
main.py          # monta a aplicação e registra os routers
docs/adr/        # registro de decisões
```

Cada camada tem um motivo para mudar e só um: trocar de banco mexe em `repositories/`,
mudar o contrato da API mexe em `schemas/`, regra nova mexe em `services/`. O service
depende de uma abstração de repository e não da sessão do SQLAlchemy, que é o que permite
testar regra de negócio sem subir Postgres.

`schemas/` fica separado de `models/` de propósito: o contrato público da API não é o
schema do banco. Fundir os dois faz qualquer coluna nova vazar para a resposta por padrão.

Comparei essa estrutura com o template oficial do FastAPI e com o
`fastapi-best-practices` antes de fechar. O raciocínio, incluindo por que não organizei
por domínio, está no [ADR 0001](docs/adr/0001-estrutura-em-camadas.md).

## Respostas teóricas

| Parte | Onde | Sobre |
|---|---|---|
| 1 | [Arquitetura](docs/parte-1-arquitetura.md) | bounded contexts, síncrono vs assíncrono, Saga, Redis, gateway, observabilidade, AWS |
| 5 | [Agente de IA](docs/parte-5-agente-ia.md) | tool calling, MCP, guardrails, custo e latência |
| 6 | [Perfil](docs/parte-6-perfil.md) | o cenário da frente em Go |
| 7 | [Portfólio](docs/parte-7-portfolio.md) | projeto representativo e o que eu faria diferente |

A Parte 3 teórica está distribuída pelos ADRs, que é onde cada decisão de implementação foi
tomada e justificada.

Na Parte 1 eu amarro cada afirmação a código deste repositório sempre que existe, e digo
explicitamente quando não existe — o lock distribuído do oversell, por exemplo, está
desenhado e não implementado.

## Decisões

Cada decisão tem um registro em [`docs/adr/`](docs/adr/) com o contexto, as alternativas
que descartei, o que estou pagando pela escolha e a saída do comando que usei para
validar.

| # | Decisão |
|---|---|
| [0001](docs/adr/0001-estrutura-em-camadas.md) | Organizar por camada, não por domínio |
| [0002](docs/adr/0002-persistencia-sqlalchemy-async.md) | SQLAlchemy 2.0 async + Alembic, descartando SQLModel |
| [0003](docs/adr/0003-fila-com-arq.md) | `arq` como fila, descartando Celery, RQ e `BackgroundTasks` |
| [0004](docs/adr/0004-liveness-separado-de-readiness.md) | Separar liveness de readiness |
| [0005](docs/adr/0005-test-client-async.md) | Client de teste async desde o início |
| [0006](docs/adr/0006-convencoes-de-migration.md) | Fixar convenções antes da primeira migration |
| [0007](docs/adr/0007-estrategia-de-cache.md) | Cache do catálogo, invalidação por namespace versionado |
| [0008](docs/adr/0008-worker-de-estoque.md) | Worker de estoque: movimentação idempotente e alerta |
| [0009](docs/adr/0009-consulta-paralela-degradacao.md) | Consulta paralela com degradação graciosa |
| [0010](docs/adr/0010-servidor-mcp.md) | Servidor MCP funcional sobre a API do ERP |

Duas coisas que não têm ADR próprio porque não tiveram alternativa real em disputa:

O Redis faz três papéis aqui, e é bom deixar explícito porque normalmente se lembra só do
primeiro: cache de leitura quente do catálogo, broker do worker, e lock distribuído para
evitar oversell quando dois pedidos disputam a última unidade em estoque.

A configuração é validada no import, via `pydantic-settings`. Se faltar variável
obrigatória a aplicação não sobe, em vez de quebrar no primeiro request em produção.
Nenhum segredo é commitado, e o `.env.example` documenta as chaves.

## Testes

```
$ uv run pytest -q
126 passed in 9.63s

$ uv run pytest --cov=app --cov=main --cov-report=term | tail -1
TOTAL   2163   222   90%
```

A CI roda isso em todo pull request, com Postgres e Redis de verdade como `services`, mais
o build da imagem e um `docker compose up` que autentica e chama uma rota protegida. O
workflow está em [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

A suíte tem dois tipos de teste, e a distinção foi aprendida errando.

A maioria roda sem infraestrutura: regra de negócio e política de cache exercitadas com
repository dublado e Redis em memória (`app/tests/dubles.py`). É rápido e é o argumento
prático a favor da camada `repositories/`. O client é `httpx.AsyncClient` sobre
`ASGITransport`, falando direto com o app sem abrir porta.

Já `test_integracao_alerta.py` precisa de Postgres, e existe porque um dublê não pode
provar garantia de banco. O `ON CONFLICT` do alerta estava escrito de um jeito que o
Postgres recusa, e o dublê passava tranquilo: ele reimplementa o invariante em Python, ou
seja, validava a minha intenção em vez do meu SQL. Esses testes pulam sozinhos quando não
há banco acessível, para não quebrar a suíte rápida.

O `ruff` está configurado com a regra `ASYNC`, que pega chamada bloqueante dentro de rota
`async`. É a armadilha número um do FastAPI e não existe equivalente no Node, então
prefiro que o linter cuide disso e não a minha memória.

## Progresso

| Parte | Situação |
|---|---|
| Fundação: repo, esqueleto, Docker, health | pronto |
| Parte 3 — CRUD Produtos/Estoque | pronto: CRUD, validação, JWT, filtros, paginação, cache e worker |
| Parte 4 — Docker | pronto: quatro serviços com healthcheck, Alembic e seed |
| Parte 2 — Assíncrono (Q4) | pronto: `asyncio.gather`, timeout por fonte, orçamento total e retry |
| Parte 5 — Desafio de IA (Q8 e Q9) | pronto: parser determinístico, [design do agente](docs/parte-5-agente-ia.md) e servidor MCP funcional |
| Parte 1 — Arquitetura (teórica) | pronto: [docs/parte-1-arquitetura.md](docs/parte-1-arquitetura.md) |
| Parte 6 — Perfil | pronto: [docs/parte-6-perfil.md](docs/parte-6-perfil.md) |
| Parte 7 — Portfólio | **incompleto**: estrutura pronta, faltam os links e o projeto |

O que ficou de fora por escolha, e não por falta de tempo: o lock distribuído para oversell
na reserva de pedido. Ele pertence ao módulo de Pedidos, não ao de Estoque, e está anotado
como limite explícito no [ADR 0008](docs/adr/0008-worker-de-estoque.md). O `UPDATE` atômico
que uso na movimentação resolve perda de atualização, mas não substitui o lock quando a
decisão de negócio depende de ler o saldo antes de decidir.

## Uso de IA

Meu histórico é Node, NestJS e TypeScript. Python não é minha stack principal, e prefiro
dizer isso direto do que deixar transparecer.

A arquitetura e as decisões são minhas. A separação em camadas, o fluxo
`router → service → repository` e a justificativa de cada escolha vêm de NestJS, onde o
modelo é praticamente o mesmo: módulos, injeção de dependência, DTOs validados. O que eu
não tinha era o mapa do ecossistema Python, e é aí que usei IA: qual biblioteca ocupa o
lugar do TypeORM, qual é o BullMQ daqui, qual é a pegadinha idiomática de cada uma.

Usei IA também para verificar referências, não para aceitá-las. Ao avaliar o template
oficial do FastAPI e o `fastapi-best-practices`, o que mudou minha conclusão foi listar a
árvore real dos repositórios em vez de ler o resumo: descobri que o template oficial não
tem Redis, fila nem worker, e que a recomendação de organizar por domínio é condicionada
a monolitos. Foi assim que SQLModel e Celery foram descartados, mesmo aparecendo como
opções óbvias.

Cada sugestão passou por execução antes de entrar. As saídas de comando espalhadas neste
README e nos ADRs são reais, não ilustrativas. Onde eu ainda não validei, está escrito que
não validei: o [ADR 0003](docs/adr/0003-fila-com-arq.md) registra a escolha do `arq` sem
seção de validação, porque o worker ainda não existe.

Uma coisa que mudei de ideia no meio do caminho está registrada no
[ADR 0005](docs/adr/0005-test-client-async.md): comecei os testes com o client síncrono,
que é o que a documentação do FastAPI mostra, e troquei depois de entender que isso
quebraria os testes de integração mais adiante.

Quatro defeitos meus aparecem documentados neste repositório, e nenhum deles quebrava algo
de forma visível — que é justamente por que estão registrados.

Tratar a chave de versão do cache como `1` quando ausente fazia a primeira invalidação não
invalidar nada, já que `INCR` numa chave inexistente também resulta em `1`
([ADR 0007](docs/adr/0007-estrategia-de-cache.md)). O FastAPI aceita só um modelo Pydantic
por endpoint como query string, e com dois ele silenciosamente passa a exigir query params
chamados `filtros` e `paginacao`. Configurei retentativas no worker antes de perceber que a
movimentação de estoque não era idempotente, o que faria uma reentrega da fila baixar o
mesmo estoque duas vezes ([ADR 0008](docs/adr/0008-worker-de-estoque.md)). E escrevi o
`ON CONFLICT` do alerta com uma expressão do ORM que o Postgres recusa, erro que só
apareceu quando o worker rodou de verdade.

Esse último é o mais instrutivo, e mudou como eu testo: o dublê de repository passava
tranquilo porque reimplementa o invariante em Python, ou seja, validava a minha intenção em
vez do meu SQL. Foi o que me levou a separar testes de integração contra Postgres real dos
testes rápidos com dublê.

Todos os quatro viraram teste para não voltarem.
