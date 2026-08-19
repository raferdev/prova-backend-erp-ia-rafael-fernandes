# Prova Técnica Back-end (ERP + IA) — Rafael Fernandes

Módulo de **Pedidos e Estoque** de um ERP, construído em FastAPI, integrando-se
(conceitualmente) aos módulos de Financeiro e Clientes.

> **Status:** em construção. A seção [O que ainda não foi feito](#o-que-ainda-não-foi-feito)
> lista o que falta e como eu faria — conforme pedido no enunciado.

---

## Sumário

- [Como rodar](#como-rodar)
- [Estrutura de pastas](#estrutura-de-pastas)
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

A estratégia é testar **regra de negócio isoladamente** (mockando repositories) e manter
os testes livres de dependência de infraestrutura sempre que o alvo do teste não for a
própria infraestrutura.

---

## O que ainda não foi feito

Esta seção é atualizada conforme o projeto avança.

| Parte | Status | Observação |
|---|---|---|
| Fundação (repo, esqueleto, Docker, `/health`) | ✅ feito | |
| Parte 3 — CRUD Produtos/Estoque | ⏳ pendente | validação Pydantic, JWT, paginação/filtros, cache Redis, worker |
| Parte 2 — Assíncrono (Q4) | ⏳ pendente | `asyncio.gather` com timeout individual e degradação graciosa |
| Parte 5 — Desafio de IA | ⏳ pendente | parser determinístico (Q8) + design de tool calling/MCP (Q9) |
| Parte 4 — Docker completo | 🟡 parcial | falta o serviço `worker` no Compose e as migrações |
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
- **Revisei e executei tudo.** Nada foi aceito sem rodar: os testes passam e o
  `docker compose up` foi verificado de ponta a ponta (os três containers sobem
  saudáveis e `/health/ready` responde `200` com Postgres e Redis acessíveis).

*(Esta seção será detalhada por parte conforme o projeto avança.)*
