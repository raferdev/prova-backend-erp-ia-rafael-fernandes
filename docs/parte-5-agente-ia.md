# Parte 5 — Agente de IA sobre o ERP

Q8 (a prática) está implementada: `POST /consultas/produtos`, parser determinístico em
`app/services/parser_consulta.py`. Este documento é a Q9, o design.

Uma restrição atravessa tudo o que segue: **nenhuma chamada a LLM de terceiro em runtime**,
conforme o enunciado. O que descrevo aqui é como eu conectaria um agente ao ERP, não uma
integração que este repositório executa.

---

## 1. Tool calling: o desenho das ferramentas

O modelo não consulta o banco. Ele escolhe **qual ferramenta chamar** e com quais
argumentos; quem executa é o nosso código, com as mesmas regras de negócio e as mesmas
permissões de qualquer outro cliente da API.

Isso importa mais do que parece: se o agente gerasse SQL, toda a validação, o cache e o
controle de acesso que este projeto tem seriam contornados de uma vez.

### `consultar_estoque`

```json
{
  "name": "consultar_estoque",
  "description": "Consulta produtos do catálogo por nome, faixa de preço ou nível de estoque. Somente leitura.",
  "input_schema": {
    "type": "object",
    "properties": {
      "nome": {"type": "string", "description": "Busca parcial no nome do produto"},
      "preco_min": {"type": "number", "minimum": 0},
      "preco_max": {"type": "number", "minimum": 0},
      "estoque_max": {"type": "integer", "minimum": 0},
      "apenas_estoque_baixo": {
        "type": "boolean",
        "description": "Produtos no ou abaixo do limiar de reposição definido para cada produto"
      },
      "limite": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20}
    },
    "additionalProperties": false
  }
}
```

`additionalProperties: false` não é detalhe. Sem isso, um argumento alucinado
(`"desconto_maximo": 30`) passaria silenciosamente e viraria filtro ignorado — a resposta
sairia com cara de correta e escopo diferente do pedido.

O schema é praticamente o `FiltrosProduto` que a API REST já usa. É de propósito: a
ferramenta não é uma porta nova para o dado, é a porta existente descrita em JSON Schema.

### `criar_pedido`

```json
{
  "name": "criar_pedido",
  "description": "Cria um pedido de venda. AÇÃO DESTRUTIVA: reserva estoque e gera cobrança. Exige confirmação explícita do usuário antes da execução.",
  "input_schema": {
    "type": "object",
    "properties": {
      "cliente_id": {"type": "string", "format": "uuid"},
      "itens": {
        "type": "array",
        "minItems": 1,
        "maxItems": 100,
        "items": {
          "type": "object",
          "properties": {
            "produto_id": {"type": "string", "format": "uuid"},
            "quantidade": {"type": "integer", "minimum": 1}
          },
          "required": ["produto_id", "quantidade"],
          "additionalProperties": false
        }
      },
      "idempotency_key": {
        "type": "string",
        "description": "Chave única da intenção. Reenvio com a mesma chave não cria segundo pedido."
      }
    },
    "required": ["cliente_id", "itens", "idempotency_key"],
    "additionalProperties": false
  }
}
```

Três decisões embutidas aqui:

**A descrição declara que a ação é destrutiva.** A descrição não é documentação para
humano: é o que o modelo lê para decidir. Ela precisa dizer o que a chamada causa no mundo.

**`idempotency_key` é obrigatória.** Agente repete chamada — por retry da aplicação, por
timeout, ou porque reinterpretou a conversa. É o mesmo problema que resolvi no worker de
estoque com `movimento_estoque.referencia` (ADR 0008), e a solução é a mesma: a segunda
chamada com a mesma chave devolve o pedido existente em vez de criar outro.

**`produto_id` é UUID, não nome.** Se a ferramenta aceitasse `"cabo HDMI"`, o modelo
resolveria o nome sozinho e poderia acertar o produto errado. Ele precisa chamar
`consultar_estoque` antes e usar o id que voltou. O acoplamento é intencional: força o
agente a passar por uma leitura verificável antes de escrever.

---

## 2. MCP e o encaixe nos microsserviços da Parte 1

