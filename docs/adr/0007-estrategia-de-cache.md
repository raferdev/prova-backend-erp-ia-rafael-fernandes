# ADR 0007 — Estratégia de cache e invalidação do catálogo

**Data:** 2026-08-20 · **Status:** aceito e implementado

## Contexto

A prova pede cache em pelo menos um endpoint de leitura, e pede a estratégia de
invalidação explicada. Decidi antes de escrever o CRUD, porque cachear primeiro e pensar
na invalidação depois é como se produz dado errado em produção.

O problema nasce assim: a primeira leitura vai ao Postgres e guarda o resultado no Redis;
a segunda nem toca no banco. Quando chega um `UPDATE`, ele atualiza o Postgres e o Redis
continua com o valor antigo, porque ninguém o avisou. A partir daí existem duas versões do
mesmo dado, e quanto melhor for a taxa de acerto do cache, mais tempo o valor errado
sobrevive: um cache eficiente é exatamente aquele que evita ir ao banco, ou seja, aquele
que nunca descobre sozinho que está desatualizado.

Um detalhe do domínio complica: a tabela de produto mistura dois tipos de dado com
naturezas opostas. Nome, descrição e preço são lidos o tempo todo e mudam raramente.
Quantidade em estoque muda a cada pedido e é o campo em que dado velho custa dinheiro.

## Decisão

### 1. O que nunca entra em cache

A quantidade em estoque não vale como fonte de verdade para decisão de escrita. Exibir na
tela um número com alguns segundos de atraso é aceitável, e é o que qualquer e-commerce
faz. Confirmar uma reserva com base nesse número não é. O caminho de reserva e baixa lê do
Postgres, sob lock distribuído (ver o oversell tratado na Parte 3).

Pela mesma lógica, consultas que **filtram** por estoque (o filtro de estoque baixo que a
prova pede) passam direto ao banco, sem cache. A regra fica fácil de explicar: cacheio o
que é estável, não cacheio o que é volátil. Um alerta de estoque baixo defasado não serve
para nada.

### 2. Chaves

| Chave | Conteúdo | TTL |
|---|---|---|
| `produto:{id}` | detalhe de um produto | 60s ± jitter |
| `produtos:v{N}:list:{fingerprint}` | uma página da listagem | 60s ± jitter |
| `produtos:version` | contador `N` | sem TTL |

O `fingerprint` é o hash dos parâmetros de filtro e paginação **normalizados**: ordeno as
chaves antes de gerar o hash, senão `?nome=cabo&pagina=1` e `?pagina=1&nome=cabo` viram
duas entradas para o mesmo resultado.

### 3. Invalidação

| Evento | Ação |
|---|---|
| criar produto | `INCR produtos:version` |
| atualizar produto | `DEL produto:{id}` + `INCR produtos:version` |
| remover produto | `DEL produto:{id}` + `INCR produtos:version` |
| worker mexe no estoque | `DEL produto:{id}` + `INCR produtos:version` |

Invalidar o detalhe é trivial porque a chave é conhecida. Invalidar a listagem é o
problema real: cada combinação de filtro e paginação criou uma chave diferente, geradas por
requests do passado, e quem processa o `PUT` não tem como saber quais existem agora.

Por isso a versão entra na chave. Um `INCR` torna todas as listagens antigas inalcançáveis
de uma vez, em O(1), sem varrer nada. As chaves órfãs somem sozinhas quando o TTL vence.

### 4. TTL é rede de segurança, não estratégia

Mantenho TTL mesmo tendo invalidação explícita, e os dois papéis são diferentes. A
invalidação é o mecanismo normal. O TTL cobre o caso em que ela falha: se o Redis estiver
indisponível no instante do `UPDATE`, a invalidação não acontece e sem TTL o dado errado
ficaria lá para sempre.

Ordem das operações: commit no Postgres primeiro, invalidação depois. Falha de
invalidação não derruba a escrita, mas é logada. Escrita que reverte porque o cache
piscou seria trocar um problema pequeno por um grande.

O TTL leva jitter de ±20% para as chaves não vencerem todas no mesmo segundo e derrubarem
uma avalanche de queries idênticas no Postgres.

### 5. Onde o código mora

Em `app/core/cache.py`, chamado pelo service, não pelo router.

