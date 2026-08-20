"""Testes do parser determinístico (Parte 5, Q8).

Metade dos testes é sobre o que o parser entende. A outra metade, mais importante, é sobre
o que ele **recusa** entender: um parser que chuta produz número errado com cara de número
certo, e é isso que ele não pode fazer.
"""

from decimal import Decimal

import pytest

from app.services.parser_consulta import interpretar


class TestEntende:
    def test_estoque_abaixo_de_um_numero(self):
        leitura = interpretar("produtos com estoque abaixo de 10")

        assert leitura.entendida is True
        assert leitura.intencao == "listar"
        assert leitura.filtros.estoque_max == 10
        assert leitura.filtros.preco_max is None

    def test_preco_acima_de_um_numero(self):
        leitura = interpretar("produtos com preço acima de 100")

        assert leitura.filtros.preco_min == Decimal("100")
        assert leitura.filtros.estoque_min is None

    def test_faixa_de_preco(self):
        leitura = interpretar("produtos entre 50 e 200 reais")

        assert leitura.filtros.preco_min == Decimal("50")
        assert leitura.filtros.preco_max == Decimal("200")

    def test_faixa_invertida_e_normalizada(self):
        """ "entre 200 e 50" é erro de digitação comum, e a intenção é óbvia."""
        leitura = interpretar("produtos entre 200 e 50 reais")

        assert leitura.filtros.preco_min == Decimal("50")
        assert leitura.filtros.preco_max == Decimal("200")

    @pytest.mark.parametrize(
        "pergunta",
        ["produtos com estoque baixo", "produtos em falta", "o que está acabando"],
    )
    def test_estoque_baixo_usa_o_limiar_de_cada_produto(self, pergunta):
        leitura = interpretar(pergunta)

        assert leitura.filtros.apenas_estoque_baixo is True
        assert leitura.filtros.estoque_max is None

    def test_contagem_muda_a_intencao(self):
        leitura = interpretar("quantos produtos estão em falta")

        assert leitura.intencao == "contar"
        assert leitura.filtros.apenas_estoque_baixo is True

    def test_busca_por_nome(self):
        leitura = interpretar("produtos com nome cabo")

        assert leitura.filtros.nome == "cabo"

    def test_inativos(self):
        assert interpretar("produtos inativos").filtros.ativo is False

    def test_ativos(self):
        assert interpretar("produtos ativos").filtros.ativo is True

    def test_acentos_e_maiusculas_nao_atrapalham(self):
        leitura = interpretar("PRODUTOS COM PREÇO ABAIXO DE 30")

        assert leitura.entendida is True
        assert leitura.filtros.preco_max == Decimal("30")

    def test_numero_por_extenso(self):
        leitura = interpretar("produtos com estoque abaixo de dez")

        assert leitura.filtros.estoque_max == 10

    def test_numero_no_formato_brasileiro(self):
        """`1.500,50` é mil e quinhentos, não um e meio.

        Ler isso como formato americano transformaria mil reais em um real, que num ERP
        é o erro que ninguém percebe até o fechamento.
        """
        leitura = interpretar("produtos com preço acima de 1.500,50")

        assert leitura.filtros.preco_min == Decimal("1500.50")

    def test_combina_filtros(self):
        leitura = interpretar("produtos ativos com nome cabo e estoque abaixo de 50")

        assert leitura.filtros.ativo is True
        assert leitura.filtros.nome == "cabo"
        assert leitura.filtros.estoque_max == 50

    def test_explicacao_e_devolvida_em_portugues(self):
        """A resposta precisa ser conferível por quem perguntou."""
        leitura = interpretar("produtos com estoque abaixo de 10")

        assert "Listar produtos" in leitura.explicacao
        assert "10" in leitura.explicacao


class TestRecusa:
    def test_numero_sem_campo_e_ambiguo(self):
        """O teste mais importante do arquivo.

        "abaixo de 10" — dez de quê? Chutar estoque quando a pessoa queria preço devolve
        um número errado com aparência de certo.
        """
        leitura = interpretar("produtos abaixo de 10")

        assert leitura.entendida is False
        assert leitura.ambiguidade is not None
        assert "estoque ou preço" in leitura.ambiguidade
        assert len(leitura.sugestoes) == 2

    def test_pergunta_fora_do_dominio(self):
        leitura = interpretar("qual a previsão do tempo amanhã")

        assert leitura.entendida is False
        assert leitura.filtros is None
        assert leitura.sugestoes

    def test_pergunta_vazia(self):
        assert interpretar("   ").entendida is False

    def test_numero_sem_operador_nao_vira_filtro(self):
        """ "produtos 10" não diz o que fazer com o 10."""
        leitura = interpretar("produtos 10")

        assert leitura.entendida is False

    def test_campo_ambiguo_quando_cita_os_dois(self):
        """Citar estoque e preço juntos com um limite só não define qual filtrar."""
        leitura = interpretar("produtos com preço e estoque abaixo de 10")

        assert leitura.entendida is False
        assert leitura.ambiguidade is not None

    def test_nunca_levanta_excecao(self):
        """Entrada hostil vira recusa, não 500."""
        for entrada in ["", "???", "'; DROP TABLE produto; --", "🙂" * 50, "a" * 5000]:
            leitura = interpretar(entrada)
            assert leitura.entendida in (True, False)
