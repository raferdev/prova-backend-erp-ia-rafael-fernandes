"""Tradutor de pergunta em linguagem natural para consulta estruturada.

Determinístico, por regras. Nenhum LLM em runtime, que é exigência do enunciado.

A decisão que organiza o arquivo inteiro: **o parser recusa quando não entende, em vez de
adivinhar**, e sempre devolve a interpretação que fez, em português, junto com o resultado.

Um parser que lê "produtos acima de 10 reais" e silenciosamente filtra por estoque é pior
que um que diz "não entendi": o usuário confia num número errado. É o mesmo princípio da
Parte 2 (falha não pode se disfarçar de resultado), aplicado a outro problema.

Ele também não monta consulta própria: produz o mesmo `FiltrosProduto` que a API REST usa.
Se montasse SQL paralelo, divergiria do endpoint na primeira mudança de regra.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Literal

from app.schemas.filtros import FiltrosProduto

Intencao = Literal["listar", "contar"]

EXEMPLOS = [
    "produtos com estoque abaixo de 10",
    "quantos produtos estão com estoque baixo",
    "produtos com preço acima de 100",
    "produtos entre 50 e 200 reais",
    "produtos com nome cabo",
    "produtos inativos",
]

# Números por extenso mais comuns numa pergunta de operação. Não tento cobrir o idioma
# inteiro: o que não estiver aqui cai na recusa explícita, que é o comportamento correto.
NUMEROS_POR_EXTENSO = {
    "zero": 0,
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "tres": 3,
    "quatro": 4,
    "cinco": 5,
    "seis": 6,
    "sete": 7,
    "oito": 8,
    "nove": 9,
    "dez": 10,
    "onze": 11,
    "doze": 12,
    "quinze": 15,
    "vinte": 20,
    "trinta": 30,
    "quarenta": 40,
    "cinquenta": 50,
    "cem": 100,
    "duzentos": 200,
    "mil": 1000,
}

TERMOS_ESTOQUE = ("estoque", "unidades", "quantidade", "saldo")
TERMOS_PRECO = ("preco", "valor", "reais", "r$", "custa", "custam", "custo")

MENOR = ("abaixo de", "menor que", "menos de", "inferior a", "ate", "no maximo")
MAIOR = ("acima de", "maior que", "mais de", "superior a", "a partir de", "no minimo")

ESTOQUE_BAIXO = (
    "estoque baixo",
    "em falta",
    "acabando",
    "precisa repor",
    "abaixo do minimo",
    "estoque critico",
    "para repor",
)


@dataclass
class Interpretacao:
    """O que o parser entendeu. Sempre devolvido, mesmo quando não entendeu nada."""

    entendida: bool
    intencao: Intencao = "listar"
    filtros: FiltrosProduto | None = None
    explicacao: str = ""
    ambiguidade: str | None = None
    sugestoes: list[str] = field(default_factory=lambda: list(EXEMPLOS))


def _sem_acento(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def _normalizar(pergunta: str) -> str:
    return re.sub(r"\s+", " ", _sem_acento(pergunta.lower())).strip()


def _para_decimal(bruto: str) -> Decimal | None:
    """Converte número no formato pt-BR.

    `1.234,56` tem ponto de milhar e vírgula decimal. Tratar isso como formato americano
    transformaria mil reais em um real, que num ERP é o tipo de erro que ninguém percebe
    até o fechamento.
    """
    texto = bruto.strip()
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", texto):
        texto = texto.replace(".", "")
    try:
        return Decimal(texto)
    except InvalidOperation:
        return None


def _numeros(texto: str) -> list[Decimal]:
    encontrados = [
        valor
        for bruto in re.findall(r"\d[\d.,]*", texto)
        if (valor := _para_decimal(bruto)) is not None
    ]
    if encontrados:
        return encontrados
    return [
        Decimal(NUMEROS_POR_EXTENSO[palavra])
        for palavra in texto.split()
        if palavra in NUMEROS_POR_EXTENSO
    ]


def _contem(texto: str, termos: tuple[str, ...]) -> bool:
    return any(termo in texto for termo in termos)


def _campo_citado(texto: str) -> Literal["estoque", "preco"] | None:
    tem_estoque = _contem(texto, TERMOS_ESTOQUE)
    tem_preco = _contem(texto, TERMOS_PRECO)
    if tem_estoque and not tem_preco:
        return "estoque"
    if tem_preco and not tem_estoque:
        return "preco"
    return None


def interpretar(pergunta: str) -> Interpretacao:
    """Traduz a pergunta. Nunca levanta exceção: pergunta ruim vira recusa explicada."""
    texto = _normalizar(pergunta)
    if not texto:
        return Interpretacao(entendida=False, explicacao="A pergunta está vazia.")

    intencao: Intencao = "contar" if re.search(r"\bquant[oa]s?\b", texto) else "listar"
    filtros = FiltrosProduto()
    partes: list[str] = []

    if _contem(texto, ESTOQUE_BAIXO):
        filtros.apenas_estoque_baixo = True
        partes.append("com estoque no limiar de reposição de cada produto")

    if "inativo" in texto:
        filtros.ativo = False
        partes.append("inativos")
    elif "ativo" in texto:
        filtros.ativo = True
        partes.append("ativos")

    if nome := re.search(r"(?:nome|chamado[as]?|contendo|com a palavra)\s+([a-z0-9\-]+)", texto):
        filtros.nome = nome.group(1)
        partes.append(f'com "{nome.group(1)}" no nome')

    valores = _numeros(texto)
    campo = _campo_citado(texto)

    faixa = re.search(r"entre\s+([\d.,]+)\s+e\s+([\d.,]+)", texto)
    faixa_aplicada = bool(faixa) and len(valores) >= 2
    if faixa_aplicada:
        inicio, fim = sorted(valores[:2])
        if campo == "estoque":
            filtros.estoque_min, filtros.estoque_max = int(inicio), int(fim)
            partes.append(f"com estoque entre {int(inicio)} e {int(fim)}")
        else:
            # Faixa sem campo citado assume preço: "entre 50 e 200 reais" é o uso natural,
            # e a explicação devolvida deixa a suposição visível para o usuário conferir.
            filtros.preco_min, filtros.preco_max = inicio, fim
            partes.append(f"com preço entre {inicio} e {fim}")

    # Avaliados fora do `elif` de propósito: com `or` e walrus, o curto-circuito deixaria
    # `maior` sem valor sempre que `menor` fosse verdadeiro.
    menor = _contem(texto, MENOR)
    maior = _contem(texto, MAIOR)

    if not faixa_aplicada and valores and (menor or maior):
        valor = valores[0]
        if campo is None:
            return Interpretacao(
                entendida=False,
                ambiguidade=(
                    f"Entendi um limite de {valor}, mas não de qual campo: estoque ou preço?"
                ),
                explicacao="A pergunta tem um número, mas não diz a que ele se refere.",
                sugestoes=[
                    f"produtos com estoque abaixo de {valor}",
                    f"produtos com preço abaixo de {valor}",
                ],
            )
        if campo == "estoque":
            if menor:
                filtros.estoque_max = int(valor)
                partes.append(f"com estoque de no máximo {int(valor)}")
            else:
                filtros.estoque_min = int(valor)
                partes.append(f"com estoque de no mínimo {int(valor)}")
        elif menor:
            filtros.preco_max = valor
            partes.append(f"com preço de no máximo {valor}")
        else:
            filtros.preco_min = valor
            partes.append(f"com preço de no mínimo {valor}")

    if not partes:
        return Interpretacao(
            entendida=False,
            explicacao="Não reconheci nenhum filtro nesta pergunta.",
        )

    verbo = "Contar produtos" if intencao == "contar" else "Listar produtos"
    return Interpretacao(
        entendida=True,
        intencao=intencao,
        filtros=filtros,
        explicacao=f"{verbo} {', '.join(partes)}.",
    )
