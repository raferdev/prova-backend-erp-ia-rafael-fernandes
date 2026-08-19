# Prova Técnica Back-end (ERP + IA) — Rafael Fernandes

Módulo de **Pedidos e Estoque** de um ERP, construído em FastAPI, integrando-se
(conceitualmente) aos módulos de Financeiro e Clientes.

> **Status:** em construção. A seção [O que ainda não foi feito](#o-que-ainda-não-foi-feito)
> lista o que falta e como eu faria — conforme pedido no enunciado.

---

## Sumário

- [Como rodar](#como-rodar)
- [Estrutura de pastas](#estrutura-de-pastas)
- [Referências consultadas e o que foi adotado](#referências-consultadas-e-o-que-foi-adotado)
- [Decisões técnicas (o porquê)](#decisões-técnicas-o-porquê)
- [Testes](#testes)
- [O que ainda não foi feito](#o-que-ainda-não-foi-feito)
- [Uso de IA](#uso-de-ia)

---

## Como rodar

Pré-requisitos: Docker e Docker Compose.

```bash
cp .env.example .env
docker compose up --build
```

Isso sobe três containers — `postgres`, `redis` e `api` — nesta ordem, respeitando
healthchecks. A API fica em `http://localhost:8000`.

| Endpoint | Para quê |
|---|---|
| `GET /health` | *Liveness*: o processo está de pé. Não toca em dependência nenhuma. |
| `GET /health/ready` | *Readiness*: Postgres e Redis respondem? Retorna `503` se algum falhar. |
| `GET /docs` | Swagger UI gerado pelo FastAPI. |

Verificação rápida:

```bash
curl http://localhost:8000/health/ready
```

### Migrações

O schema é responsabilidade do Alembic — a aplicação **não** cria tabelas no boot, para
que desenvolvimento e produção sigam exatamente o mesmo caminho.

```bash
docker compose exec api alembic upgrade head
```

Para criar uma migração nova (o slug é obrigatório e deve descrever a mudança):

```bash
docker compose exec api alembic revision --autogenerate -m "cria tabela produto"
```

Os arquivos nascem como `alembic/versions/2026-08-19_cria_tabela_produto.py`.

> Rodando do host em vez do container, o `POSTGRES_HOST` do `.env` aponta para o hostname
> do Compose. Prefixe com o override: `POSTGRES_HOST=localhost uv run alembic upgrade head`.

### Rodando fora do Docker (desenvolvimento)

O projeto usa [uv](https://docs.astral.sh/uv/) como gerenciador de dependências:

```bash
uv sync
uv run uvicorn main:app --reload
```

---

## Estrutura de pastas

O fluxo é sempre **`router → service → repository`**, sem atalhos.

```
app/
  routers/       # endpoints HTTP: recebem o request, chamam o service, devolvem a response
  services/      # regra de negócio; testável isoladamente (mockando o repository)
  repositories/  # único ponto que fala com o banco; isola a persistência
  schemas/       # modelos Pydantic (contrato da API — entrada e saída)
  models/        # modelos do ORM (tabelas)
  core/          # config, conexão de banco, Redis, segurança/JWT
  workers/       # tarefas de fila / background
  tests/         # espelha a estrutura acima
main.py          # entrypoint: monta a aplicação e registra os routers
```

**Por que assim:**

- **Single Responsibility (SOLID):** cada camada tem um motivo para mudar. Uma troca de
  banco mexe em `repositories/`; uma mudança de contrato da API mexe em `schemas/`; uma
  regra de negócio nova mexe em `services/`. Elas não se contaminam.
- **Dependency Inversion:** o service depende de uma abstração de repository, não da
  sessão do SQLAlchemy. É por isso que dá para testar regra de negócio sem subir Postgres.
- **Clean Architecture:** a regra de negócio não sabe se o dado veio de Postgres, de um
  arquivo ou de outro serviço. Infra é detalhe, e detalhe fica na borda.
- **`schemas/` separado de `models/`:** o contrato público da API não é o schema do banco.
  Fundir os dois (ex.: SQLModel) é conveniente e vaza detalhe de persistência para fora.

`main.py` fica na raiz, fora de `app/`, exatamente como descrito acima — a coerência
entre a estrutura documentada e a real é intencional.

---

## Referências consultadas e o que foi adotado

Antes de escrever o CRUD, comparei esta estrutura com duas referências conhecidas da
comunidade, para não reinventar convenção nem carregar decisão sem justificativa.

### 1. [`fastapi/full-stack-fastapi-template`](https://github.com/fastapi/full-stack-fastapi-template) — o template oficial

Estrutura real do backend: `app/api/routes/`, `app/core/`, `app/models.py`, `app/crud.py`
— ou seja, **organizado por tipo de arquivo**, como o deste projeto.

**O que eu não trouxe, e por quê:**

- **SQLModel.** O template funde model do ORM e schema da API na mesma classe. É
  conveniente, mas acopla o contrato público ao schema do banco — qualquer coluna nova
  vaza para a API por padrão. Este projeto mantém `schemas/` e `models/` separados.
- **`crud.py` achatado.** Um único arquivo com todo o acesso a dados. Funciona no escopo
  do template, mas elimina a inversão de dependência: sem uma abstração de repository,
  testar regra de negócio exige banco de verdade.
- O template **não tem Redis, cache, fila nem worker.** O escopo desta prova exige os
  quatro, então ele não serve como base — serve como referência de convenção.

### 2. [`zhanymkanov/fastapi-best-practices`](https://github.com/zhanymkanov/fastapi-best-practices)

Esta é a referência que recomenda organizar **por domínio** (`src/auth/`, `src/posts/`),
inspirada no Dispatch da Netflix — aparentemente o oposto do que fiz aqui. Vale ler a
frase completa:

> "Many example projects and tutorials organize projects by file type (e.g., crud,
> routers, models), **which works well for microservices or smaller projects.** However,
> this approach didn't scale well for **our monolith with many domains and modules.**"

O critério da recomendação não é "domínio é sempre melhor", é **porte e número de
domínios**. A entrega aqui é um microsserviço de **um** bounded context (Pedidos e
Estoque) — exatamente o caso em que a própria referência indica organizar por tipo.

Organizar este projeto por domínio criaria `app/produtos/` com um arquivo de uma classe
cada, e ainda entraria em conflito com a estrutura definida na resposta teórica. A
estrutura por camadas fica, **e agora fica justificada**: quando este módulo crescer para
vários domínios dentro do mesmo processo, a migração para pastas por domínio é o próximo
passo natural — as camadas já estão separadas, muda só o eixo de agrupamento.

### O que foi adotado dessa referência

Priorizei o que é **caro de mudar depois** — decisões de "dia 0":

| Prática | Onde | Por que agora e não depois |
|---|---|---|
| Test client **async** | [`app/tests/conftest.py`](app/tests/conftest.py) | A referência alerta que o client síncrono gera erro de event loop quando entram testes com banco async. Trocar depois = reescrever todos os testes. |
| **Naming convention** de índices/constraints | [`app/core/database.py`](app/core/database.py) | Precisa existir **antes da 1ª migration**. Alembic gera `DROP CONSTRAINT <nome>`; nome auto-gerado produz migration que não reverte. |
| `file_template` do Alembic | [`alembic.ini`](alembic.ini) | Idem — as migrations já nascem como `2026-08-19_descricao.py` em vez de hash aleatório. |
| Base Pydantic customizada | [`app/schemas/base.py`](app/schemas/base.py) | Padroniza `datetime` com timezone explícito em toda a API. Num ERP, data de pedido e de faturamento sem fuso é defeito. |
| Docs escondidos fora de dev | [`main.py`](main.py) | `/docs` em produção entrega o mapa da API para reconhecimento. |
| **Ruff** configurado | [`pyproject.toml`](pyproject.toml) | Inclui a regra `ASYNC`, que detecta chamada bloqueante dentro de rota `async` — a armadilha nº 1 do FastAPI, descrita na própria referência. |

Convenções adotadas para as próximas partes: validação de existência via **dependências**
(`valid_produto_id`) em vez de repetir o mesmo `if not found` em cada endpoint;
`dependency_overrides` para trocar auth nos testes; `response_model`/`status_code`
explícitos; e SQL-first — agregação e filtro no banco, não em laço Python.

**Uma divergência assumida:** a referência coloca o SQL dentro de `service.py` e não tem
camada de repository. Mantive `repositories/` porque a separação é o que permite testar
service com repository mockado, sem Postgres no ar. O custo é uma camada a mais de
indireção; a troco de testes de regra de negócio que rodam em milissegundos.

### Sobre `BackgroundTasks` vs fila de verdade

A referência tem uma seção específica sobre isso, e ela **confirma a escolha do `arq`**:
`BackgroundTasks` roda no mesmo processo do worker web, sem retry e sem visibilidade — se
o processo morre, a tarefa desaparece. A regra prática citada é a que eu sigo aqui: *se
você seria acordado de madrugada porque a tarefa se perdeu, ela não pertence a
`BackgroundTasks`*. Baixa de estoque e recálculo em um ERP se encaixam nisso.

---

## Decisões técnicas (o porquê)

### SQLAlchemy 2.0 (async) como ORM

Alternativas consideradas: SQLModel, Tortoise ORM, SQL puro.

- **`async` nativo** com driver `asyncpg`. Num serviço que é majoritariamente I/O-bound
  (banco, Redis, chamadas HTTP a outros módulos), ORM síncrono bloquearia o event loop
  do FastAPI e jogaria fora a vantagem do framework.
- **Alembic** dá migrations versionadas de verdade. `create_all()` no boot é confortável
  em dev e insustentável em produção — por isso o `lifespan` da aplicação
  deliberadamente **não** cria tabelas.
- **SQLModel foi descartado** pelo motivo já citado: funde `schemas/` e `models/`.

### arq como worker de fila

Alternativas consideradas: Celery, RQ, Dramatiq.

- **Async-nativo:** roda no mesmo modelo de concorrência do resto da aplicação. Com RQ
  (síncrono) eu teria dois modelos de concorrência convivendo no mesmo repositório.
- **Só precisa do Redis**, que já está no stack por causa do cache e dos locks. Celery
  traria configuração e vocabulário (brokers, backends, pools) desproporcionais ao escopo.

### Redis com três papéis distintos

1. **Cache** de leituras quentes (catálogo de produtos).
2. **Broker** do worker de background.
3. **Lock distribuído**, para evitar *oversell* quando dois pedidos disputam a última
   unidade em estoque — o caso mais crítico deste domínio.

### `uv` em vez de pip

Resolução de dependências ordens de magnitude mais rápida e `uv.lock` determinístico, o
que torna o build Docker reproduzível.

### Liveness separado de readiness

`/health` não consulta Postgres nem Redis, de propósito. Se consultasse, uma queda do
banco faria o orquestrador **reiniciar a API em loop** — quando o problema não é a API.
`/health/ready` é que checa dependências: uma falha ali significa "não me mande tráfego
agora", não "me mate".

### Docker

- **Multi-stage:** o estágio de build carrega o toolchain; o de runtime leva apenas o
  virtualenv pronto e o código. Imagem final menor e com menor superfície de ataque.
- **Usuário sem privilégios** (`appuser`), o container não roda como root.
- **Camadas ordenadas por volatilidade:** manifestos de dependência são copiados antes do
  código, então mudar código não invalida o cache de instalação das dependências.
- **`depends_on: condition: service_healthy`:** sem isso o Compose considera "pronto" um
  container que apenas *iniciou*, e a API tentaria conectar antes do Postgres aceitar
  conexões.

### Configuração

`pydantic-settings` valida a config **no import**. Se faltar uma variável obrigatória, a
aplicação não sobe — em vez de quebrar no primeiro request em produção. Nenhum segredo é
commitado; `.env.example` documenta as chaves necessárias.

---

## Testes

```bash
uv run pytest
```

Lint e formatação:

```bash
uv run ruff check --fix . && uv run ruff format .
```

A estratégia é testar **regra de negócio isoladamente** (mockando repositories) e manter
os testes livres de dependência de infraestrutura sempre que o alvo do teste não for a
própria infraestrutura.

O client de teste é **async desde o primeiro teste** (`httpx.AsyncClient` +
`ASGITransport`), falando direto com o app ASGI sem abrir porta de rede.

---

## O que ainda não foi feito

Esta seção é atualizada conforme o projeto avança.

| Parte | Status | Observação |
|---|---|---|
| Fundação (repo, esqueleto, Docker, `/health`) | ✅ feito | |
| Parte 3 — CRUD Produtos/Estoque | ⏳ pendente | validação Pydantic, JWT, paginação/filtros, cache Redis, worker |
| Parte 2 — Assíncrono (Q4) | ⏳ pendente | `asyncio.gather` com timeout individual e degradação graciosa |
| Parte 5 — Desafio de IA | ⏳ pendente | parser determinístico (Q8) + design de tool calling/MCP (Q9) |
| Parte 4 — Docker completo | 🟡 parcial | Alembic já configurado; falta o serviço `worker` no Compose e o seed |
| Parte 1 — Arquitetura (teórica) | ⏳ pendente | |
| Parte 6 — Perfil | ⏳ pendente | |
| Parte 7 — Portfólio | ⏳ pendente | |

---

## Uso de IA

Meu histórico é **Node/NestJS/TypeScript**; Python não é minha stack principal. Isso é
relevante e prefiro declarar de forma direta em vez de esconder.

O que isso significou na prática, até aqui:

- **A arquitetura e as decisões são minhas.** A separação em camadas, o fluxo
  `router → service → repository` e a justificativa de cada escolha vêm da experiência com
  NestJS, onde o modelo é praticamente o mesmo (módulos, injeção de dependência,
  DTOs validados).
- **Usei IA como tradutor de ecossistema.** As perguntas que eu não teria respondido
  sozinho com rapidez eram do tipo "qual é o SQLAlchemy do mundo Python?", "o equivalente
  de BullMQ aqui é o quê?", "qual a pegadinha idiomática disso". Cada sugestão foi
  avaliada por mim contra o critério da prova — foi assim que SQLModel e Celery foram
  descartados, apesar de aparecerem como opções.
- **Usei IA para verificar referências, não para aceitá-las.** Ao avaliar o template
  oficial do FastAPI e o `fastapi-best-practices`, a conclusão mais útil veio de checar a
  estrutura real dos repositórios em vez do resumo: o template oficial não tem Redis, fila
  nem worker, e a recomendação de organizar por domínio é condicionada a monolitos — o que
  confirmou, com fonte, que a estrutura por camadas é a correta neste escopo. Está
  detalhado em [Referências consultadas](#referências-consultadas-e-o-que-foi-adotado).
- **Revisei e executei tudo.** Nada foi aceito sem rodar: os testes passam, o `ruff` passa
  limpo, o Alembic conecta no Postgres do Compose e o `docker compose up` foi verificado de
  ponta a ponta (os três containers sobem saudáveis e `/health/ready` responde `200` com
  Postgres e Redis acessíveis).

*(Esta seção será detalhada por parte conforme o projeto avança.)*
