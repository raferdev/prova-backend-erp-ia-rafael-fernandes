# Parte 1 — Arquitetura e organização

Sempre que possível, ligo a decisão ao código deste repositório. Arquitetura descrita no
abstrato é fácil de defender; a que já passou por implementação tem cicatriz, e as
cicatrizes estão marcadas ao longo do texto.

- [Questão 1 — arquitetura de microsserviços](#questão-1--arquitetura-de-microsserviços)
- [Questão 2 — estrutura de pastas e camadas](#questão-2--estrutura-de-pastas-e-camadas)

---

# Questão 1 — arquitetura de microsserviços

---

## 1. Divisão em serviços

Divido por **bounded context**, não por camada técnica. Serviço não é "o serviço de banco
de dados" nem "o serviço de API": é um pedaço do negócio que muda por um motivo próprio e
tem dono.

| Serviço | É dono de | Muda quando |
|---|---|---|
| **Produtos/Estoque** | catálogo, saldo, movimentação, alertas | regra de catálogo ou de reposição muda |
| **Pedidos** | o pedido e seu ciclo de vida | regra de venda muda |
| **Financeiro** | faturas, cobranças, crédito | regra fiscal ou de cobrança muda |
| **Clientes** | cadastro, documentos, segmentação | regra de cadastro muda |

Este repositório implementa o primeiro.

**Cada serviço é dono do seu banco** (database-per-service). É a parte que mais gera
discussão, então vale o argumento explícito: se o serviço de Pedidos puder dar `SELECT` na
tabela `produto`, ele passa a depender do *schema* do Estoque, e não da API dele. A partir
daí, renomear uma coluna quebra outro serviço, e a autonomia que justificava separar
desaparece. O que resta é um monolito distribuído: o custo da rede sem o benefício do
desacoplamento.

Pedidos **orquestra**, mas não é dono. Ele coordena estoque e financeiro sem mandar neles.

---

## 2. Comunicação: síncrona e assíncrona, cada uma no seu caso

Não é escolher um dos dois. É saber qual pergunta cada um responde.

### Síncrona (REST), quando o fluxo depende da resposta agora

Montar um contexto de venda precisa de cliente, crédito e prazo de entrega **antes** de
seguir. Esperar é o ponto.

Implementado em `GET /integracoes/contexto-de-venda/{cliente_id}`, com as três fontes indo
em paralelo. Medido na API real: cada fonte responde em ~49 ms e a resposta total sai em
50 ms, não 150.

O custo é acoplamento em tempo de execução: se o Financeiro cair, meu endpoint sente. Por
isso ele tem timeout por fonte, orçamento total e degradação — decisões e números no
[ADR 0009](adr/0009-consulta-paralela-degradacao.md).

E a regra que considero a mais importante de tudo isso: **falha nunca vira dado**. Se o
Financeiro está fora, a resposta traz `dados: null` e `status: "erro"`, jamais
`saldo_devedor: 0`. Um zero devolvido por engano faz o Pedidos concluir que o cliente está
limpo e liberar a venda.

### Assíncrona (eventos), quando pode acontecer depois

Pedido confirmado publica `PedidoConfirmado`. Financeiro gera a cobrança, Estoque dá baixa,
Clientes atualiza histórico — cada um no seu tempo, sem que Pedidos saiba quem escuta.

Duas vantagens que a síncrona não dá: resiliência, porque com um consumidor fora o evento
espera na fila em vez de o pedido falhar; e extensibilidade, porque adicionar um consumidor
novo (BI, antifraude) não toca no publicador.

Implementado em escala reduzida: `POST /produtos/{id}/estoque` responde `202` e enfileira,
o worker `arq` processa. É a mesma forma, com fila em vez de barramento de eventos
([ADR 0008](adr/0008-worker-de-estoque.md)).

### A regra prática que uso para decidir

Se o usuário está esperando na tela para saber se pode seguir, é síncrona. Se a operação
pode ser confirmada depois sem prejuízo, é assíncrona. E o teste decisivo: **se a operação
falhar em silêncio, alguém precisa ser acordado de madrugada?** Se sim, ela precisa de fila
com retry e persistência, não de uma chamada HTTP que se perde.

---

## 3. Consistência: Saga, e por que não transação distribuída

Com um banco por serviço, não existe `BEGIN` que cubra estoque e financeiro. Two-phase
commit resolveria no papel e trava recurso em todos os participantes enquanto o
coordenador decide — e um coordenador lento vira indisponibilidade em cascata.

A alternativa é **Saga**: a transação vira uma sequência de passos locais, cada um com uma
**compensação**.

```mermaid
sequenceDiagram
    participant P as Pedidos
    participant E as Estoque
    participant F as Financeiro

    P->>E: reservar estoque
    E-->>P: reservado
    P->>F: cobrar
    F-->>P: pagamento recusado
    P->>E: EstoqueLiberado (compensação)
    E-->>E: devolve a reserva
    Note over P: pedido cancelado, saldo íntegro
```

Compensação não é rollback: é uma operação de negócio nova que desfaz o efeito da anterior.
Cancelar uma cobrança já emitida gera um estorno, não apaga a cobrança. Num ERP isso é
requisito contábil, não detalhe — o histórico tem que mostrar o que aconteceu, inclusive o
erro.

Isso implica **consistência eventual**: existe uma janela em que o estoque está reservado e
o pagamento ainda não confirmou. É preciso projetar para ela, e não fingir que não existe.
É o mesmo raciocínio que usei em duas decisões deste repositório: o TTL do cache existe
para o caso em que a invalidação não aconteceu ([ADR 0007](adr/0007-estrategia-de-cache.md)),
e a varredura periódica do worker existe para o caso em que o evento se perdeu
([ADR 0008](adr/0008-worker-de-estoque.md)). Em ambos, o mecanismo principal é o rápido, e
há uma rede de segurança lenta atrás.

**Idempotência é obrigatória**, e essa eu aprendi apanhando aqui. Fila entrega *pelo menos
uma vez*: configurei retry no worker antes de perceber que movimentar estoque não era
idempotente, e uma reentrega aplicaria a baixa duas vezes. A correção foi a tabela
`movimento_estoque` com chave única — e ela se provou em condição real, quando um job falhou
depois de commitar e o `arq` reentregou sem duplicar o efeito.

---

## 4. Persistência

### PostgreSQL como banco transacional de cada serviço

Dentro de um serviço, ACID de verdade. É o que garante que baixar estoque e registrar a
movimentação aconteçam juntos ou não aconteçam.

Uso o banco para o que ele faz melhor que código: `CheckConstraint` impedindo saldo
negativo, índice único parcial garantindo no máximo um alerta aberto por produto, e `UPDATE`
atômico em vez de ler-somar-gravar. Todas as três são garantias que continuam valendo para
quem escrever por fora do meu service — inclusive uma migration ou um script de correção.

O `UPDATE` atômico tem teste com cinco transações concorrentes: ler-somar-gravar deixaria o
saldo em 9 em vez de 5.

### Redis com três papéis

Normalmente se lembra só do primeiro:

1. **Cache** de leitura quente do catálogo, com invalidação por namespace versionado. Um
   `INCR` derruba todas as listagens em O(1), sem `SCAN` — que é O(n) sobre o keyspace — e
   sem `KEYS`, que bloqueia o Redis inteiro por ser single-threaded.
2. **Broker** do worker de background.
3. **Lock distribuído** para o *oversell*: dois pedidos disputando a última unidade em
   estoque.

**Sendo honesto sobre o terceiro:** ele não está implementado. O `UPDATE` atômico que uso
resolve perda de atualização, mas não substitui o lock quando a decisão de negócio depende
de *ler o saldo antes de decidir* — que é exatamente o caso da reserva de pedido. Está
registrado como limite explícito no ADR 0008, e pertence ao serviço de Pedidos.

Com mais tempo eu implementaria com Redlock, e com uma ressalva que acho importante: lock
distribuído com TTL não é garantia absoluta. Se o processo travar segurando o lock e o TTL
vencer, dois donos coexistem. Por isso a garantia final tem que estar no banco — no meu
caso, a `CheckConstraint` de saldo não negativo, que faz a transação falhar em vez de
gravar um número impossível.

---

## 5. API Gateway

Kong como porta única de entrada, resolvendo o que seria repetido em todo serviço:
roteamento, autenticação e validação de JWT, rate limiting, CORS, terminação TLS, e log e
tracing de borda.

O ganho não é técnico, é organizacional: sem gateway, cada time reimplementa autenticação, e
a quinta implementação vai ter um bug que as outras quatro não têm. Centralizar tira a
decisão de segurança de quem está com pressa para entregar uma feature.

Isso apareceu de forma concreta na Parte 5: o servidor MCP entra como **mais um consumidor
do gateway**, e não como serviço privilegiado com acesso direto ao banco. É o que faz o
agente de IA herdar exatamente as permissões do token que carrega, em vez de existir um
"usuário robô com acesso total" ([ADR 0010](adr/0010-servidor-mcp.md)).

O cuidado: gateway é ponto único de falha e tentação de virar lixeira de lógica de negócio.
Ele faz cross-cutting; regra de negócio fica no serviço.

---

## 6. Observabilidade

### Os três pilares

**Logs centralizados** (ELK ou Loki), estruturados em JSON e com `trace_id`. Log em texto
livre espalhado por dez serviços não responde nada.

**Métricas** (Prometheus + Grafana): latência por rota em percentis, taxa de erro,
saturação de pool de conexão, tamanho e idade da fila. Percentil, não média — a média
esconde exatamente o cliente que está sofrendo.

**Tracing distribuído** (OpenTelemetry + Jaeger), que é o mais importante em
microsserviços e o que não tem substituto no monolito. Ele responde a pergunta que aparece
toda semana: "o checkout está lento — onde?". Sem trace, isso vira três times olhando o
próprio gráfico e concluindo que o problema é do vizinho.

### O que eu monitoraria primeiro num ERP

Prioridade por **impacto financeiro e integridade**, não por volume de tráfego:

1. **Taxa de erro na criação de pedidos.** É receita não realizada, medida em tempo real.
2. **Falhas de cobrança e sagas incompletas.** Uma saga que parou no meio deixou estoque
   reservado sem pagamento. Esse é o alerta que eu colocaria para acordar alguém.
3. **Consistência de estoque.** Divergência entre saldo e a soma das movimentações é
   sintoma de bug ou de compensação que não rodou. O livro `movimento_estoque` deste
   projeto existe para essa conferência ser possível.
4. **Latência do checkout**, em p95 e p99.
5. **Idade da mensagem mais antiga na fila.** Fila crescendo é consumidor morto, e o
   sintoma aparece antes do prejuízo.

Um princípio que aplico ao alertar: alerta que não tem ação associada vira ruído, e ruído
treina o time a ignorar alerta. Prefiro poucos alertas que acordam alguém, e o resto em
painel.

---

## 7. AWS

Não fiz deploy, então descrevo o desenho e sou explícito sobre isso.

| Componente | Serviço | Por quê |
|---|---|---|
| Containers | ECS Fargate | sem gerenciar nó; EKS só se já houvesse Kubernetes na casa |
| Banco | RDS PostgreSQL Multi-AZ | failover automático; uma instância por serviço |
| Cache e fila | ElastiCache Redis | o mesmo Redis dos três papéis |
| Eventos | EventBridge ou SNS/SQS | SQS com *dead-letter queue*, que é onde a mensagem venenosa vai parar |
| Segredos | Secrets Manager | nunca `.env` em produção; a aplicação já lê tudo do ambiente |
| Imagens | ECR | com scan de vulnerabilidade no push |
| Observabilidade | CloudWatch + OTel Collector | exporta para o backend de tracing |

Dois pontos que costumam ficar de fora e eu colocaria desde o começo: **dead-letter queue**,
porque sem ela uma mensagem que sempre falha trava o consumo, e **auto scaling por
profundidade de fila**, e não só por CPU — worker de fila fica ocioso em CPU enquanto a fila
cresce, e escalar por CPU não reage.

---

## 8. O que a implementação me fez mudar de ideia

Vale registrar, porque é o que separa arquitetura defendida de arquitetura recitada.

**Camada de repository sobrevive à prova prática.** Eu poderia ter posto o SQL no service,
como faz uma referência conhecida da comunidade. Mantive a separação, e ela pagou: a política
de cache inteira e a regra de negócio de estoque são testadas sem Postgres no ar.

**Mas dublê tem um teto, e eu descobri onde.** O `ON CONFLICT` do alerta estava escrito de
um jeito que o Postgres recusa, e o dublê passava tranquilo — ele reimplementa o invariante
em Python, então validava a minha intenção em vez do meu SQL. Foi o que me levou a separar
testes de integração contra banco real dos testes rápidos. E a medir cobertura em vez de
confiar na contagem de testes: o SQL estava em 26%.

**Definição duplicada de um conceito de negócio diverge sozinha.** "Estoque baixo" existia
em dois lugares e as duas versões discordavam sobre produto inativo. Nenhuma revisão de
código pegou; um teste de integração pegou. Hoje há uma implementação só.

---

# Questão 2 — estrutura de pastas e camadas

Esta é a estrutura real deste repositório, e não uma proposta. Coerência entre o que está
escrito e o que está no código é critério da prova, então descrevo o que existe.

```
app/
  routers/       # endpoints HTTP
  services/      # regra de negócio
  repositories/  # único ponto que fala com o banco
  schemas/       # modelos Pydantic (contrato da API)
  models/        # modelos do ORM (tabelas)
  core/          # config, conexão de banco, Redis, segurança/JWT, cache, fila
  workers/       # tarefas de fila
  integracoes/   # gateways para outros bounded contexts
  mcp/           # servidor MCP
  tests/
main.py          # monta a aplicação e registra os routers
```

O fluxo é sempre **`router → service → repository`**, sem atalhos.

## Por que cada camada existe

**`routers/`** traduz HTTP em chamada de método e volta. Ele não monta SQL, não conhece
cache e não decide regra. O teste disso é concreto: se amanhã o mesmo CRUD precisasse ser
exposto por mensageria ou CLI, esta seria a única pasta descartada.

**`services/`** é onde mora a decisão de negócio. Ele levanta exceção de domínio
(`EstoqueInsuficiente`) e não sabe o que é status code — a tradução para HTTP acontece num
handler único em `main.py`. Isso não é purismo: o mesmo service é chamado pelo worker de
fila, que não tem request nenhum, e uma exceção que só faz sentido em HTTP quebraria ali.

**`repositories/`** concentra o SQL. É a camada que mais dá trabalho justificar, porque
uma referência conhecida da comunidade (`fastapi-best-practices`) coloca SQL dentro do
service. Mantive separado, e o retorno apareceu na prática: a política de cache inteira e a
regra de estoque são testadas com repository dublado, sem Postgres no ar, em milissegundos.

**`schemas/` separado de `models/`** é a separação que eu mais defendo. O contrato público
da API não é o schema do banco. Fundir os dois — que é o que o SQLModel faz — significa que
toda coluna nova vaza para a resposta por padrão; num ERP é assim que custo de compra
aparece num endpoint de catálogo.

**`core/`** guarda o que atravessa tudo e não pertence a um domínio: configuração validada
no boot, conexões, JWT, cache, fila. A invalidação de cache mora aqui de propósito, e não
no router, porque o worker também precisa invalidar e ele não passa por router nenhum.

**`workers/`** e **`integracoes/`** são entrypoints e saídas alternativos: um consome fila,
o outro fala com serviços de outros bounded contexts. Nenhum dos dois é persistência nem
regra, então nenhum caberia em `repositories/` ou `services/` sem fazer a camada mentir
sobre o que ela é.

**`tests/`** espelha a estrutura, com uma divisão que aprendi errando: testes rápidos com
dublê e testes de integração contra Postgres real, em arquivos separados.

## Como isso ajuda em testabilidade

O argumento fica concreto olhando o que a estrutura permite:

- **Regra de negócio sem infraestrutura.** `ProdutoService` recebe repository e Redis por
  construtor, então a suíte exercita a política de cache inteira com um Redis em memória e
  um repository dublado. Onze testes, 0,1 s.
- **Contrato testado sem subir servidor.** `httpx.AsyncClient` sobre `ASGITransport` fala
  direto com o app.
- **Falha de dependência simulável.** Trocar `get_session` por um objeto que levanta
  exceção é uma linha, e é assim que o teste de readiness degradado é determinístico.

E onde a estrutura **não** ajuda, que é honesto dizer: dublê não prova garantia de banco.
Meu `ON CONFLICT` estava escrito de um jeito que o Postgres recusa e o dublê passava
tranquilo, porque ele reimplementa o invariante em Python — validava a minha intenção, não
o meu SQL. Foi o que me levou a separar testes de integração.

## Como isso ajuda em manutenção

Cada camada tem **um** motivo para mudar. Trocar de banco mexe em `repositories/`. Mudar o
contrato da API mexe em `schemas/`. Regra nova mexe em `services/`. Quando o motivo da
mudança e o lugar da mudança coincidem, revisão de código fica curta e o risco de efeito
colateral cai.

## Princípios que inspiraram

**SOLID**, principalmente dois. *Single Responsibility* é o parágrafo acima: uma razão para
mudar por camada. *Dependency Inversion* é o que faz o service depender de uma abstração de
repository e não da sessão do SQLAlchemy — sem isso, testar regra exigiria banco.

**Clean Architecture**, na ideia de que a regra de negócio não sabe de onde o dado veio.
Infra é detalhe e detalhe fica na borda. O sinal de que isso está valendo neste projeto é
que o `EstoqueService` funciona igual chamado por HTTP e por worker de fila.

**DDD leve**, na divisão por bounded context da Questão 1 e no vocabulário: o código fala
`estoque_minimo`, `alerta aberto`, `movimento`, e não `entity`, `manager`, `helper`. Digo
"leve" de propósito: não uso agregados, value objects nem repositórios por raiz de
agregado, porque neste porte seria cerimônia sem retorno.

**O que eu conscientemente não segui:** a recomendação de organizar por domínio
(`app/produtos/`, `app/pedidos/`), que é o que o `fastapi-best-practices` defende. O
critério dele é porte — a frase completa diz que organizar por tipo "works well for
microservices or smaller projects", e este é um bounded context só. Está detalhado no
[ADR 0001](adr/0001-estrutura-em-camadas.md). Quando este serviço passar a ter vários
domínios no mesmo processo, a migração é mecânica: as camadas já estão separadas, muda só o
eixo de agrupamento.
