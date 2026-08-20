"""Testes do servidor MCP.

Testo as ferramentas chamando função, com um ERP dublado. É o que a separação entre
`ferramentas.py` (o quê) e `servidor.py` (transporte) permite: não preciso levantar
processo nem falar stdio para verificar o comportamento que importa.

O foco está nos guardrails, porque são eles que impedem um agente confiante de causar
estrago — não o caminho feliz.
"""

import json
from typing import Any

import pytest

from app.mcp.cliente_erp import ErroERP
from app.mcp.confirmacao import RegistroConfirmacoes
from app.mcp.ferramentas import Executor
from app.mcp.servidor import mcp


class ERPFalso:
    def __init__(self, quebrado: bool = False) -> None:
        self.quebrado = quebrado
        self.ajustes: list[tuple[str, int, str]] = []
        self.produto = {
            "id": "11111111-1111-1111-1111-111111111111",
            "nome": "Cabo HDMI 2m",
            "quantidade_estoque": 10,
            "estoque_minimo": 3,
            "preco": "39.90",
        }

    def _checa(self) -> None:
        if self.quebrado:
            raise ErroERP("HTTP 503: api fora do ar")

    async def listar_produtos(self, filtros: dict[str, Any]) -> dict[str, Any]:
        self._checa()
        return {"total": 1, "itens": [self.produto], "pagina": 1, "tamanho": 20, "paginas": 1}

    async def buscar_produto(self, produto_id: str) -> dict[str, Any]:
        self._checa()
        if produto_id != self.produto["id"]:
            raise ErroERP(f"HTTP 404: produto {produto_id} nao encontrado")
        return self.produto

    async def listar_alertas(self, apenas_abertos: bool = True) -> list[dict[str, Any]]:
        self._checa()
        return []

    async def perguntar(self, pergunta: str) -> dict[str, Any]:
        self._checa()
        return {"pergunta": pergunta, "entendida": True, "total": 1}

    async def ajustar_estoque(self, produto_id: str, delta: int, motivo: str) -> dict[str, Any]:
        self._checa()
        self.ajustes.append((produto_id, delta, motivo))
        return {"job_id": "job-fake-1", "produto_id": produto_id, "situacao": "enfileirado"}


@pytest.fixture
def erp() -> ERPFalso:
    return ERPFalso()


@pytest.fixture
def executor(erp) -> Executor:
    return Executor(erp)


def json_de(texto: str) -> dict[str, Any]:
    return json.loads(texto)


class TestFerramentasPublicadas:
    async def test_publica_as_cinco_ferramentas(self):
        nomes = {f.name for f in await mcp.list_tools()}

        assert nomes == {
            "consultar_estoque",
            "consultar_alertas",
            "perguntar_sobre_catalogo",
            "preparar_ajuste_estoque",
            "confirmar_ajuste_estoque",
        }

    async def test_ferramentas_destrutivas_se_anunciam(self):
        """A descrição é o que o modelo lê para decidir, não documentação para humano."""
        destrutivas = {"preparar_ajuste_estoque", "confirmar_ajuste_estoque"}

        for ferramenta in await mcp.list_tools():
            if ferramenta.name in destrutivas:
                assert "DESTRUTIVA" in ferramenta.description

    async def test_produto_id_e_uuid_e_nao_nome(self):
        """Aceitar nome faria o modelo resolver sozinho e acertar o produto errado."""
        preparar = next(f for f in await mcp.list_tools() if f.name == "preparar_ajuste_estoque")
        descricao = preparar.input_schema["properties"]["produto_id"]["description"]

        assert "UUID" in descricao
        assert "nao invente" in descricao


class TestArgumentoDesconhecido:
    """O SDK aceita e **descarta em silêncio** argumento fora do schema, devolvendo sucesso.

    Isso é pior do que o que eu tinha escrito no documento de design: eu supunha que
    `additionalProperties: false` no schema resolvia. Não resolve — o schema é declaração
    de intenção para o modelo, e quem protege é o servidor. Daí a subclasse `ServidorERP`.
    """

    async def test_argumento_alucinado_e_recusado_sem_executar(self):
        resultado = await mcp.call_tool(
            "consultar_estoque", {"nome": "cabo", "desconto_maximo": 30}
        )

        assert resultado.is_error is True
        corpo = json_de(resultado.content[0].text)
        assert "desconto_maximo" in corpo["erro"]
        assert "NAO foi executada" in corpo["observacao"]

    async def test_a_recusa_diz_quais_argumentos_sao_aceitos(self):
        """Recusar sem dizer o que serve deixa o modelo tentando às cegas."""
        resultado = await mcp.call_tool("consultar_alertas", {"inventado": True})

        corpo = json_de(resultado.content[0].text)
        assert corpo["aceitos"] == ["apenas_abertos"]


class TestLeitura:
    async def test_consultar_estoque_separa_total_dos_itens(self, executor):
        """Contagem não deve exigir carregar o catálogo inteiro no contexto."""
        resposta = json_de(await executor.executar("consultar_estoque", {}))

        assert resposta["total"] == 1
        assert len(resposta["itens"]) == 1

    async def test_limite_tem_teto(self, executor, erp):
        """Teto no retorno é controle de custo: contexto grande é o que sai caro."""
        capturado: dict[str, Any] = {}

        async def espiao(filtros):
            capturado.update(filtros)
            return {"total": 0, "itens": []}

        erp.listar_produtos = espiao
        await executor.executar("consultar_estoque", {"limite": 5000})

        assert capturado["tamanho"] == 50

    async def test_pergunta_em_linguagem_natural_passa_pelo_parser_do_erp(self, executor):
        resposta = json_de(
            await executor.executar(
                "perguntar_sobre_catalogo", {"pergunta": "produtos com estoque abaixo de 10"}
            )
        )

        assert resposta["entendida"] is True


