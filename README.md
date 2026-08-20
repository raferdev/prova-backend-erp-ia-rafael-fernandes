# Prova Técnica Back-end (ERP + IA) — Rafael Fernandes

Módulo de Pedidos e Estoque de um ERP em FastAPI: cache Redis com invalidação por versão,
worker de fila idempotente, agregação paralela com degradação, consulta em linguagem natural
sem LLM e um servidor MCP funcional.

```bash
cp .env.example .env && docker compose up --build
```

Interface em `http://localhost:5173`, API em `http://localhost:8000`, Swagger em `/docs`.
Depois de subir: `docker compose exec api alembic upgrade head` e
`docker compose exec api python -m app.core.seed`.

## Índice

**Respostas:** [Q1 arquitetura](#q1--arquitetura-de-microsserviços) ·
[Q2 camadas](#q2--estrutura-de-pastas-e-camadas) ·
[Q3 concorrência](#q3--asyncio-threading-e-multiprocessing) ·
[Q4 paralelo](#q4--endpoint-com-3-fontes-em-paralelo) ·
[Q6 CRUD](#q6--crud-de-produtos-e-estoque) ·
[Q7 Docker](#q7--docker-e-orquestração) ·
[Q8 linguagem natural](#q8--pergunta-em-linguagem-natural) ·
[Q9 agente e MCP](#q9--agente-mcp-e-guardrails) ·
[Q10 perfil](#q10--a-frente-em-go) ·
[Q11 portfólio](#q11--portfólio)

**Projeto:** [Como rodar](#como-rodar) · [Decisões (10 ADRs)](#decisões) ·
[Testes](#testes) · [O que não foi feito](#o-que-não-foi-feito) · [Uso de IA](#uso-de-ia)

---

## Como rodar

Sobem cinco containers respeitando healthcheck:

```
SERVICE    STATUS
api        Up 19 seconds (healthy)
frontend   Up 14 seconds (healthy)
postgres   Up 26 hours (healthy)
redis      Up 26 hours (healthy)
worker     Up About a minute (healthy)
```

O seed é idempotente e cria nove produtos mais `admin@erp.local` / `admin123` — usuário de
desenvolvimento, sobrescrevível por `SEED_USUARIO_EMAIL` e `SEED_USUARIO_SENHA`.

`/health` é liveness e não toca em dependência nenhuma: se tocasse, uma queda do Postgres
reiniciaria a API em loop por um problema que não é dela. `/health/ready` checa Postgres e
Redis e devolve `503` estruturado.

O Alembic é dono do schema; a aplicação não cria tabelas no boot, para dev e produção
seguirem o mesmo caminho. Rodando do host em vez do container, prefixe `POSTGRES_HOST=localhost`.

Desenvolvimento: `uv sync && uv run uvicorn main:app --reload`, e
`cd frontend && npm install && npm run dev`.

### Usando a API

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token \
  -d "username=admin@erp.local&password=admin123" | jq -r .access_token)

curl -s -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/produtos?nome=cabo&preco_max=50&pagina=1&tamanho=20"
```

| Rota | |
|---|---|
| `POST /auth/token` | autentica, devolve JWT |
| `GET /produtos` · `GET /produtos/{id}` | leitura, servida de cache |
| `POST` · `PATCH` · `DELETE /produtos/{id}` | escrita, invalida o cache |
| `POST /produtos/{id}/estoque` | enfileira movimentação, `202` com `job_id` |
| `GET /produtos/{id}/movimentos` · `GET /alertas` | histórico e alertas abertos pelo worker |
| `GET /integracoes/contexto-de-venda/{id}` | três módulos em paralelo, degrada sem falhar |
| `POST /consultas/produtos` | pergunta em português, sem LLM |

Filtros: `nome`, `preco_min`, `preco_max`, `estoque_min`, `estoque_max`, `ativo` e
`apenas_estoque_baixo` — este compara com o `estoque_minimo` de cada produto, porque o ponto
de reposição não é um número global.

### Interface e servidor MCP

Front React + Vite em `http://localhost:5173`. Três telas, escolhidas para mostrar o que o
back-end tem de menos óbvio e não para ser painel administrativo — o enunciado diz que o foco
é back-end. A tela **Perguntar** exibe a interpretação e os filtros que rodaram, e ao
perguntar "produtos abaixo de 10" **recusa** com as duas leituras possíveis.

O front nunca sabe o endereço da API: chama `/api/...` relativo e um proxy resolve (Vite no
dev, nginx no Compose). Dispensa CORS e dispensa URL embutida no build.

O servidor MCP sobe com `uv run python -m app.mcp.servidor` e expõe cinco ferramentas: três
de leitura e duas de escrita em duas etapas. Ver [Q9](#q9--agente-mcp-e-guardrails).

---

# Respostas

## Q1 — Arquitetura de microsserviços

**Divisão por bounded context**, não por camada técnica, com cada serviço dono do seu banco.

| Serviço | Dono de |
|---|---|
| **Produtos/Estoque** (implementado aqui) | catálogo, saldo, movimentação, alertas |
| **Pedidos** | ciclo de vida do pedido; orquestra, não manda |
| **Financeiro** | faturas, cobranças, crédito |
| **Clientes** | cadastro, documentos, segmentação |

Database-per-service é a parte que gera discussão, então o argumento explícito: se Pedidos
puder dar `SELECT` na tabela `produto`, ele depende do *schema* do Estoque e não da API dele.
Renomear uma coluna quebra outro serviço, e o que resta é um monolito distribuído — o custo
da rede sem o benefício do desacoplamento.

### Comunicação

**Síncrona (REST) quando o fluxo depende da resposta agora.** Montar contexto de venda
precisa de cliente, crédito e prazo antes de seguir. Implementado em
`GET /integracoes/contexto-de-venda/{id}`: três fontes de ~49 ms respondem em 50 ms, não 150.
Custo é acoplamento em runtime, tratado com timeout, orçamento e degradação.

**Assíncrona (eventos) quando pode acontecer depois.** `PedidoConfirmado` é consumido por
Financeiro, Estoque e Clientes, cada um no seu tempo. Ganha resiliência — consumidor fora, o
evento espera na fila — e extensibilidade, porque consumidor novo não toca no publicador.
Implementado em escala reduzida: `POST /produtos/{id}/estoque` responde `202` e o worker
`arq` processa.

A régua que uso: se o usuário está esperando na tela para saber se pode seguir, é síncrona. E
o teste decisivo — **se a operação falhar em silêncio, alguém precisa ser acordado de
madrugada?** Se sim, precisa de fila com retry e persistência, não de HTTP que se perde.

### Consistência: Saga

Com um banco por serviço não existe `BEGIN` que cubra estoque e financeiro. Two-phase commit
resolveria no papel e trava recurso em todos os participantes enquanto o coordenador decide.

Saga são passos locais, cada um com **compensação**: pagamento recusado dispara evento que
devolve a reserva de estoque. Compensação não é rollback — é operação de negócio nova.
Cancelar cobrança emitida gera estorno, não apaga a cobrança. Num ERP isso é requisito
contábil, não detalhe.

Isso implica **consistência eventual**, e é preciso projetar para a janela em vez de fingir
que ela não existe. Mesmo raciocínio que apliquei duas vezes aqui: o TTL do cache existe para
quando a invalidação não aconteceu, e a varredura periódica do worker existe para quando o
evento se perdeu. Mecanismo rápido na frente, rede de segurança lenta atrás.

**Idempotência é obrigatória**, e essa eu aprendi apanhando: configurei retry no worker antes
de perceber que movimentar estoque não era idempotente. Fila entrega *pelo menos uma vez*. A
tabela `movimento_estoque` com chave única resolveu — e se provou em condição real, quando um
job falhou depois de commitar e o `arq` reentregou sem duplicar o efeito.

### PostgreSQL e Redis

**Postgres** é o banco transacional de cada serviço. Uso o banco para o que ele faz melhor
que código: `CheckConstraint` impedindo saldo negativo, índice único parcial garantindo no
máximo um alerta aberto por produto, `UPDATE` atômico em vez de ler-somar-gravar. As três
continuam valendo para quem escrever por fora do service, inclusive um script de correção.

**Redis** tem três papéis, e normalmente se lembra só do primeiro:

1. **Cache** de leitura quente, com invalidação por namespace versionado — um `INCR` derruba
   todas as listagens em O(1), sem `SCAN` (O(n) sobre o keyspace) e sem `KEYS`, que bloqueia
   o Redis inteiro por ser single-threaded.
2. **Broker** do worker.
3. **Lock distribuído** para oversell na disputa da última unidade.

Sendo honesto: **o terceiro não está implementado.** O `UPDATE` atômico resolve perda de
atualização, mas não substitui o lock quando a decisão depende de *ler o saldo antes de
decidir* — que é o caso da reserva de pedido, e pertence ao serviço de Pedidos. Com mais
tempo faria com Redlock, com a ressalva de que lock com TTL não é garantia absoluta: se o
processo travar segurando o lock e o TTL vencer, dois donos coexistem. Por isso a garantia
final fica no banco.

### API Gateway

Kong como porta única: roteamento, autenticação e validação de JWT, rate limiting, CORS, TLS,
log e tracing de borda.

O ganho não é técnico, é organizacional. Sem gateway, cada time reimplementa autenticação, e
a quinta implementação tem um bug que as outras quatro não têm. Isso apareceu concreto na
Parte 5: o servidor MCP entra como **mais um consumidor do gateway**, não como serviço
privilegiado — é o que faz o agente herdar as permissões do token que carrega, em vez de
existir um "usuário robô com acesso total".

Cuidado: gateway é ponto único de falha e tentação de virar lixeira de lógica de negócio.

### Observabilidade

**Logs** centralizados (ELK ou Loki), estruturados em JSON e com `trace_id`. **Métricas**
(Prometheus + Grafana): latência em percentis — não média, que esconde exatamente o cliente
que está sofrendo —, taxa de erro, saturação de pool, idade da fila. **Tracing**
(OpenTelemetry + Jaeger) é o mais importante em microsserviços e o que não tem substituto no
monolito: responde "o checkout está lento, onde?" sem virar três times olhando o próprio
gráfico e concluindo que o problema é do vizinho.

O que eu monitoraria primeiro num ERP, por impacto financeiro e não por volume de tráfego:

1. taxa de erro na criação de pedidos — receita não realizada, em tempo real;
2. **sagas incompletas** — estoque reservado sem pagamento é o alerta que acorda alguém;
3. consistência de estoque contra a soma das movimentações (o livro `movimento_estoque`
   existe para essa conferência ser possível);
4. latência do checkout em p95 e p99;
5. idade da mensagem mais antiga na fila — o sintoma aparece antes do prejuízo.

Alerta sem ação associada vira ruído, e ruído treina o time a ignorar alerta.

### AWS

Não fiz deploy; descrevo o desenho. ECS Fargate (EKS só se já houvesse Kubernetes na casa),
RDS Multi-AZ com uma instância por serviço, ElastiCache, EventBridge ou SNS/SQS, Secrets
Manager, ECR com scan no push, CloudWatch mais OTel Collector.

Dois pontos que costumam ficar de fora e eu colocaria desde o início: **dead-letter queue**,
porque sem ela uma mensagem venenosa trava o consumo, e **auto scaling por profundidade de
fila** — worker fica ocioso em CPU enquanto a fila cresce, então escalar por CPU não reage.

---

## Q2 — Estrutura de pastas e camadas

Esta é a estrutura real do repositório, não uma proposta. Fluxo sempre
**`router → service → repository`**.

```
app/
  routers/       # HTTP: recebe, chama o service, devolve
  services/      # regra de negócio
  repositories/  # único ponto que fala com o banco
  schemas/       # Pydantic (contrato da API)
  models/        # ORM (tabelas)
  core/          # config, conexões, JWT, cache, fila
  workers/       # tarefas de fila
  integracoes/   # gateways para outros bounded contexts
  mcp/           # servidor MCP
  tests/
main.py
frontend/        # React + Vite, com os testes Playwright em e2e/
docs/adr/        # registro de decisões
```

**`routers/`** não monta SQL, não conhece cache, não decide regra. Teste concreto: se o mesmo
CRUD precisasse ser exposto por mensageria, esta seria a única pasta descartada.

**`services/`** levanta exceção de domínio e não sabe o que é status code — a tradução para
HTTP fica num handler único em `main.py`. Não é purismo: o mesmo service é chamado pelo
worker, que não tem request nenhum.

**`repositories/`** concentra o SQL. É a camada mais difícil de justificar, porque o
`fastapi-best-practices` põe SQL no service. Mantive separado e o retorno apareceu: a política
de cache e a regra de estoque são testadas com dublê, sem Postgres, em milissegundos.

**`schemas/` separado de `models/`** é a separação que mais defendo. O contrato público da API
não é o schema do banco. Fundir os dois — que é o que o SQLModel faz — faz toda coluna nova
vazar para a resposta por padrão; num ERP é assim que custo de compra aparece num endpoint de
catálogo.

**`core/`** guarda o que atravessa tudo. A invalidação de cache mora aqui e não no router
porque o worker também precisa invalidar, e ele não passa por router nenhum.

**Testabilidade.** O service recebe repository e Redis por construtor, então a política de
cache inteira roda com Redis em memória e repository dublado. O client de teste é
`httpx.AsyncClient` sobre `ASGITransport`, sem abrir porta. Trocar `get_session` por um objeto
que levanta exceção é uma linha — é assim que o teste de readiness degradado é determinístico.

**Onde não ajuda**, que é honesto dizer: dublê não prova garantia de banco. Meu `ON CONFLICT`
estava escrito de um jeito que o Postgres recusa e o dublê passava tranquilo, porque
reimplementa o invariante em Python — validava minha intenção, não meu SQL. Foi o que me levou
a separar testes de integração.

**Princípios.** *SOLID*, principalmente Single Responsibility (uma razão para mudar por
camada) e Dependency Inversion (service depende de abstração, não da sessão do SQLAlchemy).
*Clean Architecture*, na ideia de que regra de negócio não sabe de onde o dado veio — o sinal
de que está valendo é o `EstoqueService` funcionar igual chamado por HTTP e por fila. *DDD
leve*, na divisão por bounded context e no vocabulário (`estoque_minimo`, `alerta aberto`,
`movimento`, e não `manager` ou `helper`). "Leve" de propósito: sem agregados nem value
objects, que neste porte seria cerimônia sem retorno.

**O que não segui:** organizar por domínio (`app/produtos/`). O critério do
`fastapi-best-practices` é porte — a frase completa diz que organizar por tipo "works well for
microservices or smaller projects", e este é um bounded context só
([ADR 0001](docs/adr/0001-estrutura-em-camadas.md)).

---

## Q3 — `asyncio`, `threading` e `multiprocessing`

A pergunta que separa os três não é qual é mais rápido, é **quem está segurando o trabalho**:
a rede ou o processador.

| | Paralelismo real | Custo por tarefa | Serve para |
|---|---|---|---|
| `asyncio` | não, intercala | baixíssimo | I/O com bibliotecas async |
| `threading` | não, GIL | médio | I/O com bibliotecas síncronas |
| `multiprocessing` | sim | alto | CPU |

**`asyncio`** tem um event loop só; a corrotina cede o controle no `await`. A troca é
*cooperativa*, e a palavra importa: nada é interrompido à força, então uma chamada bloqueante
dentro de código `async` **congela o loop inteiro** — não é a sua função que trava, é o
serviço. Por isso liguei a regra `ASYNC` do ruff: ela acusa isso no lint, em vez de eu
descobrir com a latência subindo sem explicação.

**`threading`** sofre do GIL, então só uma thread executa bytecode por vez e não há ganho em
CPU. Mas o GIL é **liberado durante I/O**, e é aí que serve: bibliotecas síncronas sem versão
async. É o que o FastAPI faz ao rodar rota `def` (não `async def`) num threadpool.

**`multiprocessing`** é a única que aumenta throughput de CPU, porque cada processo tem seu
interpretador. Preço: memória duplicada, serialização para atravessar a fronteira, custo de
subir processo — se a tarefa é curta, o overhead come o ganho.

**Chamar 3 APIs externas → `asyncio`.** É o que está implementado na Q4. Threading
funcionaria e gastaria três threads esperando socket; multiprocessing seria absurdo.

**CSV grande de importação → depende, e é onde erra quem decide sem medir.** A resposta
reflexa é "é arquivo, logo é I/O, logo threads". Ler é I/O mesmo, e costuma ser a parte
barata. O caro é validar dez mil linhas, converter tipos, conferir duplicidade — isso é
**CPU**, e nem asyncio nem threading ajudam. Eu leria em streaming e distribuiria blocos com
`ProcessPoolExecutor`, disparado por fila e não por request. Mas mediria antes: se o gargalo
for o `INSERT`, a resposta muda inteira e o ganho está em inserção em lote.

**Relatório pesado em PDF → `multiprocessing`.** Renderizar é CPU puro. `asyncio` seria pior
que inútil: sem `await`, a geração bloqueia o loop e a API inteira para de responder. Na
prática a rota enfileira e responde `202`, o worker consome, e a geração roda via
`run_in_executor(ProcessPoolExecutor(), ...)` — ressalva que registrei no
[ADR 0003](docs/adr/0003-fila-com-arq.md) ao escolher o `arq`.

**Um quarto caso que aparece muito em ERP e não está na lista: `threading`.** SDK de emissão
de nota fiscal, cliente de SEFAZ, biblioteca de certificado digital — quase sempre síncronos,
sem versão async e sem chance de reescrever. Aí é `run_in_threadpool`.

---

## Q4 — Endpoint com 3 fontes em paralelo

`GET /integracoes/contexto-de-venda/{cliente_id}` consulta Clientes, Financeiro e Logística
com `asyncio.gather`. Código em [`app/services/contexto.py`](app/services/contexto.py) e
[`app/integracoes/base.py`](app/integracoes/base.py); decisões no
[ADR 0009](docs/adr/0009-consulta-paralela-degradacao.md).

Três coisas que `gather` sozinho não resolve:

**`return_exceptions=True`** é a diferença entre `Promise.all` e `Promise.allSettled`. Sem
ele, a primeira falha descarta as respostas que já chegaram.

**Orçamento total além do timeout por fonte.** 0,8 s por tentativa × 2 tentativas viraria
1,6 s por fonte. Cada tentativa só acontece se houver orçamento, e a janela é o menor entre o
timeout e o que sobrou.

**Falha nunca vira dado** — a decisão que o enunciado não pede e que considero a mais
importante. Cada fonte devolve `status` próprio e `dados: null` quando falha, nunca objeto
vazio. Se o Financeiro cai e a resposta trouxesse `saldo_devedor: 0`, o módulo de Pedidos
concluiria que o cliente está limpo e liberaria a venda.

```
tudo no ar             → completo=True, latencia_total=50ms (cada fonte ~49ms)
financeiro fora        → HTTP 200, dados=NULL, 2 tentativas, as outras intactas
logistica dormindo 5s  → HTTP 200 em 1,65s, status=timeout
fonte instavel         → retry recupera na 2a tentativa
```

Responde `200` mesmo degradado, de propósito: um `502` jogaria fora as duas fontes que
responderam. O endpoint entrega **contexto, não veredito** — quem recusa a venda é o módulo de
Pedidos, com a política dele.

---

## Q6 — CRUD de Produtos e Estoque

CRUD completo com validação Pydantic, Postgres, JWT, paginação, filtros, cache e worker.

**ORM: SQLAlchemy 2.0 async + Alembic** ([ADR 0002](docs/adr/0002-persistencia-sqlalchemy-async.md)).
Async nativo com `asyncpg`, porque ORM síncrono bloquearia o event loop num serviço que é
quase todo I/O. SQLModel descartado por fundir `schemas/` e `models/`.

**Validação.** Preço `ge=0` com duas casas — a coluna é `NUMERIC(12,2)`, e aceitar três casas
criaria arredondamento silencioso. Nome não vazio e não puramente numérico, mas
"Monitor 27 polegadas" passa, porque a regra é "só números", não "sem números". As mesmas
garantias existem no banco via `CheckConstraint`, porque a API não é o único caminho de
escrita.

**Cache com invalidação por namespace versionado** ([ADR 0007](docs/adr/0007-estrategia-de-cache.md)).
A versão entra na chave (`produtos:v7:list:{hash}`), então um `INCR` invalida todas as
listagens em O(1). Detalhe do fingerprint: normalizo a ordem dos parâmetros antes do hash,
senão `?nome=cabo&pagina=1` e `?pagina=1&nome=cabo` viram duas entradas para o mesmo resultado.

**O que decidi não cachear:** consultas filtradas por estoque. Cacheio o que é estável, não
cacheio o que é volátil — alerta de estoque baixo respondido de cache de 60 s atrás não serve
para nada. E o TTL continua existindo mesmo com invalidação explícita: ele cobre a invalidação
que não aconteceu porque o Redis piscou.

**Worker `arq`** ([ADR 0003](docs/adr/0003-fila-com-arq.md) e
[ADR 0008](docs/adr/0008-worker-de-estoque.md)) com duas tarefas: movimentar estoque
(invalida cache, registra o movimento) e varrer o catálogo abrindo ou resolvendo alertas.
Roda por evento após cada movimentação **e** por cron — evento é o mecanismo, varredura é a
rede de segurança para o que ele perdeu, como `estoque_minimo` editado sem o estoque mudar.

`BackgroundTasks` foi descartado: roda no processo web, sem retry nem persistência. A régua é
a mesma da Q1 — se você seria acordado porque a tarefa se perdeu, ela não pertence ali.

---

## Q7 — Docker e orquestração

`Dockerfile` multi-stage para API e front, `docker-compose.yml` com cinco serviços e
healthcheck em todos, `.env` fora do versionamento com `.env.example` documentando as chaves.

**Multi-stage** porque o estágio de runtime leva só o virtualenv pronto (ou os estáticos e o
nginx), sem toolchain de build: imagem menor e menor superfície de ataque. Container roda com
usuário sem privilégios, e as camadas são ordenadas por volatilidade — manifestos antes do
código, então mudar código não invalida a instalação de dependências.

**`depends_on: condition: service_healthy`** é o detalhe que importa: sem ele o Compose
considera pronto um container que apenas *iniciou*, e a API tentaria conectar antes do
Postgres aceitar conexões.

Worker e API usam **a mesma imagem** com comando diferente. Imagens separadas dariam duas
versões do mesmo código convivendo, e a divergência apareceria como bug de dado.

---

## Q8 — Pergunta em linguagem natural

`POST /consultas/produtos`, parser determinístico por regras em
[`app/services/parser_consulta.py`](app/services/parser_consulta.py). Nenhum LLM em runtime.

O parser **não monta consulta própria**: produz o mesmo `FiltrosProduto` que a API REST recebe
por query string, e entrega ao mesmo repository. Se montasse SQL paralelo, divergiria do
endpoint na primeira mudança de regra.

**A decisão central é recusar em vez de adivinhar.** "produtos abaixo de 10" não diz dez de
quê — chutar estoque quando a pessoa queria preço devolve número errado com aparência de
certo, e alguém decide compra com esse número. Nesse caso ele responde que está ambíguo e
lista as duas interpretações.

Toda resposta traz a interpretação em português e os filtros que rodaram, para ser conferível:
número sem procedência não serve para decidir. E trata número em formato pt-BR — `1.500,50` é
mil e quinhentos, não um e meio; ler como formato americano transformaria mil reais em um real.

---

## Q9 — Agente, MCP e guardrails

O enunciado pede design. Implementei também o servidor MCP, porque ele expõe ferramentas e não
chama modelo nenhum — quem chama LLM é o cliente do outro lado
([ADR 0010](docs/adr/0010-servidor-mcp.md)).

### Tool calling

O modelo não consulta o banco: escolhe **qual ferramenta chamar** e com quais argumentos, e
quem executa é o nosso código, com as mesmas regras e permissões de qualquer cliente da API.
Se o agente gerasse SQL, toda a validação, cache e controle de acesso seriam contornados.

```json
{
  "name": "criar_pedido",
  "description": "Cria um pedido de venda. AÇÃO DESTRUTIVA: reserva estoque e gera cobrança. Exige confirmação explícita do usuário.",
  "input_schema": {
    "type": "object",
    "properties": {
      "cliente_id": {"type": "string", "format": "uuid"},
      "itens": {"type": "array", "minItems": 1, "items": {"...": "..."}},
      "idempotency_key": {"type": "string", "description": "Reenvio com a mesma chave não cria segundo pedido."}
    },
    "required": ["cliente_id", "itens", "idempotency_key"],
    "additionalProperties": false
  }
}
```

Três decisões embutidas. A **descrição declara que a ação é destrutiva**, porque ela não é
documentação para humano — é o que o modelo lê para decidir. A **`idempotency_key` é
obrigatória**, porque agente repete chamada: é o mesmo problema que resolvi no worker com
`movimento_estoque.referencia`. E **`produto_id` é UUID, não nome** — se aceitasse nome, o
modelo resolveria sozinho e poderia acertar o produto errado; assim ele precisa passar por uma
leitura verificável antes de escrever.

> **Correção depois de implementar.** Eu havia escrito que `additionalProperties: false`
> impede argumento alucinado de passar. **Não impede.** Ao construir o servidor descobri que o
> SDK aceita o argumento desconhecido, **descarta em silêncio e devolve sucesso** — verificado
> na mão: `consultar(nome="cabo", desconto_maximo=30)` retorna `is_error=False` e o
> `desconto_maximo` evapora. A lição corrige o princípio: schema é declaração de intenção *para
> o modelo*, e quem protege é o servidor. Em `app/mcp/servidor.py` a validação acontece antes
> do despacho e a chamada é recusada.

### MCP na arquitetura da Q1

O servidor entra **como mais um consumidor do API Gateway**, não como serviço privilegiado:

```
Agente → servidor MCP → API Gateway (auth, rate limit, tracing) → serviços do ERP
```

Ir direto ao banco seria mais simples e erraria em três frentes: contornaria validação e
cache, daria ao agente acesso mais amplo que o do usuário da conversa, e tiraria o tráfego do
agente da observabilidade. Um servidor MCP **por bounded context**, e não um monolito de
ferramentas — senão vira acoplamento novo onde a arquitetura tentou desacoplar.

### Guardrails

**Confirmação em duas etapas para ação destrutiva.** Ferramenta de escrita não executa na
primeira chamada: devolve preview com valores resolvidos ("Baixar 3 unidades de Cabo HDMI 2m,
saldo 120 ficará 117") e um token de dois minutos, de uso único. O problema real não é modelo
malicioso, é modelo confiante — uma frase ambígua vira ação irreversível sem ninguém ter visto
o que ela significava. O preview é também onde a alucinação morre: se o modelo errou o produto,
quem lê vê o nome errado antes de confirmar.

**Alucinação.** Nunca confiar em id vindo do modelo — id inexistente é erro explícito, não
busca aproximada, porque "encontrei algo parecido" é como se vende o produto errado. Ferramenta
nunca responde vazio quando falhou (devolve `{"status": "indisponivel"}`, já que lista vazia faz
o modelo afirmar que não há nada). E teto de passos por conversa, contra o laço em que o agente
reformula a mesma consulta indefinidamente.

**Escopo.** O token do agente carrega as permissões do usuário, e a lista de ferramentas é uma
allow-list por perfil: o agente de suporte não recebe `criar_pedido` no catálogo — não é que
seja recusado, é que a ferramenta não existe para ele.

### Custo, latência e observabilidade

**Custo** é dominado pelo tamanho do contexto, que cresce sozinho porque cada resultado de
ferramenta volta inteiro para o modelo. Limitar o retorno (teto de 50 itens, `total` separado
dos itens — "quantos produtos estão em falta" não precisa carregar 4.000 registros para
responder um número), cache de resposta de ferramenta com a mesma política do ADR 0007, prompt
caching para o bloco estável, e roteamento por modelo, porque classificar intenção é tarefa de
modelo pequeno.

**Latência.** Chamadas independentes em paralelo — já resolvido aqui, é o `gather` com timeout
e orçamento da Q4. Timeout por ferramenta com degradação, e streaming da resposta final.

**Observabilidade.** Log de prompt e resposta com o mesmo `trace_id` das chamadas HTTP que a
ferramenta disparou, senão "o agente respondeu errado ontem" é irreproduzível — com máscara de
dado pessoal e retenção curta, porque prompt de ERP contém nome e documento de cliente.
Métricas por turno: tokens, custo estimado, número de chamadas, e **taxa de confirmação
negada**, que é sintoma antes de virar incidente: se muitos previews estão sendo recusados, o
agente está entendendo errado com frequência. Alerta de custo por janela e não só total mensal,
porque um laço de ferramenta gasta em uma hora o orçamento do mês.

**Fallback.** Retry com backoff, provedor secundário, e degradação honesta — dizer que o
assistente está indisponível e oferecer o caminho normal da aplicação. O ERP não pode depender
do agente para funcionar: ele é uma interface a mais sobre uma API que já existe.

---

## Q10 — A frente em Go

**Reajo bem, e o motivo não é boa vontade.** Go é adequado ao cenário: goroutines custam ordens
de magnitude menos que threads do sistema, binário único simplifica deploy e derruba cold
start, e a ausência de GIL dá paralelismo real em CPU — exatamente a limitação que registrei no
[ADR 0003](docs/adr/0003-fila-com-arq.md) deste projeto. Discutir a escolha aqui seria discutir
preferência minha, não a necessidade do sistema.

**Já fiz isso, e tem código público.** O [payment_processor](https://github.com/raferdev/payment_processor)
é um sistema de três serviços em **três linguagens**, construído em uma semana: gateway em Node,
análise de fraude em Python com Keras, regras em Ruby on Rails. Escolhi Rails para o serviço de
regras sendo a linguagem que eu menos dominava das três, porque era o que entregava aquele CRUD
mais rápido. É o cenário da pergunta, já vivido. Aprendi o custo junto, e ele está no meu
portfólio como autocrítica: três toolchains numa POC de uma semana foi caro.

**Como me organizaria.** O gargalo não é sintaxe, é *idioma*. O que transfere direto — camadas,
injeção de dependência, contrato separado de persistência — é a maior parte do que eu faço. O
que é específico eu iria atrás: `context.Context` para cancelamento, canais e `sync`, erro como
valor de retorno, e as armadilhas conhecidas (variável capturada em loop, `nil` interface que
não é `nil`, goroutine vazando). Linter como rede desde o primeiro commit, mesma tática da regra
`ASYNC` do ruff aqui. E pediria revisão explícita de idioma nos primeiros PRs, senão escrevo Go
com sotaque de TypeScript por três meses sem ninguém falar nada.

**Se eu discordasse, argumentaria por número, não por preferência.** Primeiro levaria um
perfilamento: se o tempo está indo em espera de banco ou numa query sem índice, trocar de
linguagem melhora a fatia errada. Depois, os degraus mais baratos até o mesmo alvo — `uvloop`,
`orjson`, processamento em lote, `COPY` no lugar de `INSERT` repetido, escala horizontal. Se
ainda faltasse, proporia alternativas com menos custo de troca, como Rust via PyO3 quando o
gargalo é uma função quente e bem delimitada. E colocaria na mesa o custo que ninguém conta:
dois pipelines, dois conjuntos de dependências, plantão que precisa saber as duas.

O que eu **não** faria: dizer "Python é rápido o suficiente" sem medição, e transformar a
decisão em referendo. Apresentaria os dados, ouviria o contexto que talvez eu não tenha, e se a
decisão fosse mantida entraria inteiro — discordar e entregar mal é o pior resultado.

**Esta prova é a evidência recente:** Python e FastAPI não são minha stack principal.

---

## Q11 — Portfólio

**[payment_processor](https://github.com/raferdev/payment_processor)** — processamento de
pagamento com análise de fraude, em uma semana. Escolho este porque não é um CRUD bonito: é um
fluxo de ponta a ponta com serviços que precisam concordar para uma transação ser aprovada.

**O problema.** Entender na prática o mercado adquirente: o que acontece entre passar o cartão
e a transação ser aprovada, e onde entra a decisão de fraude. A pergunta que só aparece
implementando é: quando três sistemas precisam concordar, o que acontece quando um deles não
responde?

**Decisões.** Node no gateway, porque é quase toda espera de rede e orquestração de requisições
paralelas. Python com Keras no serviço de ML em vez de mais regras estáticas, porque regra pega
o que você já sabe que é fraude e o modelo existe para o que ela não previu — e devolve
percentual, o que permite calibrar o limiar depois sem reescrever a regra. Rails no serviço de
regras por velocidade de construção, assumindo conscientemente o custo da terceira linguagem.
Redis antes do Postgres no caminho, rejeitando repetição em memória.

**O que eu faria diferente hoje.** O fan-out não tem degradação: o gateway derruba a transação
se ML ou Rules falhar, o que confunde *"o modelo reprovou"* com *"o modelo não respondeu"* — e
instabilidade vira recusa de venda legítima. É exatamente o problema que resolvi na
[Q4](#q4--endpoint-com-3-fontes-em-paralelo) desta prova. Também faltava idempotência (retry do
cliente cria cobrança nova, mesmo erro que repeti no worker daqui) e observabilidade: sem
`trace_id` atravessando os três, não dá para dizer qual avaliador negou sem ler log de três
lugares e cruzar na mão.

**Outros links.** [classification_with_sklearn](https://github.com/raferdev/classification_with_sklearn)
é o início dos meus estudos de ML em 2023 — estudo, não produção.
[Stack Overflow](https://stackoverflow.com/users/20442134/rafael-fernandes): respostas com
pontuação, principalmente em 2022; não é perfil de alta reputação, está aqui porque mostra que
eu explico o que aprendo. [WakaTime](https://wakatime.com/@raferdev): cerca de 4 mil horas
medidas, e vale dizer o que a métrica é — tempo com o editor aberto, não qualidade nem entrega.
[GitHub](https://github.com/raferdev).

---

# Projeto

## Decisões

Dez decisões em [`docs/adr/`](docs/adr/), cada uma com contexto, alternativas descartadas, o
que estou pagando pela escolha e a **saída do comando que a validou**.

| # | |
|---|---|
| [0001](docs/adr/0001-estrutura-em-camadas.md) | organizar por camada, não por domínio |
| [0002](docs/adr/0002-persistencia-sqlalchemy-async.md) | SQLAlchemy 2.0 async, descartando SQLModel |
| [0003](docs/adr/0003-fila-com-arq.md) | `arq`, descartando Celery, RQ e `BackgroundTasks` |
| [0004](docs/adr/0004-liveness-separado-de-readiness.md) | liveness separado de readiness |
| [0005](docs/adr/0005-test-client-async.md) | client de teste async desde o início |
| [0006](docs/adr/0006-convencoes-de-migration.md) | convenções fixadas antes da 1ª migration |
| [0007](docs/adr/0007-estrategia-de-cache.md) | cache com invalidação por namespace versionado |
| [0008](docs/adr/0008-worker-de-estoque.md) | worker de estoque idempotente |
| [0009](docs/adr/0009-consulta-paralela-degradacao.md) | consulta paralela com degradação |
| [0010](docs/adr/0010-servidor-mcp.md) | servidor MCP sobre a API |

## Testes

```
$ uv run pytest -q
131 passed in 11.10s        # cobertura 90%

$ cd frontend && npx playwright test
18 passed (7.3s)
```

Dois tipos, e a distinção foi aprendida errando. A maioria roda sem infraestrutura, com
repository dublado e Redis em memória. Já `test_integracao_*.py` precisa de Postgres, porque
dublê não prova garantia de banco — e pula sozinho quando não há banco, exceto na CI, onde
pular seria confiança falsa.

A CI roda tudo em todo pull request, com Postgres e Redis reais, build das duas imagens, e um
`docker compose up` que autentica, chama rota protegida e roda os 18 Playwright contra o build
de produção. Workflow em [`.github/workflows/ci.yml`](.github/workflows/ci.yml).

## O que não foi feito

**Lock distribuído para oversell.** É o problema mais interessante do domínio e ficou como
decisão registrada em vez de código. O `UPDATE` atômico cobre perda de atualização, mas não
substitui o lock quando a decisão depende de ler o saldo antes de decidir. Com mais tempo:
Redlock no serviço de Pedidos, com a garantia final ainda no banco.

**Circuit breaker** na agregação paralela. Com três mocks seria cerimônia; num sistema real,
depois de N falhas seguidas você para de chamar a fonte em vez de pagar o timeout sempre.

**O parser tem teto.** Entende as formas que previ e recusa o resto. O passo seguinte seria
classificação de intenção com modelo local pequeno, mantendo a extração de valores
determinística: modelo para interpretar, código para executar.

**Deploy na AWS.** Desenhado na [Q1](#q1--arquitetura-de-microsserviços), não executado.

## Uso de IA

Meu histórico é Node, NestJS e TypeScript. Python não é minha stack principal, e prefiro dizer
isso direto.

**A arquitetura e as decisões são minhas.** O fluxo `router → service → repository` e a
justificativa de cada escolha vêm de NestJS, onde o modelo é o mesmo. O que eu não tinha era o
mapa do ecossistema Python, e é aí que usei IA: qual biblioteca ocupa o lugar do TypeORM, qual é
o BullMQ daqui, qual é a pegadinha idiomática de cada uma.

**Usei IA para verificar referências, não para aceitá-las.** Ao avaliar o template oficial do
FastAPI e o `fastapi-best-practices`, o que mudou minha conclusão foi listar a árvore real dos
repositórios em vez de ler o resumo — descobri que o template oficial não tem Redis, fila nem
worker, e que a recomendação de organizar por domínio é condicionada a monolitos. Foi assim que
SQLModel e Celery foram descartados, mesmo aparecendo como opções óbvias.

**Nada entrou sem rodar.** As saídas de comando neste README e nos ADRs são reais, não
ilustrativas. Onde não validei, está escrito que não validei.

**Os erros também estão registrados**, porque são o que mostra o processo funcionando:

- tratar chave de versão ausente como `1` fazia a primeira invalidação não invalidar nada, já
  que `INCR` numa chave inexistente também resulta em `1`;
- o FastAPI aceita só um modelo Pydantic por endpoint como query string — com dois, passa a
  exigir params chamados `filtros` e `paginacao`, sem erro no boot nem no lint;
- configurei retry no worker antes de perceber que movimentar estoque não era idempotente;
- escrevi o `ON CONFLICT` com uma expressão do ORM que o Postgres recusa, e o dublê passava
  porque validava minha intenção e não meu SQL;
- um teste de readiness passava localmente por acidente de credenciais e quebrou na CI;
- e dois problemas que só apareceram quando clonei o repositório do zero: o worker cuspindo
  traceback antes das migrations, e dois testes de paginação que dependiam de um produto que eu
  tinha criado à mão.

Os quatro últimos têm a mesma causa raiz: eu validando contra um estado que só existia na minha
máquina. É o argumento mais honesto que tenho a favor de CI e de teste de integração.
