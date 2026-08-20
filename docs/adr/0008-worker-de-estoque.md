# ADR 0008 — Worker de estoque: movimentação e alerta

**Data:** 2026-08-20 · **Status:** aceito

## Contexto

A prova pede um worker de fila executando uma tarefa real do domínio. O `arq` já foi
escolhido no [ADR 0003](0003-fila-com-arq.md), que segue sem validação até existir tarefa
rodando. Falta decidir o que ele faz e como.

Há também uma dívida do [ADR 0007](0007-estrategia-de-cache.md): a asserção de que o worker
invalida cache sem passar por router está provada apenas com dublê, porque não existe
nenhum escritor de estoque de verdade no sistema.

## Decisão

### Duas tarefas

**`ajustar_estoque(produto_id, delta, motivo)`** movimenta o estoque, invalida o cache do
produto e encadeia a verificação. É ela que fecha a dívida do ADR 0007: passa a existir um
escritor real fora do caminho HTTP.

**`verificar_estoque_baixo(produto_id | None)`** compara `quantidade_estoque` com o
`estoque_minimo` de cada produto e abre ou resolve alerta. Sem argumento, varre o catálogo.

Uma tarefa só cumpriria o enunciado, mas deixaria o projeto afirmando no ADR 0007 algo que
nenhum código exercita.

### O alerta vai para uma tabela, não para o log

Num ERP, alerta precisa de histórico e de alguém que consulte depois. Log estruturado some
no rotacionamento e não responde "há quanto tempo este item está em falta".

O campo que decide o desenho é o `status`, com um **índice único parcial**: no máximo um
alerta `aberto` por produto. A idempotência fica garantida pelo banco, não por código —
a varredura pode rodar a cada minuto por uma semana sem gerar alerta duplicado. É também o
que torna a tarefa segura para retry, requisito de qualquer fila.

Quando o estoque volta acima do mínimo o alerta é **resolvido**, não apagado. Apagar
destruiria o histórico, que é justamente o que a tabela existe para guardar.

### Cadência: evento e varredura

Os dois, pelo mesmo raciocínio do TTL versus invalidação explícita do ADR 0007.

Por evento, a verificação roda logo após cada movimentação; é o que importa para uma
decisão de compra. Por varredura (cron do `arq`), pega o que o caminho de evento perdeu:
worker fora do ar, dado alterado direto no banco, ou `estoque_minimo` editado sem o estoque
mudar — este último não dispara evento de movimentação nenhum e passaria despercebido.

Evento é o mecanismo, varredura é a rede de segurança.

### Movimentação é `UPDATE` atômico, não ler-somar-gravar

`UPDATE produto SET quantidade_estoque = quantidade_estoque + :delta`.

Ler o saldo, somar em Python e gravar perde atualização silenciosamente quando dois
workers rodam concorrentes: os dois leem 10, os dois gravam 9, e duas baixas viraram uma.
O `UPDATE` atômico resolve sem lock, porque quem resolve o conflito é o próprio Postgres.

A `CheckConstraint` de estoque não negativo, que já existe na tabela desde a primeira
migration, impede que uma baixa concorrente leve o saldo abaixo de zero: a transação falha
e o service traduz para um erro de domínio.

**Limite que assumo:** isto resolve movimentação de estoque. Não é a solução de oversell na
reserva de pedido, que precisa de lock distribuído e pertence ao módulo de Pedidos.

### O endpoint enfileira em vez de executar

`POST /produtos/{id}/estoque` devolve 202 e o id do job.

Vale ser explícito sobre quando isso é adequado: movimentação que tolera consistência
eventual (reposição, ajuste de inventário, devolução). O caminho de reserva de pedido, que
precisa de resposta síncrona sob lock, não passaria por aqui.

### Mesma imagem para API e worker

O serviço `worker` no Compose usa a imagem da API com comando diferente. Worker e API
compartilham models, services e o módulo de cache; imagens separadas dariam duas versões
do mesmo código convivendo, e a divergência apareceria como bug de dado.

## O que descartei

**Alerta por e-mail ou webhook.** Dependência externa que a prova não pede e que eu não
teria como validar honestamente.

**`BackgroundTasks`.** Já descartado no ADR 0003, e aqui o argumento fica mais concreto:
alerta de estoque perdido porque o processo web reiniciou é exatamente o que não pode
sumir num ERP.

**Apagar o alerta ao resolver.** Simplifica o índice único e destrói o histórico. Trocar
auditoria por conveniência num sistema financeiro é mau negócio.

