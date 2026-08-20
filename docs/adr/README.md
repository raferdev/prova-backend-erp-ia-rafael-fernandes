# Registro de decisões de arquitetura (ADR)

Cada arquivo aqui é uma decisão que tomei durante a prova, com o contexto que eu tinha
no momento, as alternativas que descartei e como validei o resultado.

Escrevo ADR porque decisão sem registro vira folclore: seis meses depois ninguém lembra
se `arq` foi escolha ou acidente. O formato também me obriga a declarar o que estou
*pagando* por cada escolha, não só o que estou ganhando.

| # | Decisão | Data | Status |
|---|---|---|---|
| [0001](0001-estrutura-em-camadas.md) | Organizar por camada, não por domínio | 2026-08-19 | aceito |
| [0002](0002-persistencia-sqlalchemy-async.md) | SQLAlchemy 2.0 async + Alembic | 2026-08-19 | aceito |
| [0003](0003-fila-com-arq.md) | `arq` como fila de background | 2026-08-19 | aceito |
| [0004](0004-liveness-separado-de-readiness.md) | Separar liveness de readiness | 2026-08-19 | aceito |
| [0005](0005-test-client-async.md) | Client de teste async desde o início | 2026-08-19 | aceito, substitui decisão anterior |
| [0006](0006-convencoes-de-migration.md) | Fixar convenções antes da 1ª migration | 2026-08-19 | aceito |
| [0007](0007-estrategia-de-cache.md) | Cache do catálogo e invalidação por versão | 2026-08-20 | aceito, implementado |

## Formato

Uso uma versão enxuta do padrão de Michael Nygard: contexto, opções, decisão,
consequências. Acrescentei uma seção **Como validei**, com a saída real do comando.
Sem ela um ADR é só opinião bem formatada.