O MCP (Model Context Protocol) padroniza como um agente descobre e chama ferramentas. Sem
ele, cada integração vira código sob medida para um provedor; com ele, o ERP publica um
catálogo de ferramentas e qualquer cliente compatível consome.

Na arquitetura da Parte 1, o servidor MCP entra **como mais um consumidor do API Gateway,
não como um serviço com acesso privilegiado**:

```
Agente (Claude Desktop, IDE, chatbot interno)
        │  protocolo MCP
        ▼
Servidor MCP do ERP  ──── traduz tool call em chamada HTTP
        │  HTTP + JWT
        ▼
API Gateway (Kong)   ──── auth, rate limit, log, tracing
        │
        ├── Produtos/Estoque   (este serviço)
        ├── Pedidos
        ├── Financeiro
        └── Clientes
```

Por que atrás do gateway e não conversando direto com os bancos:

- O gateway já resolve autenticação, rate limiting e log de forma centralizada. Um servidor
  MCP com conexão direta reimplementaria os três, provavelmente pior.
- O agente herda **exatamente** as permissões do token que carrega. Não existe "usuário
  robô com acesso total": se o vendedor não pode ver margem de lucro, o agente dele
  também não pode.
- O tráfego do agente aparece na mesma observabilidade do resto. Investigar um incidente
  causado por agente vira o mesmo trabalho de investigar qualquer cliente.

Um servidor MCP por bounded context, e não um monolito de ferramentas: quem publica
`consultar_estoque` é o serviço dono do estoque. O catálogo de ferramentas segue a mesma
divisão dos serviços, senão vira um acoplamento novo justamente onde a arquitetura tentou
desacoplar.

---

## 3. Guardrails

### Confirmação para ação destrutiva

Ferramentas ficam em duas classes, e a separação é estrutural:

| Classe | Exemplos | Execução |
|---|---|---|
| Leitura | `consultar_estoque`, `consultar_alertas` | direta |
| Escrita | `criar_pedido`, `ajustar_estoque`, `cancelar_pedido` | exige confirmação |