O motivo é concreto: existe um segundo escritor no sistema, o worker de estoque, e ele não
passa por router nenhum. Invalidação implementada na camada HTTP significaria o worker
atualizar o banco e deixar o cache velho, por um caminho que ninguém está olhando.

## Opções que descartei

**`KEYS produtos:list:*`.** Bloqueia o Redis, que é single-threaded. Uma varredura num
keyspace grande trava todo mundo, inclusive os locks de estoque. Nunca em produção.

**`SCAN` com pattern.** Não bloqueia como o `KEYS`, mas continua sendo O(n) sobre o
keyspace inteiro e fica mais lento conforme o Redis cresce, para uma operação que roda em
toda escrita.

**Só TTL, sem invalidação explícita.** Simples e defensável para catálogo puro. Descartei
porque editar um preço e ele continuar aparecendo errado por um minuto é difícil de
justificar num ERP.

**Set auxiliar com as chaves de cada produto.** Funciona e é preciso, mas exige manter a
bookkeeping em dia e ela mesma pode ficar dessincronizada. Mais peças móveis para resolver
o que um contador resolve.

**Write-through.** Atualizar o cache junto com o banco em vez de apagar. Para a listagem
seria recalcular todas as páginas a cada escrita, o que não faz sentido.

## Consequências

Ganho: invalidação em O(1) independente de quantas chaves existam, e uma regra de negócio
clara sobre o que pode ou não ser servido de cache.

Pago:

- Chaves órfãs ocupando memória até o TTL vencer. O desperdício é limitado por
  TTL × taxa de escrita, e com 60s é irrelevante nesta escala. Numa escala em que passasse
  a doer, o `maxmemory-policy` do Redis com `allkeys-lru` resolve.
- Toda leitura de listagem passa a fazer duas idas ao Redis: uma para ler a versão, outra
  para ler a página. Dá para reduzir a uma com script Lua; não vou otimizar isso agora.
- Uma janela mínima de inconsistência entre o commit e o `INCR`. Um request que caia
  exatamente nesse intervalo pode gravar em cache um resultado já velho. É o mesmo tipo de
  janela que qualquer sistema com consistência eventual tem, e o TTL a limita.
- Não faço cache negativo (não guardo 404). Isso deixa a porta aberta para cache
  penetration se alguém varrer ids inexistentes. Com id sequencial ou UUID o risco é baixo
  e prefiro não complicar a invalidação de criação.

## Como validei

As seis asserções que listei aqui antes de escrever o código viraram testes, em
`app/tests/test_produto_cache.py`. Rodam sem Postgres e sem Redis, com repository dublado
e Redis em memória.

```
$ uv run pytest -q
33 passed in 0.14s
```

Além dos testes, exercitei o fluxo contra a API real, com Postgres e Redis do Compose:

```
$ curl -s -H "$A" $API/produtos/$ID | jq -r .preco
39.90
$ redis-cli EXISTS produto:$ID ; redis-cli GET produtos:version
1
(nil)

$ curl -s -X PATCH -H "$A" -d '{"preco":"29.90"}' $API/produtos/$ID
$ redis-cli EXISTS produto:$ID ; redis-cli GET produtos:version
0
1

$ curl -s -H "$A" $API/produtos/$ID | jq -r .preco
29.90
```

Detalhe apagado, versão incrementada, leitura seguinte com o valor novo. É exatamente o
passo 3 do problema descrito no contexto, agora fechado.

Também confirmei na API real que a consulta `?apenas_estoque_baixo=true` responde
corretamente e **não** cria chave de listagem no Redis: a contagem de chaves
`produtos:v*` fica igual antes e depois.

### Um bug que só apareceu ao escrever o teste

Minha primeira versão tratava a chave de versão ausente como valendo `1`. Só que `INCR`
numa chave inexistente cria a chave valendo exatamente `1`. Ou seja: a primeira
invalidação da vida do processo ia de 1 para 1 e **não invalidava nada**, e todas as
listagens gravadas antes dela continuariam sendo servidas.

Chave ausente passou a valer `0`. O teste `test_incr_invalida_listagens_de_filtros_diferentes_de_uma_vez`
cobre isso, e a verificação manual acima mostra a versão indo de ausente para `1` com o
efeito correto.

O que me chama atenção nesse erro é que ele não quebra nada de forma visível: a API
responde 200, os dados parecem certos e o defeito só aparece como preço desatualizado
algum tempo depois. Sem a asserção escrita antes, eu provavelmente não teria procurado.
