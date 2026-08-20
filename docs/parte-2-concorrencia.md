# Parte 2 — Assíncrono e concorrência

## Questão 3 — `asyncio`, `threading` e `multiprocessing`

A pergunta que separa os três não é "qual é mais rápido", é **quem está segurando o
trabalho**: a rede, ou o processador.

### `asyncio` — um processo, uma thread, troca cooperativa

Existe um event loop só. Quando uma corrotina chega num `await` que espera I/O, ela devolve
o controle e o loop roda outra. Não há paralelismo: há **intercalação**, e ela é
suficiente porque o tempo estava sendo gasto esperando, não calculando.

A troca é cooperativa, e a palavra importa. Nenhuma corrotina é interrompida à força — ela
cede quando quer. Isso torna o custo por tarefa muito baixo (milhares de conexões
simultâneas num processo) e cria a armadilha correspondente: **uma chamada bloqueante
dentro de código `async` congela o loop inteiro**. Não é a sua função que trava, é o
serviço.

Vindo de Node, o modelo é familiar. A diferença desconfortável é que em Python é fácil
chamar sem querer uma biblioteca síncrona, porque a maioria do ecossistema é síncrona por
padrão. Foi por isso que liguei a regra `ASYNC` do ruff neste projeto: ela acusa chamada
bloqueante dentro de rota `async` no lint, em vez de eu descobrir em produção com a
latência subindo sem explicação.

**Uso quando:** I/O de rede, banco e cache, com muita coisa acontecendo ao mesmo tempo.

### `threading` — várias threads, uma de cada vez executando Python

Threads do sistema operacional, com troca preemptiva. Mas o **GIL** garante que apenas uma
execute bytecode Python por vez, então threading **não dá ganho em trabalho de CPU** — só
custo de troca de contexto.

O que ele resolve é diferente: o GIL é **liberado durante I/O**. Então enquanto uma thread
espera a resposta de um socket, outra roda. É o que torna threading útil justamente onde
`asyncio` não alcança: **bibliotecas síncronas que não têm versão async**.

É o que o FastAPI faz por baixo dos panos quando você declara uma rota com `def` em vez de
`async def` — ele a joga num threadpool para não travar o loop.

**Uso quando:** preciso de I/O concorrente mas a biblioteca é síncrona e não dá para trocar.
Threads custam bem mais memória que corrotinas, e o pool é finito — encher o threadpool
deixa a aplicação lenta de um jeito difícil de diagnosticar.

### `multiprocessing` — vários processos, GIL nenhum no caminho

Cada processo tem seu interpretador e seu GIL, então roda de verdade em paralelo em vários
núcleos. É a única das três que aumenta throughput de **CPU**.

O preço é real: cada processo tem sua memória, os dados precisam ser serializados para
atravessar a fronteira (`pickle`), e subir processo custa tempo. Se a tarefa é curta, o
overhead come o ganho.

**Uso quando:** o trabalho é de processador e não de espera.

### Resumo

| | Paralelismo real | Custo por tarefa | Serve para |
|---|---|---|---|
| `asyncio` | não (intercala) | baixíssimo | I/O com bibliotecas async |
| `threading` | não (GIL) | médio | I/O com bibliotecas síncronas |
| `multiprocessing` | sim | alto | CPU |

---

## Os três cenários, no ERP

### Chamar 3 APIs externas → `asyncio`

Montar o contexto de uma venda precisa de dados de Clientes, Financeiro e Logística. O
tempo é quase todo espera de rede, e as três esperas podem acontecer juntas.

É o que está implementado em `GET /integracoes/contexto-de-venda/{cliente_id}`, e o número
mostra o efeito: cada fonte responde em ~49 ms e a resposta sai em **50 ms**, não 150.

Sequencial somaria as latências. Threading funcionaria e gastaria três threads para ficar
esperando socket — desperdício. Multiprocessing seria absurdo: três processos parados
esperando rede.

O que o exercício me obrigou a resolver, e que `gather` sozinho não resolve, está no
[ADR 0009](adr/0009-consulta-paralela-degradacao.md): timeout por fonte, orçamento total
para o retry não multiplicar a latência, e a regra de que falha nunca vira dado.

