# ADR 0009 — Consulta paralela com degradação graciosa

**Data:** 2026-08-20 · **Status:** aceito, implementado

## Contexto

O endpoint consulta Clientes, Financeiro e Logística ao mesmo tempo. É o caso que descrevi
na Parte 1 como "síncrono quando o fluxo depende da resposta agora": o módulo de Pedidos
precisa dos três para montar um contexto de venda, e de nenhum deles depois.

O enunciado pede `asyncio.gather`, timeout individual e degradação graciosa. `gather`
sozinho não entrega isso, e as lacunas é que são as decisões.

## Decisões

### Falha nunca vira dado

A mais importante, e a que o enunciado não pede.

Se o Financeiro cai e a resposta traz `saldo_devedor: 0` ou `{}`, o consumidor conclui que
o cliente está limpo e libera a venda. Cada fonte devolve `status` próprio e `dados: null`
quando falhou — nunca objeto vazio, nunca valor padrão. Existe um teste só para isso.

O corpo também traz `completo` e `fontes_indisponiveis`, para o consumidor não precisar
reimplementar a varredura dos status.

### 200 mesmo degradado, não 502

Degradação graciosa é entregar o que deu para obter dizendo o que faltou. Um 502 jogaria
fora as duas fontes que responderam.

O corolário: este endpoint entrega **contexto, não veredito**. Quem decide recusar a venda
por falta de dado é o módulo de Pedidos, com a política dele. Eu não codifico essa
política aqui.

### Orçamento total além do timeout por fonte

Timeout por tentativa vezes número de tentativas é o erro clássico: 1s com 3 tentativas
vira 3s de latência real. Cada tentativa só acontece se ainda houver orçamento, e a janela
dela é o menor entre o timeout configurado e o que sobrou.

Números: 0,8s por tentativa, 2s de orçamento total. Acima disso o usuário de um checkout já
considerou o sistema travado, e responder degradado é melhor que responder tarde.

### Retry também em timeout, limitado a duas tentativas

Retentar timeout é discutível, porque pode dobrar a latência. Faço porque a causa mais
comum de timeout curto é pico passageiro, e o que torna seguro é o orçamento total.

Duas tentativas, com espera curta e fixa. Sem backoff exponencial longo: há um usuário
esperando, e o que não respondeu rápido duas vezes deve virar degradação, não mais espera.

### `return_exceptions=True` no gather

É a diferença entre `Promise.all` e `Promise.allSettled`. Sem isso, a primeira falha
descarta as respostas que já tinham chegado. A função `consultar` já não deixa exceção
escapar, mas prefiro a garantia declarada no `gather` a depender do comportamento dela.

### Pasta `app/integracoes/`

Gateway para outro bounded context não é persistência (`repositories/` fala com o banco)
nem regra de negócio (`services/`). Coloquei em pasta própria e atualizei a estrutura no
README, para o código e a documentação continuarem batendo.

Os mocks têm a mesma assinatura de um cliente HTTP real: função async que pode demorar,
falhar ou responder. Trocar por `httpx` não muda nada em `services/contexto.py`.

## Consequências

Pago: mais superfície de configuração (dois números que precisam ser revisados quando as
latências reais aparecerem), e a suíte de testes ficou ~4s mais lenta, porque dois testes
esperam o orçamento estourar de verdade em vez de simular o relógio.

Assumo também que o orçamento é fixo e não adaptativo. Um sistema maior usaria circuit
breaker: depois de N falhas seguidas, parar de chamar a fonte por um tempo em vez de pagar
o timeout a cada requisição. Não implementei — com três fontes mock seria cerimônia sem
ganho observável.

## Como validei

```
$ uv run pytest -q
58 passed in 5.04s
```

Na API real, o paralelismo aparece no número: cada fonte levou ~49ms e o total foi 50ms,
não 150ms.

```
completo=True  latencia_total=50ms
clientes    status=ok  49ms  dados=sim
financeiro  status=ok  49ms  dados=sim
logistica   status=ok  50ms  dados=sim
```

Financeiro fora do ar: 200 em 57ms, duas tentativas, dados nulos, e as outras duas intactas.

```
HTTP 200  completo=False  indisponiveis=['financeiro']
clientes    status=ok      tent=1  dados=sim
financeiro  status=erro    tent=2  dados=NULL  ServicoIndisponivel: financeiro recusou a conexao
logistica   status=ok      tent=1  dados=sim
```

Logística dormindo 5s: o orçamento corta em 1,65s e o resto responde.

```
HTTP 200  tempo_real=1.65s  indisponiveis=['logistica']
logistica   status=timeout tent=2  dados=NULL  nao respondeu em 0.80s
```

Fonte instável (falha na primeira, responde na segunda): o retry recupera e a resposta sai
completa.

```
HTTP 200  completo=True
clientes    status=ok  tent=2  dados=sim
```
