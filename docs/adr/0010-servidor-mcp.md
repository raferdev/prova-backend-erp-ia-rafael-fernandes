# ADR 0010 — Servidor MCP funcional sobre a API do ERP

**Data:** 2026-08-20 · **Status:** aceito, implementado

## Contexto

O enunciado pede a Q9 como design escrito, não como código. Implementei mesmo assim, por
dois motivos.

Um servidor MCP **expõe ferramentas e não chama modelo nenhum** — quem chama LLM é o
cliente do outro lado. Então isto não esbarra na restrição de não integrar com LLM de
terceiro em runtime.

E porque design que nunca virou código é design não testado. A seção seguinte mostra que
essa desconfiança se justificou.

## Decisões

### O servidor fala HTTP com a nossa API, não com o banco

É a decisão mais importante, e ela vem do próprio documento de design: o servidor MCP entra
como mais um consumidor do gateway, não como serviço privilegiado.

Ir direto ao banco seria mais simples e mais rápido. Erraria em três frentes de uma vez:
contornaria validação e cache que a API implementa; daria ao agente acesso mais amplo que o
do usuário que iniciou a conversa; e tiraria o tráfego do agente da mesma observabilidade
do resto do sistema.

Com HTTP e JWT, o agente herda exatamente as permissões do token que carrega. "Usuário robô
com acesso total" fica impossível por construção, não por disciplina.

O custo é real e eu aceito: uma camada de rede a mais em cada chamada de ferramenta.

### Ação destrutiva em duas etapas

`preparar_ajuste_estoque` devolve preview com valores resolvidos e um token de dois
minutos; `confirmar_ajuste_estoque` executa. A primeira chamada não altera nada.

O problema que isso resolve não é modelo malicioso, é modelo confiante. E o preview é onde
a alucinação morre: se o modelo errou o produto, quem lê vê o nome errado antes de
confirmar.

O token é consumido no resgate. Sem isso, o mesmo token repetido criaria duas
movimentações — a mesma armadilha de idempotência do [ADR 0008](0008-worker-de-estoque.md).

### Falha nunca vira resultado vazio

Erro ao falar com o ERP devolve `{"status": "indisponivel"}` com uma observação explícita
de que aquilo **não** significa ausência de dados. Um modelo que recebe lista vazia conclui
e afirma que não há nada.

É o mesmo princípio da Parte 2 e do parser da Q8, agora na terceira aplicação. Gosto que
seja: princípio que se repete em contextos diferentes é princípio, não coincidência.

### Schemas derivados das assinaturas

O SDK v2 monta o JSON Schema a partir da função tipada e da docstring. Preferi isso a
escrever schema à mão: duas fontes de verdade divergem, e a assinatura é a que o código
obedece de fato.

As descrições dizem o que a chamada **causa**, não o que ela é — é o que o modelo lê para
decidir. `produto_id` é UUID e a descrição manda obter com `consultar_estoque` em vez de
deduzir do nome, para o modelo não resolver o produto sozinho e acertar o errado.

## O que a implementação me ensinou, e o documento não sabia

No design eu escrevi que `additionalProperties: false` impede argumento alucinado de passar.
Implementando, descobri que **não impede**.

O SDK aceita o argumento desconhecido, descarta em silêncio e devolve sucesso:

```
$ consultar(nome="cabo", desconto_maximo=30)
is_error: False
conteudo: chamado com nome=cabo
```

O `desconto_maximo` evaporou e a chamada foi "bem-sucedida". É exatamente o efeito que eu
queria evitar: consulta com escopo diferente do pedido, respondida com cara de correta.

Isso muda o princípio, não só a implementação: **o schema é declaração de intenção para o
modelo, e quem protege é o servidor.** Por isso existe a subclasse `ServidorERP`, que
valida os argumentos contra o schema publicado antes de despachar e recusa a chamada
dizendo quais argumentos são aceitos.

Corrigi o documento de design marcando o parágrafo original e explicando o que mudou, em
vez de reescrevê-lo como se eu já soubesse.

## Consequências

Pago: mais um entrypoint para manter (`app/mcp/`), uma dependência nova (`mcp`), e a
latência da camada HTTP.

Assumo também que os tokens de confirmação ficam em memória. Reiniciar o servidor descarta
confirmações pendentes e o usuário precisa pedir de novo — aceitável para um token de dois
minutos, e evita acoplar o servidor ao Redis só por isso. Com várias instâncias, iria para
o Redis que já está no stack.

## Como validei

100 testes na suíte, e o servidor exercitado por um cliente MCP real via stdio, não por
chamada de função:

```
conectado ao servidor: erp-pedidos-estoque

ferramentas publicadas:
  [leitura]  consultar_estoque
  [leitura]  consultar_alertas
  [leitura]  perguntar_sobre_catalogo
  [escrita] preparar_ajuste_estoque
  [escrita] confirmar_ajuste_estoque

--- consultar_estoque(apenas_estoque_baixo=True) ---
  total=3
    Hub USB-C 7 portas: 0 un (min 4)
    Monitor 27 polegadas: 3 un (min 5)

--- perguntar_sobre_catalogo (usa o parser da Q8) ---
  interpretacao: Listar produtos com preço de no mínimo 200.

--- guardrail: pergunta ambigua ---
  entendida: False
  ambiguidade: Entendi um limite de 10, mas não de qual campo: estoque ou preço?

--- acao destrutiva em 'Cabo HDMI 2m' (saldo 120) ---
etapa 1: preparar
  preview: Baixar 3 unidade(s) de "Cabo HDMI 2m". Saldo atual 120, ficara 117.
  saldo apos preparar: 120 (inalterado)
etapa 2: confirmar
  status: enfileirado  job: 76529d8a
etapa 3: reusar o mesmo token
  status: erro (token invalido, ja usado ou expirado)

  saldo final apos o worker processar: 117
```

A última linha fecha o circuito inteiro do projeto: o agente chamou uma ferramenta MCP, que
chamou a API REST, que enfileirou um job, que o worker `arq` processou, que invalidou o
cache e resolveu o alerta.