**Enum nativo do Postgres para `status`.** Bonito, mas `ALTER TYPE` em migration é
desconfortável. `String` com CheckConstraint dá a mesma garantia e migra sem cerimônia.

## Consequências

Ganho: uma tarefa de domínio real, idempotente por construção, com o caminho
worker → cache exercitado de verdade.

Pago:

- Mais uma tabela e mais uma migration para manter.
- A varredura por cron custa uma query periódica no catálogo inteiro. Com catálogo grande
  isso passaria a doer e viraria varredura paginada ou incremental por `atualizado_em`.
- O endpoint 202 transfere para o cliente a responsabilidade de descobrir o resultado.
  Aceitável para ajuste de inventário, e é por isso que deixei registrado acima que a
  reserva de pedido não deve usar este caminho.
- Dois processos passam a escrever na mesma tabela `produto`. O `UPDATE` atômico cobre
  perda de atualização, mas não substitui o lock quando a decisão de negócio depende de
  ler o saldo antes de decidir.

## Correção que fiz durante a implementação: idempotência da movimentação

Configurei `max_tries = 3` e só depois percebi que `ajustar_estoque` **não era
idempotente**. O alerta é seguro para repetir por causa do índice único; a movimentação
não era: uma reentrega aplicaria o `delta` de novo.

Isso não é hipótese, é como fila funciona. A entrega é *pelo menos uma vez*: se o worker
commita a baixa e morre antes de confirmar o job, o arq reentrega.

A correção foi a tabela `movimento_estoque` com `referencia` única, preenchida com o
`job_id`. Reentrega vira no-op. Ela resolve também uma lacuna de domínio que eu teria
deixado passar: ERP sem histórico de movimentação não responde "por que o saldo deste item
caiu 40 unidades ontem", que é a primeira pergunta de qualquer auditoria de inventário.

## Como validei

As sete asserções viraram teste ou verificação com o Compose de pé.

```
$ uv run pytest -q
47 passed in 0.42s
```

Os quatro containers sobem saudáveis:

```
SERVICE    STATUS
api        Up 22 seconds (healthy)
postgres   Up 24 hours (healthy)
redis      Up 24 hours (healthy)
worker     Up 22 seconds (healthy)
```

O ciclo completo pela API, com o worker processando de verdade:

```
1) detalhe em cache antes:  1
   saldo antes: 8
2) POST /produtos/{id}/estoque {"delta":100} -> 202, job eb75bf71
3) detalhe em cache depois:  0        <- invalidado pelo worker, sem passar por router
4) worker: {'saldo': 108, 'alerta': 'resolvido'}
5) alerta: status=resolvido  qtd_no_alerta=8  resolvido_em=2026-08-20T14:28:30+0000
```

O `qtd_no_alerta=8` preservado é o ponto do desenho: o alerta guarda o estado de quando
foi aberto, não o de agora.

A idempotência da varredura aparece nos números do cron em execuções seguidas:

```
14:27:50  cron:verificar_estoque_baixo ● {'abertos': 1, 'resolvidos': 0, 'ja_abertos': 3}
14:28:00  cron:verificar_estoque_baixo ● {'abertos': 0, 'resolvidos': 0, 'ja_abertos': 4}
```

### O bug que os testes de unidade não pegariam

Na primeira execução real, a tarefa falhou com:

```
InvalidColumnReferenceError: there is no unique or exclusion constraint
matching the ON CONFLICT specification
```

Eu havia passado o predicado do `ON CONFLICT` como expressão do ORM
(`AlertaEstoque.status == StatusAlerta.ABERTO`). Parece equivalente ao predicado do índice
e não é: renderiza como bind parameter (`status = $1`), e o Postgres só casa `ON CONFLICT`
com índice parcial quando consegue provar que os predicados são iguais — o que ele não faz
com um valor que só existe em tempo de execução. Passou a ser `text("status = 'aberto'")`.

O dublê de repository passou tranquilo nos testes, porque ele reimplementa o invariante em
Python: validava a minha intenção, não o meu SQL. Essa é a fronteira honesta do teste com
dublê, e por isso adicionei `app/tests/test_integracao_alerta.py`, que roda contra Postgres
de verdade e pula sozinho quando não há banco acessível.

E houve um efeito colateral que eu não teria conseguido encenar: como a tarefa falhou
*depois* de commitar a baixa, o arq reentregou o job. O saldo continuou correto, porque a
chave de idempotência que eu tinha acabado de adicionar fez a reentrega virar no-op. A
correção da seção anterior se provou em condição real de falha, não em teste.