class TestFalhaNaoViraDadoVazio:
    async def test_erro_do_erp_e_marcado_como_indisponivel(self):
        """O guardrail mais importante.

        Se a ferramenta devolvesse `{"alertas": []}` com a API fora, o modelo afirmaria
        que não há alerta nenhum. Falha tem que ser reconhecível como falha.
        """
        executor = Executor(ERPFalso(quebrado=True))

        resposta = json_de(await executor.executar("consultar_alertas", {}))

        assert resposta["status"] == "indisponivel"
        assert "alertas" not in resposta
        assert "NAO significa que nao ha dados" in resposta["observacao"]

    async def test_falha_nunca_vira_excecao_no_transporte(self):
        """Exceção no transporte perde a explicação, e o modelo fica sem saber o que fazer."""
        executor = Executor(ERPFalso(quebrado=True))

        for nome in ("consultar_estoque", "consultar_alertas", "perguntar_sobre_catalogo"):
            texto = await executor.executar(nome, {"pergunta": "produtos em falta"})
            assert json_de(texto)["status"] == "indisponivel"


class TestConfirmacaoDeAcaoDestrutiva:
    async def test_preparar_nao_executa(self, executor, erp):
        """Primeira chamada não pode alterar nada."""
        resposta = json_de(
            await executor.executar(
                "preparar_ajuste_estoque",
                {"produto_id": erp.produto["id"], "delta": -4, "motivo": "venda"},
            )
        )

        assert resposta["status"] == "aguardando_confirmacao"
        assert erp.ajustes == []

    async def test_preview_traz_valores_resolvidos(self, executor, erp):
        """É onde a alucinação morre: o usuário lê o nome errado antes de confirmar."""
        resposta = json_de(
            await executor.executar(
                "preparar_ajuste_estoque",
                {"produto_id": erp.produto["id"], "delta": -4, "motivo": "venda"},
            )
        )

        assert "Cabo HDMI 2m" in resposta["preview"]
        assert resposta["saldo_atual"] == 10
        assert resposta["saldo_apos"] == 6

    async def test_confirmar_executa_uma_vez(self, executor, erp):
        preparo = json_de(
            await executor.executar(
                "preparar_ajuste_estoque",
                {"produto_id": erp.produto["id"], "delta": -4, "motivo": "venda"},
            )
        )

        confirmacao = json_de(
            await executor.executar(
                "confirmar_ajuste_estoque", {"token_confirmacao": preparo["token_confirmacao"]}
            )
        )

        assert confirmacao["status"] == "enfileirado"
        assert erp.ajustes == [(erp.produto["id"], -4, "venda")]

    async def test_token_nao_pode_ser_reutilizado(self, executor, erp):
        """Token reutilizável criaria duas movimentações: mesma armadilha do ADR 0008."""
        preparo = json_de(
            await executor.executar(
                "preparar_ajuste_estoque",
                {"produto_id": erp.produto["id"], "delta": -4, "motivo": "venda"},
            )
        )
        token = preparo["token_confirmacao"]

        await executor.executar("confirmar_ajuste_estoque", {"token_confirmacao": token})
        segunda = json_de(
            await executor.executar("confirmar_ajuste_estoque", {"token_confirmacao": token})
        )

        assert segunda["status"] == "erro"
        assert len(erp.ajustes) == 1

    async def test_token_inventado_e_recusado(self, executor, erp):
        """O modelo não pode confirmar uma ação que nunca preparou."""
        resposta = json_de(
            await executor.executar(
                "confirmar_ajuste_estoque", {"token_confirmacao": "token-inventado"}
            )
        )

        assert resposta["status"] == "erro"
        assert erp.ajustes == []

    async def test_baixa_maior_que_o_saldo_e_recusada_no_preview(self, executor, erp):
        """Recusar antes de preparar evita levar o usuário a confirmar algo que vai falhar."""
        resposta = json_de(
            await executor.executar(
                "preparar_ajuste_estoque",
                {"produto_id": erp.produto["id"], "delta": -50, "motivo": "venda"},
            )
        )

        assert resposta["status"] == "recusado"
        assert "saldo insuficiente" in resposta["erro"]

    async def test_produto_inexistente_nao_vira_busca_aproximada(self, executor):
        """ "Encontrei algo parecido" é como se movimenta o produto errado."""
        resposta = json_de(
            await executor.executar(
                "preparar_ajuste_estoque",
                {
                    "produto_id": "99999999-9999-9999-9999-999999999999",
                    "delta": -1,
                    "motivo": "venda",
                },
            )
        )

        assert resposta["status"] == "indisponivel"
        assert "404" in resposta["erro"]

    async def test_delta_zero_e_recusado(self, executor, erp):
        resposta = json_de(
            await executor.executar(
                "preparar_ajuste_estoque",
                {"produto_id": erp.produto["id"], "delta": 0, "motivo": "nada"},
            )
        )

        assert resposta["status"] == "erro"


class TestRegistroDeConfirmacoes:
    def test_token_expirado_nao_resgata(self):
        registro = RegistroConfirmacoes()
        pendente = registro.registrar("x", {}, "resumo")

        # Empurra o registro para além da validade sem esperar de verdade.
        registro._pendentes[pendente.token].criado_em -= 10_000

        assert registro.resgatar(pendente.token) is None
        assert len(registro) == 0

    def test_tokens_sao_distintos_e_nao_sequenciais(self):
        """Token adivinhável permitiria confirmar uma ação que o usuário nunca viu."""
        registro = RegistroConfirmacoes()
        tokens = {registro.registrar("x", {}, "r").token for _ in range(50)}

        assert len(tokens) == 50
        assert all(len(t) > 10 for t in tokens)
