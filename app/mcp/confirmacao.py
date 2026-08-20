"""Confirmação em duas etapas para ações destrutivas.

Implementa em código o guardrail que descrevi na Q9 do README: ferramenta de
escrita **não executa na primeira chamada**. Ela devolve um preview com valores resolvidos
e um token de validade curta; a execução só acontece com esse token.

O problema que isso resolve não é modelo malicioso, é modelo confiante. Uma frase ambígua
do usuário vira ação irreversível sem que ninguém tenha visto o que ela significava. O
preview é também onde a alucinação morre: se o modelo inventou o produto, quem lê o preview
vê o nome errado antes de confirmar.

Guardo os pendentes em memória. É honesto sobre o custo: reiniciar o servidor MCP descarta
confirmações pendentes, e o usuário precisa pedir de novo. Para um token de dois minutos
isso é aceitável, e evita acoplar o servidor ao Redis só por causa disto. Num sistema com
várias instâncias, iria para o Redis que já está no stack.
"""

import secrets
import time
from dataclasses import dataclass, field
from typing import Any

VALIDADE_SEGUNDOS = 120


@dataclass
class Pendente:
    token: str
    ferramenta: str
    argumentos: dict[str, Any]
    resumo: str
    criado_em: float


@dataclass
class RegistroConfirmacoes:
    _pendentes: dict[str, Pendente] = field(default_factory=dict)

    def registrar(self, ferramenta: str, argumentos: dict[str, Any], resumo: str) -> Pendente:
        self._expirar()
        # `token_urlsafe` e não um contador: token adivinhável permitiria confirmar uma
        # ação que o usuário nunca viu.
        pendente = Pendente(
            token=secrets.token_urlsafe(12),
            ferramenta=ferramenta,
            argumentos=argumentos,
            resumo=resumo,
            criado_em=time.monotonic(),
        )
        self._pendentes[pendente.token] = pendente
        return pendente

    def resgatar(self, token: str) -> Pendente | None:
        """Consome o token. Uma confirmação vale por uma execução, e só.

        Sem o consumo, o mesmo token repetido criaria duas movimentações de estoque -- o
        mesmo problema de idempotência que resolvi no worker (ADR 0008).
        """
        self._expirar()
        return self._pendentes.pop(token, None)

    def _expirar(self) -> None:
        agora = time.monotonic()
        vencidos = [
            token for token, p in self._pendentes.items() if agora - p.criado_em > VALIDADE_SEGUNDOS
        ]
        for token in vencidos:
            del self._pendentes[token]

    def __len__(self) -> int:
        self._expirar()
        return len(self._pendentes)
