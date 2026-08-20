"""Cliente HTTP do ERP usado pelo servidor MCP.

A decisão que este arquivo materializa está no `docs/parte-5-agente-ia.md`: o servidor MCP
**fala com a API por HTTP e JWT**, e não com o banco direto.

Acessar o banco daqui seria mais simples e mais rápido, e erraria em três frentes ao mesmo
tempo: contornaria a validação e o cache que a API implementa; daria ao agente um acesso
mais amplo que o do usuário que iniciou a conversa; e tiraria o tráfego do agente da mesma
observabilidade do resto do sistema. O agente herda exatamente as permissões do token que
carrega, e é isso que torna "usuário robô com acesso total" impossível por construção.
"""

import os
from typing import Any

import httpx

BASE_URL = os.getenv("ERP_API_URL", "http://localhost:8000")
USUARIO = os.getenv("ERP_USUARIO", "admin@erp.local")
SENHA = os.getenv("ERP_SENHA", "admin123")
TIMEOUT = float(os.getenv("ERP_TIMEOUT", "10"))


class ErroERP(Exception):
    """Falha ao falar com a API. Vira mensagem explícita para o agente, nunca dado vazio."""


class ClienteERP:
    """Wrapper fino sobre a API REST, com autenticação e renovação de token."""

    def __init__(self, base_url: str = BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self._token: str | None = None

    async def _autenticar(self, http: httpx.AsyncClient) -> str:
        resposta = await http.post("/auth/token", data={"username": USUARIO, "password": SENHA})
        if resposta.status_code != 200:
            raise ErroERP(f"falha ao autenticar no ERP (HTTP {resposta.status_code})")
        return resposta.json()["access_token"]

    async def _requisitar(
        self,
        metodo: str,
        caminho: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=TIMEOUT) as http:
            if self._token is None:
                self._token = await self._autenticar(http)

            cabecalhos = {"Authorization": f"Bearer {self._token}"}
            resposta = await http.request(
                metodo, caminho, params=params, json=json, headers=cabecalhos
            )

            # Token expirado (o padrão é 60 minutos) é o caso comum numa conversa longa.
            # Renovo uma vez e repito; se falhar de novo, é problema de credencial.
            if resposta.status_code == 401:
                self._token = await self._autenticar(http)
                cabecalhos = {"Authorization": f"Bearer {self._token}"}
                resposta = await http.request(
                    metodo, caminho, params=params, json=json, headers=cabecalhos
                )

            if resposta.status_code >= 400:
                detalhe = self._detalhe(resposta)
                raise ErroERP(f"HTTP {resposta.status_code}: {detalhe}")

            return None if resposta.status_code == 204 else resposta.json()

    @staticmethod
    def _detalhe(resposta: httpx.Response) -> str:
        try:
            return str(resposta.json().get("detail", resposta.text))[:400]
        except ValueError:
            return resposta.text[:400]

    async def listar_produtos(self, filtros: dict[str, Any]) -> dict[str, Any]:
        limpos = {k: v for k, v in filtros.items() if v is not None}
        return await self._requisitar("GET", "/produtos", params=limpos)

    async def buscar_produto(self, produto_id: str) -> dict[str, Any]:
        return await self._requisitar("GET", f"/produtos/{produto_id}")

    async def listar_alertas(self, apenas_abertos: bool = True) -> list[dict[str, Any]]:
        return await self._requisitar("GET", "/alertas", params={"apenas_abertos": apenas_abertos})

    async def perguntar(self, pergunta: str) -> dict[str, Any]:
        return await self._requisitar("POST", "/consultas/produtos", json={"pergunta": pergunta})

    async def ajustar_estoque(self, produto_id: str, delta: int, motivo: str) -> dict[str, Any]:
        return await self._requisitar(
            "POST", f"/produtos/{produto_id}/estoque", json={"delta": delta, "motivo": motivo}
        )