### Processar um CSV grande de importação de produtos → depende, e é onde erra quem decide sem medir

A resposta reflexa é "é arquivo, logo é I/O, logo threads". Ler o arquivo é I/O mesmo — e
costuma ser a parte barata.

O caro é o que vem depois: validar dez mil linhas, converter tipos, normalizar texto,
conferir duplicidade. Isso é **CPU**, e nem asyncio nem threading ajudam.

Como eu faria: ler em streaming (nunca carregar o arquivo inteiro na memória), dividir em
blocos e distribuir os blocos entre processos com `ProcessPoolExecutor`. O I/O fica no
processo principal, o trabalho pesado vai para os núcleos.

E o gatilho vem de fila, não de request HTTP: quem sobe uma planilha de dez mil produtos
recebe `202` e um identificador, exatamente como o ajuste de estoque deste projeto
responde `202` e enfileira.

Antes de decidir, eu mediria. Se o CSV for pequeno e o gargalo for o `INSERT` no banco, a
resposta muda completamente: aí é I/O, e o ganho está em inserção em lote, não em
paralelismo.

### Gerar um relatório pesado em PDF → `multiprocessing`

Renderizar um PDF de fechamento mensal é processador puro: montar layout, desenhar tabela,
comprimir. O GIL torna threading inútil aqui, e `asyncio` seria pior que inútil — sem
`await`, a geração bloqueia o event loop e a API inteira para de responder enquanto o
relatório é montado.

Na prática, no desenho deste projeto: a rota enfileira o job e responde `202`; o worker
`arq` consome; e a geração em si roda num processo separado, via
`loop.run_in_executor(ProcessPoolExecutor(), gerar_pdf, dados)`. É a ressalva que registrei
no [ADR 0003](adr/0003-fila-com-arq.md) quando escolhi o `arq`: worker async é ótimo para
tarefa de I/O, e tarefa de CPU precisa sair do processo mesmo assim.

### Um quarto caso, que aparece muito em ERP e não está na lista: `threading`

Integração fiscal. SDK de emissão de nota, cliente de SEFAZ, biblioteca de certificado
digital — quase sempre síncronos, sem versão async, e sem chance de eu reescrever.

Aí a resposta é `run_in_threadpool` do Starlette: a chamada bloqueante sai do event loop e
vai para uma thread, o loop continua atendendo. Não é o desenho mais bonito; é o que
permite conviver com o ecossistema que existe.

---

## Questão 4 — implementação

`GET /integracoes/contexto-de-venda/{cliente_id}`, em
[`app/services/contexto.py`](../app/services/contexto.py) e
[`app/integracoes/base.py`](../app/integracoes/base.py).

| Requisito do enunciado | Onde está |
|---|---|
| `asyncio.gather` para paralelizar | `ContextoService.montar`, com `return_exceptions=True` |
| Timeout individual sem derrubar a resposta | `consultar()`, com `asyncio.timeout` por tentativa |
| Retry simples | duas tentativas, limitadas por orçamento total |

Três decisões que fui além do pedido, e o porquê está no
[ADR 0009](adr/0009-consulta-paralela-degradacao.md):

**`return_exceptions=True`** é a diferença entre `Promise.all` e `Promise.allSettled`. Sem
ele, a primeira falha descarta as respostas que já tinham chegado.

**Orçamento total além do timeout por fonte.** 0,8 s por tentativa × 2 tentativas viraria
1,6 s por fonte. Cada tentativa só acontece se ainda houver orçamento, e a janela dela é o
menor entre o timeout configurado e o que sobrou.

**Falha nunca vira dado.** Cada fonte devolve `status` próprio e `dados: null` quando falha
— nunca objeto vazio. Se o Financeiro cai e a resposta trouxesse `saldo_devedor: 0`, o
módulo de Pedidos concluiria que o cliente está limpo e liberaria a venda.

Verificado na API real:

```
tudo no ar          → completo=True   latencia_total=50ms
financeiro fora     → HTTP 200, financeiro dados=NULL, as outras duas intactas
logistica dormindo 5s → HTTP 200 em 1,65s, status=timeout
fonte instavel      → retry recupera na 2a tentativa, resposta completa
```
