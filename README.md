# Prova Técnica Back-end (ERP + IA) — Rafael Fernandes

Módulo de Pedidos e Estoque de um ERP, em FastAPI, conversando (conceitualmente) com os
módulos de Financeiro e Clientes.

Projeto em andamento. O que já está pronto e o que falta está em
[Progresso](#progresso), e o raciocínio por trás de cada escolha está em
[`docs/adr/`](docs/adr/).

## Como rodar

Precisa de Docker e Docker Compose.

```bash
cp .env.example .env
docker compose up --build
```

Sobem três containers na ordem certa, respeitando healthcheck. A API fica em
`http://localhost:8000`.

```
$ docker compose ps --format "table {{.Service}}\t{{.Status}}"
SERVICE    STATUS
api        Up About an hour (healthy)
postgres   Up About an hour (healthy)
redis      Up About an hour (healthy)
```

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

Filtros disponíveis na listagem: `nome` (busca parcial), `preco_min`, `preco_max`,
`ativo` e `apenas_estoque_baixo`. Este último compara `quantidade_estoque` com o
`estoque_minimo` de cada produto, porque o ponto de alerta não é um número global.

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
.................................                                        [100%]
33 passed in 0.14s

$ uv run ruff check .
All checks passed!
```

Nenhum teste precisa de Postgres ou Redis no ar. A política de cache inteira é exercitada
com um repository dublado e um Redis em memória (`app/tests/dubles.py`), que é o argumento
prático a favor da camada `repositories/`.

A ideia é testar regra de negócio isolada, com repository mockado, e manter os testes sem
dependência de infra sempre que o alvo do teste não for a própria infra. O client é
`httpx.AsyncClient` sobre `ASGITransport`, falando direto com o app sem abrir porta.

O `ruff` está configurado com a regra `ASYNC`, que pega chamada bloqueante dentro de rota
`async`. É a armadilha número um do FastAPI e não existe equivalente no Node, então
prefiro que o linter cuide disso e não a minha memória.

## Progresso

| Parte | Situação |
|---|---|
| Fundação: repo, esqueleto, Docker, health | pronto |
| Parte 3 — CRUD Produtos/Estoque | CRUD, validação, JWT, filtros, paginação e cache prontos; falta o worker |
| Parte 4 — Docker | Compose, Alembic e seed prontos; falta o serviço `worker` |
| Parte 2 — Assíncrono (Q4) | não iniciado |
| Parte 5 — Desafio de IA (Q8 e Q9) | não iniciado |
| Parte 1 — Arquitetura (teórica) | não iniciado |
| Parte 6 — Perfil | não iniciado |
| Parte 7 — Portfólio | não iniciado |

O que falta na Parte 3 é o worker de fila. Ele já tem lugar reservado: a invalidação de
cache mora em `app/core/cache.py` justamente para o worker chamar sem passar por router,
e o `arq` foi escolhido no [ADR 0003](docs/adr/0003-fila-com-arq.md), que segue sem seção
de validação até a tarefa existir de verdade.

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

Dois defeitos que apareceram na implementação do cache e que valem ser ditos, porque
nenhum dos dois quebrava nada de forma visível. O primeiro está descrito no
[ADR 0007](docs/adr/0007-estrategia-de-cache.md): tratar a chave de versão ausente como
`1` fazia a primeira invalidação não invalidar nada, já que `INCR` numa chave inexistente
também resulta em `1`. O segundo é a armadilha do FastAPI de aceitar apenas um modelo
Pydantic por endpoint como query string — com dois, ele silenciosamente passa a exigir
query params chamados `filtros` e `paginacao`. Os dois viraram teste
(`test_produto_cache.py` e `test_produtos_contrato.py`) para não voltarem.
