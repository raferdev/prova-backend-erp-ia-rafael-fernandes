# Parte 7 — Portfólio

## Projeto mais representativo

**[payment_processor](https://github.com/raferdev/payment_processor)** — simulação de
processamento de pagamento com análise de fraude, construída em uma semana.

Escolho este e não outro porque ele é o que mais se parece com o trabalho real: não é um
CRUD bonito, é um fluxo de ponta a ponta com serviços que precisam concordar entre si para
uma transação ser aprovada.

### O problema

Entender, na prática, como funciona o mercado adquirente: o que acontece entre o cliente
passar o cartão e a transação ser aprovada ou negada, e onde entra a decisão de fraude.

Ler sobre isso não resolve. A pergunta que só aparece implementando é: quando três sistemas
precisam concordar para aprovar um pagamento, **o que acontece quando um deles não
responde?**

### A arquitetura

Três serviços, em três linguagens diferentes:

```
        cliente
           │
           ▼
   ┌───────────────┐   Redis (bloqueio rápido de repetição)
   │    Gateway    │   Postgres (credenciais)
   │  Node + TS    │
   └───────┬───────┘
           │ dispara as duas ao mesmo tempo
     ┌─────┴─────┐
     ▼           ▼
┌─────────┐  ┌──────────┐
│   ML    │  │  Rules   │
│ Python  │  │  Rails   │
│ Keras   │  │ blacklist│
└─────────┘  └──────────┘
  % de fraude    aprova/nega

  qualquer negativa derruba a transação
```

O gateway aplica as proteções baratas primeiro — Redis para rejeitar repetição do mesmo
usuário sem gastar processamento — e só então consulta os dois avaliadores em paralelo.

### Decisões técnicas, e o que descartei

**Node no gateway.** Escolhi pelo que a linguagem faz bem no papel dele: I/O concorrente e
orquestração de requisições paralelas. Um gateway é quase todo espera de rede, e é o caso em
que o modelo assíncrono paga.

**Python com Keras no serviço de ML, em vez de mais regras estáticas.** Regra estática pega
o que você já sabe que é fraude. O modelo existe para o caso que a regra não previu, e
devolve percentual em vez de sim/não — o que permite calibrar o limiar depois sem
reescrever a regra.

**Ruby on Rails no serviço de regras.** Aqui a decisão foi por velocidade de construção: era
CRUD de blacklist com validação, e Rails entrega isso mais rápido que qualquer outra coisa
que eu conhecesse. Assumi conscientemente o custo de uma terceira linguagem.

**Redis antes do Postgres no caminho.** Rejeitar repetição em memória custa ordens de
magnitude menos que ir ao banco. É a mesma ideia que reaproveitei nesta prova: as
verificações baratas primeiro.

**Docker separado por ambiente** (desenvolvimento, teste, produção), com compose próprio
para cada. Foi o que permitiu ter testes de integração rodando em CI contra os serviços de
verdade, e não contra mock.

### O que eu faria diferente hoje

Esta é a parte que mais mudou, e o projeto desta prova é a evidência de que mudou.

**O fan-out não tem degradação, e é o defeito mais sério.** O gateway consulta ML e Rules em
paralelo e derruba a transação se qualquer um falhar. Isso confunde duas coisas muito
diferentes: *"o modelo avaliou e reprovou"* e *"o modelo não respondeu"*. Na prática, uma
instabilidade no serviço de ML vira recusa de venda legítima.

Hoje eu faria como fiz [nesta prova](adr/0009-consulta-paralela-degradacao.md): timeout por
fonte, orçamento total, e cada fonte devolvendo o próprio status — com a regra de que falha
nunca vira dado. Se o avaliador não respondeu, quem decide o que fazer com isso é a política
de negócio, não o acidente de rede. Numa transação de pagamento, essa distinção é dinheiro.

**Três linguagens numa POC de uma semana foi caro.** Aprendi muito, e foi o objetivo. Mas
são três toolchains, três formas de testar e três conjuntos de dependências para atualizar.
Hoje eu manteria a poliglossia só onde ela paga — o serviço de ML em Python paga; o serviço
de regras em Rails eu escreveria no gateway.

**Sem observabilidade.** Não há trace id atravessando os três serviços. Quando uma transação
é negada, não dá para responder *qual* avaliador negou e por quê sem ler log de três lugares
e cruzar na mão. Hoje isso entraria desde o primeiro commit, e é o que defendo na
[Parte 1](parte-1-arquitetura.md).

**Sem idempotência na transação.** Um retry do cliente cria uma cobrança nova. É o mesmo
erro que cometi de novo no worker desta prova e só percebi ao configurar retry — a diferença
é que agora eu procuro por isso.

---

## Este projeto, como peça de portfólio

**[prova-backend-erp-ia-rafael-fernandes](https://github.com/raferdev/prova-backend-erp-ia-rafael-fernandes)**

Módulo de Pedidos e Estoque em FastAPI: cache Redis com invalidação por versão, worker de
fila idempotente, agregação paralela com degradação, consulta em linguagem natural sem LLM e
um servidor MCP funcional. 126 testes, 90% de cobertura, dez decisões registradas em
[`docs/adr/`](adr/) com a saída do comando que validou cada uma.

As três decisões que eu defenderia numa conversa:

**Invalidação de cache por namespace versionado.** Um `INCR` derruba todas as listagens em
O(1). `SCAN` seria O(n) sobre o keyspace numa operação que roda em toda escrita, e `KEYS`
bloqueia o Redis, que é single-threaded.

**A camada de repository, contra uma referência conhecida da comunidade.** O
`fastapi-best-practices` coloca o SQL no service. Mantive a separação e ela pagou: a política
de cache e a regra de estoque são testadas sem Postgres no ar.

**Idempotência no worker via chave única.** Fila entrega pelo menos uma vez, e a tabela
`movimento_estoque` transforma reentrega em no-op. Ela se provou em condição real, não em
teste: um job falhou depois de commitar, o `arq` reentregou, e o saldo continuou correto.

E o que eu faria diferente aqui está escrito com a mesma honestidade em
[o que faria diferente](#o-que-eu-faria-diferente-hoje-neste-projeto).

### O que eu faria diferente hoje, neste projeto

**Teste de integração desde o começo, não depois de medir cobertura.** Escrevi a suíte
inteira com dublê achando que estava coberto; a medição mostrou o SQL em 26%. Quando enfim
testei contra Postgres real, ele achou dois bugs em minutos.

**O lock distribuído do oversell não existe.** É o problema mais interessante do domínio e
ficou como decisão registrada em vez de código.

**O parser em linguagem natural é por regras e tem teto.** O passo seguinte seria
classificação de intenção com modelo local pequeno, mantendo a extração de valores
determinística: modelo para interpretar, código para executar.

---

## Outros links

**[classification_with_sklearn](https://github.com/raferdev/classification_with_sklearn)** —
início dos meus estudos de machine learning, em 2023: classificação supervisionada com
sklearn e pandas, modelagem de dados e escalonamento de features. É estudo, não produção, e
está aqui como marco de quando comecei a olhar para IA além de consumir API pronta.

**[Stack Overflow](https://stackoverflow.com/users/20442134/rafael-fernandes)** — respostas
com pontuação, principalmente em 2022. Não é um perfil de alta reputação; está aqui porque
mostra que eu explico o que aprendo, e explicar é como eu descubro que entendi.

**[WakaTime](https://wakatime.com/@raferdev)** — cerca de 4 mil horas de código medidas.
Vale dizer o que a métrica é: tempo com o editor aberto, não qualidade nem entrega. Ela
mostra constância, e só isso.

**[GitHub](https://github.com/raferdev)**
