# Parte 7 — Portfólio

> ⚠️ **Esta seção está incompleta e precisa ser preenchida por mim antes da entrega.**
> Os marcadores `[PREENCHER]` indicam o que falta. Deixo o aviso visível de propósito, em
> vez de entregar texto genérico fingindo que está pronto.

---

## Projeto mais representativo

**Link:** `[PREENCHER: URL do repositório ou do sistema em produção]`

**O que é, em uma frase:** `[PREENCHER]`

### O problema que ele resolve

`[PREENCHER]`

> Guia do que responder aqui: qual era a dor concreta, de quem era a dor, e o que
> acontecia antes de existir. Evitar descrever a solução — a pergunta é sobre o problema.
> Um número ajuda: quantos usuários, qual volume, quanto tempo levava antes.

### Decisões técnicas que eu tomei

`[PREENCHER]`

> Guia: escolher de duas a quatro decisões e, para cada uma, dizer **o que eu descartei e
> por quê**. Decisão sem alternativa descartada soa como o único caminho que eu conhecia.
> O mesmo formato dos ADRs deste repositório funciona bem: contexto, opções, escolha,
> o que estou pagando por ela.

### O que eu faria diferente hoje

`[PREENCHER]`

> Guia: esta é a pergunta que mais separa candidatos, e a resposta fraca é "nada" ou uma
> autocrítica genérica de organização de código. A resposta forte nomeia uma decisão
> específica, explica por que ela pareceu certa na época e o que eu aprendi depois que
> mudaria minha escolha.

---

## Este projeto como peça de portfólio

Esta parte eu posso escrever agora, porque o trabalho é deste repositório.

**Link:** https://github.com/raferdev/prova-backend-erp-ia-rafael-fernandes

**O que é:** módulo de Pedidos e Estoque de um ERP em FastAPI, com cache Redis com
invalidação por versão, worker de fila idempotente, agregação paralela com degradação
graciosa, consulta em linguagem natural sem LLM e um servidor MCP funcional.

### Decisões que eu defendo

As dez estão em [`docs/adr/`](adr/), cada uma com o que descartei e a saída do comando que
usei para validar. As três que eu levaria para uma conversa:

**Invalidação de cache por namespace versionado.** Um `INCR` derruba todas as listagens em
O(1). A alternativa óbvia — varrer as chaves com `SCAN` — é O(n) sobre o keyspace inteiro
numa operação que roda em toda escrita, e `KEYS` bloqueia o Redis, que é single-threaded.

**A camada de repository, contra uma referência conhecida.** O `fastapi-best-practices`
coloca o SQL no service. Mantive a separação e ela pagou: a política de cache e a regra de
estoque são testadas sem Postgres no ar.

**Idempotência no worker via chave única.** Fila entrega pelo menos uma vez. A tabela
`movimento_estoque` transforma reentrega em no-op — e ela se provou em condição real, não em
teste: um job falhou depois de commitar, o `arq` reentregou, e o saldo continuou correto.

### O que eu faria diferente, neste projeto

Quatro coisas, em ordem de quanto me incomodam:

**Testes de integração desde o começo, e não depois de medir cobertura.** Escrevi toda a
suíte com dublê achando que estava coberto. A medição mostrou o SQL em 26% — e quando
finalmente escrevi teste contra Postgres real, ele achou dois bugs em minutos: um
`ON CONFLICT` que o Postgres recusa e duas definições divergentes de "estoque baixo". Hoje
eu escreveria um teste de integração junto com o primeiro repository, não no fim.

**O lock distribuído do oversell não existe.** É o problema mais interessante do domínio e
ficou como decisão registrada em vez de código. Está anotado como limite explícito no
[ADR 0008](adr/0008-worker-de-estoque.md), mas é o que eu atacaria primeiro com mais tempo.

**O `APP_DEBUG` liga o echo de SQL do SQLAlchemy, e o log do worker fica ilegível.** Cada
job despeja o SQL inteiro. Funciona, e eu separaria o nível de log da aplicação do do ORM.

**O parser da Q8 é por regras e tem teto.** Ele entende as formas que eu previ e recusa o
resto — recusar é o comportamento certo, mas cada frase nova exige código. O passo seguinte
seria classificação de intenção com modelo local pequeno, mantendo a extração de valores
determinística: modelo para interpretar, código para executar.

---

## Outros links

- `[PREENCHER: GitHub pessoal]`
- `[PREENCHER: LinkedIn]`
- `[PREENCHER: site ou blog, se aplicável]`
