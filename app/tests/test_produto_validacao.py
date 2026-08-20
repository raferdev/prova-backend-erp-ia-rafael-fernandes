"""Validacao do contrato de produto.

A prova pede explicitamente preco nao negativo e nome que nao seja numerico nem nulo.
Testo no schema, que e onde a regra mora -- se ela vazasse para o service, cada endpoint
novo precisaria repeti-la.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.produto import ProdutoCreate


def produto_valido(**sobrescritas):
    base = {"nome": "Cabo HDMI 2m", "preco": Decimal("39.90")}
    return ProdutoCreate(**{**base, **sobrescritas})


def test_aceita_produto_valido():
    produto = produto_valido()

    assert produto.nome == "Cabo HDMI 2m"
    assert produto.quantidade_estoque == 0


def test_preco_negativo_e_rejeitado():
    with pytest.raises(ValidationError) as erro:
        produto_valido(preco=Decimal("-1.00"))

    assert "greater_than_equal" in str(erro.value)


def test_preco_zero_e_aceito():
    """Zero e diferente de negativo: brinde e amostra tem preco zero legitimamente."""
    assert produto_valido(preco=Decimal("0")).preco == Decimal("0")


@pytest.mark.parametrize("nome", ["12345", "42"])
def test_nome_apenas_numerico_e_rejeitado(nome):
    with pytest.raises(ValidationError, match="apenas numerico"):
        produto_valido(nome=nome)


@pytest.mark.parametrize("nome", ["", "   "])
def test_nome_vazio_ou_so_espaco_e_rejeitado(nome):
    with pytest.raises(ValidationError):
        produto_valido(nome=nome)


def test_nome_com_numero_no_meio_e_aceito():
    """A regra e "so numeros", nao "sem numeros".

    "Monitor 27 polegadas" tem digito e e um nome de produto perfeitamente legitimo.
    """
    assert produto_valido(nome="Monitor 27 polegadas").nome == "Monitor 27 polegadas"


def test_nome_e_normalizado_sem_espaco_nas_pontas():
    assert produto_valido(nome="  Mouse sem fio  ").nome == "Mouse sem fio"


def test_estoque_negativo_e_rejeitado():
    with pytest.raises(ValidationError):
        produto_valido(quantidade_estoque=-5)


def test_preco_com_mais_de_duas_casas_e_rejeitado():
    """A coluna e NUMERIC(12,2). Aceitar 3 casas no contrato criaria arredondamento silencioso."""
    with pytest.raises(ValidationError):
        produto_valido(preco=Decimal("10.999"))
