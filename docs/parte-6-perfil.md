# Parte 6 — Perfil

> **Cenário.** Você é alocado para escrever uma frente nova de alto throughput e baixa
> latência, e a decisão do time é fazê-la em Go. Você não conhece Go. Como reage?

## Reajo bem, e o motivo não é boa vontade

Go é a escolha adequada para esse cenário, e reconhecer isso primeiro me parece mais
honesto do que negociar a stack.

Alta concorrência com baixo overhead por conexão é o problema para o qual as goroutines
foram feitas — o custo de uma é ordens de magnitude menor que o de uma thread do sistema.
Binário único e estático simplifica deploy e derruba o tempo de cold start, que importa
justamente em serviço que escala rápido. E ausência de GIL significa paralelismo real em
CPU, que é exatamente a limitação que este projeto em Python tem: escrevi no
[ADR 0003](adr/0003-fila-com-arq.md) que tarefa CPU-bound precisa de processo separado, e
em Go isso não é uma discussão.

Discutir a escolha aqui seria discutir preferência minha, não a necessidade do sistema.

## Como eu me colocaria em produção rápido

Já troquei de stack antes — Node, Java, Python — e o que aprendi é que o gargalo não é a
sintaxe. Sintaxe se resolve em dias. O que demora é o **idioma**: o jeito que a comunidade
resolve os problemas e as armadilhas que só aparecem em produção.

Meu caminho seria:

**Primeiro, o que transfere direto.** Camadas, injeção de dependência, contrato separado do
modelo de persistência, teste com dublê. Isso é desenho, não linguagem, e é a maior parte do
que eu faço.

**Depois, o que é específico e não tem equivalente.** Em Go seriam `context.Context` para
cancelamento e deadline, canais e `sync` para coordenação, o modelo de erro como valor de
retorno em vez de exceção, e as armadilhas conhecidas — variável capturada em loop, `nil`
interface que não é `nil`, goroutine que vaza porque ninguém fecha o canal.

**E o linter como rede.** É a mesma tática que usei nesta prova: liguei a regra `ASYNC` do
ruff, que pega chamada bloqueante dentro de rota `async`. É a armadilha número um do
FastAPI e não existe equivalente no Node, então preferi que o linter cuidasse disso em vez
da minha memória. Em Go eu faria o mesmo com `go vet` e `golangci-lint` desde o primeiro
commit.

**Pedindo revisão explícita no começo.** Nos primeiros PRs eu diria em voz alta: "sou novo
em Go, revise idioma e não só correção". A alternativa é escrever Go com sotaque de
TypeScript por três meses sem ninguém falar nada.

## Já fiz isso, e tem código público

Prefiro mostrar do que afirmar, e a evidência mais direta é de 2022: o
[payment_processor](https://github.com/raferdev/payment_processor) é um sistema de três
serviços em **três linguagens diferentes**, construído em uma semana — gateway em Node com
TypeScript, serviço de análise de fraude em Python com Keras, e serviço de regras em Ruby on
Rails.

Escolhi cada uma pelo que o serviço precisava, não pelo que eu sabia melhor. Rails entrou
porque o serviço de regras era CRUD de blacklist com validação, e Rails entrega isso mais
rápido do que qualquer outra coisa — mesmo sendo a linguagem que eu menos dominava das três.

É literalmente o cenário da pergunta, já vivido: o problema pediu uma ferramenta que eu não
tinha, e a resposta foi aprender o suficiente para entregar bem naquele escopo.

Aprendi também o custo, e isso está registrado no meu portfólio como autocrítica: três
toolchains numa POC de uma semana foi caro, e hoje eu manteria a poliglossia só onde ela
paga. Adotar linguagem nova não é gratuito, e reconhecer isso é parte de saber quando ela
vale.

## E esta prova é a evidência recente

Este repositório é Python e FastAPI, que não é minha stack principal — meu histórico é Node,
NestJS e TypeScript.

O que a troca produziu, na prática:

- A arquitetura veio inteira da experiência anterior. O fluxo `router → service →
  repository` é o mesmo modelo do NestJS, com outro nome.
- As armadilhas idiomáticas eu fui atrás em vez de esperar tropeçar. `expire_on_commit=False`
  na sessão do SQLAlchemy, a diferença entre `gather` com e sem `return_exceptions`, o fato
  de o FastAPI expandir só um modelo Pydantic por endpoint como query string.
- E encontrei coisas que só aparecem quando o código roda. `INCR` numa chave inexistente
  resulta em 1, o que fazia a primeira invalidação do cache não invalidar nada. O SDK do MCP
  aceita argumento fora do schema e descarta em silêncio. Nenhuma das duas está na
  documentação de forma óbvia; as duas viraram teste.

Cada uma dessas está registrada num ADR, com a saída do comando que usei para verificar. É
esse rastro que eu levaria para Go: não a certeza de já saber, mas o hábito de conferir e
deixar registrado o que descobri.

## O que eu perguntaria antes de começar

Abertura não é aceitar sem pensar. Eu levantaria quatro pontos, e nenhum deles é objeção:

**Quem no time já é sênior em Go?** Se ninguém for, o risco não é meu — é do projeto, e
muda o plano: entra pair programming, ou uma consultoria pontual, ou um piloto menor antes
da frente inteira.

**Qual o número que define "alto throughput"?** Sem isso, "rápido" é opinião. Com um alvo,
dá para medir se a escolha entregou.

**Quanto do ecossistema existente precisa ser reescrito?** Cliente de autenticação,
observabilidade, log estruturado, migrations. Se cada um virar um mês, o custo real da
decisão é maior que o de aprender a linguagem.

**Como fica a manutenção em duas linguagens?** Não é argumento contra Go — é planejamento.
Duas stacks significam dois pipelines, dois conjuntos de dependências para atualizar, e um
plantão que precisa saber as duas.

## Em uma frase

Mentalidade de dono, para mim, é essa: a linguagem é ferramenta, o problema é que manda, e
quando o time escolhe uma ferramenta melhor para o problema meu trabalho é aprender rápido
e ajudar a reduzir o risco da transição — não defender o que já sei.