O fluxo de escrita nunca executa na primeira chamada. Ele devolve um **preview**: o que
será feito, com valores resolvidos ("3 unidades de Cabo HDMI 2m, R$ 119,70, cliente
Comércio Silva Ltda"), mais um token de confirmação com validade curta. A execução só
acontece com esse token.

Isso resolve o problema real, que não é o modelo ser malicioso — é ele ser confiante. Uma
frase ambígua do usuário ("cancela isso aí") vira uma ação irreversível sem que ninguém
tenha visto o que "isso" era.

O preview é também onde a alucinação morre: se o modelo inventou um produto, o usuário lê
o nome errado antes de confirmar.

### Lidar com alucinação

**Nunca confiar em id vindo do modelo.** Todo id é validado contra o banco antes do uso.
Id inexistente é erro explícito, não busca aproximada — "encontrei algo parecido" é como se
vende o produto errado.

**Ferramenta nunca responde vazio quando falhou.** É o mesmo princípio da Parte 2 e do
parser da Q8: se o serviço de Financeiro está fora, a ferramenta devolve
`{"status": "indisponivel"}`, nunca `{"debitos": []}`. Um modelo que recebe lista vazia
conclui e afirma que o cliente está limpo.

**Resposta ancorada em dado retornado.** O resultado da ferramenta traz os valores que o
modelo deve citar. Quando ele responde um número que não está no retorno, isso é
detectável — e num fluxo com valor financeiro, vale rodar essa verificação.

**Limite de passos.** Um teto de chamadas por conversa evita o laço em que o agente
reformula a mesma consulta indefinidamente, queimando custo e latência.

### Escopo

O token do agente carrega as permissões do usuário que iniciou a conversa. Além disso, a
lista de ferramentas é uma allow-list explícita por perfil: o agente de suporte não recebe
`criar_pedido` no catálogo — não é que ele seja recusado ao chamar, é que a ferramenta não
existe para ele. Ferramenta que não está no catálogo não é chamada nem por engano.

---

## 4. Custo, latência e observabilidade

### Custo

O custo é dominado pelo tamanho do contexto, e o contexto cresce sozinho: a cada chamada
de ferramenta, o resultado inteiro volta para o modelo.

- **Limitar o retorno das ferramentas.** `consultar_estoque` tem `limite` com teto de 50 e
  devolve `total` separado dos itens. "Quantos produtos estão em falta" não precisa
  carregar 4.000 registros no contexto para responder um número — é o mesmo raciocínio que
  me fez separar a intenção `contar` da `listar` no parser da Q8.
- **Cache de resposta de ferramenta.** Consulta de catálogo dentro da mesma conversa não
  precisa ir ao banco duas vezes. O Redis já está no stack, e a política de invalidação do
  ADR 0007 vale igual aqui: leitura de catálogo cacheia, consulta que depende de estoque
  não.
- **Prompt caching** do provedor para o bloco estável (definições de ferramentas e
  instruções), que é grande e não muda entre turnos.
- **Roteamento por modelo.** Classificar intenção é tarefa de modelo pequeno; redigir a
  resposta final para o cliente pode justificar um maior. Usar o modelo mais caro para tudo
  é a forma mais silenciosa de queimar orçamento.

### Latência

Um turno de agente é lento por natureza: são várias idas ao provedor, mais as chamadas de
ferramenta no meio.

- **Chamadas de ferramenta independentes em paralelo.** Já está resolvido neste repositório:
  é o `asyncio.gather` com timeout individual e orçamento total do ADR 0009. Um agente que
  precisa de cliente, crédito e prazo faz as três de uma vez.
- **Timeout por ferramenta, com degradação.** O agente recebe o resultado parcial marcado
  como parcial e decide se responde assim ou pede para tentar de novo. Melhor que travar o
  turno esperando a fonte lenta.
- **Streaming** da resposta final, para o tempo até o primeiro token ser baixo mesmo quando
  o turno inteiro demora.

### Observabilidade

Vale o que já vale para o resto do ERP (três pilares, tracing com OpenTelemetry), mais o
que é específico de LLM:

- **Log de prompt e resposta, com trace id**, ligado ao mesmo trace das chamadas HTTP que a
  ferramenta disparou. Sem isso, "o agente respondeu errado ontem" é irreprodutível.
  Cuidado com dado pessoal no log: prompt de ERP contém nome e documento de cliente, então
  vale mascarar e ter retenção curta.
- **Métricas por turno:** tokens de entrada e saída, custo estimado, número de chamadas de
  ferramenta, latência total, e taxa de turnos que bateram o limite de passos.
- **Taxa de recusa e de confirmação negada.** Se muitos previews estão sendo recusados pelo
  usuário, o agente está entendendo errado com frequência, e isso é sintoma antes de virar
  incidente.
- **Alerta de custo por janela**, não só total mensal. Um laço de ferramenta pode gastar em
  uma hora o orçamento do mês.

### Fallback quando o provedor cai

Aqui a resposta é menos sobre o LLM e mais sobre o produto: **o ERP não pode depender do
agente para funcionar**. O agente é uma interface a mais sobre uma API que já existe e é
usável sem ele.

Em ordem: retry com backoff para erro transitório; provedor secundário para o caso de
indisponibilidade prolongada, aceitando que a qualidade muda; e, se nada responder, a
degradação honesta — dizer que o assistente está indisponível e oferecer o caminho normal
da aplicação. O que não pode acontecer é o agente inventar resposta porque a ferramenta não
respondeu, que é exatamente o cenário que os guardrails da seção 3 previnem.

---

## 5. O que eu faria diferente com mais tempo

O parser da Q8 é por regras, e regra tem teto: ele entende as formas que eu previ e recusa
o resto. Recusar é o comportamento certo, mas a cobertura é limitada e cada frase nova
exige código.

O passo seguinte natural seria classificação de intenção com um modelo local pequeno
(embeddings e similaridade contra exemplos rotulados, sem provedor externo, o que respeita
a restrição do enunciado), mantendo a extração de valores determinística. O modelo diria
"isto é uma pergunta sobre nível de estoque"; a regra continuaria extraindo o número.

Assim eu ganharia tolerância a variação linguística sem abrir mão da parte que não pode
errar: o número que vai para o filtro. É a divisão que eu defenderia em qualquer sistema
com LLM — modelo para interpretar, código determinístico para executar.
