"""Filtros e paginacao da listagem de produtos.

Ficam em um schema proprio por dois motivos: viram query params documentados no /docs
automaticamente, e o service consegue perguntar ao objeto se aquela consulta pode ou nao
ser cacheada, sem o router opinar sobre cache.
"""

from decimal import Decimal

from pydantic import Field

from app.schemas.base import CustomModel


class FiltrosProduto(CustomModel):
    nome: str | None = Field(default=None, description="Busca parcial, sem diferenciar maiusculas")
    preco_min: Decimal | None = Field(default=None, ge=0)
    preco_max: Decimal | None = Field(default=None, ge=0)
    apenas_estoque_baixo: bool = Field(
        default=False,
        description="Traz so produtos com quantidade menor ou igual ao estoque minimo",
    )
    estoque_min: int | None = Field(default=None, ge=0)
    estoque_max: int | None = Field(default=None, ge=0)
    ativo: bool | None = None

    def toca_estoque(self) -> bool:
        """Consulta que depende de estoque nao entra em cache (ADR 0007).

        Estoque e o dado volatil do catalogo. Um alerta de estoque baixo respondido a
        partir de cache de 60 segundos atras nao serve para nada -- e justamente o alerta
        que precisa ser verdadeiro agora.

        Os filtros numericos de estoque entram na mesma regra: "produtos com menos de 10
        unidades" tem exatamente o mesmo problema de validade que "estoque baixo".
        """
        return (
            self.apenas_estoque_baixo
            or self.estoque_min is not None
            or self.estoque_max is not None
        )


class Paginacao(CustomModel):
    pagina: int = Field(default=1, ge=1)
    tamanho: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.pagina - 1) * self.tamanho


class ConsultaProdutos(FiltrosProduto, Paginacao):
    """Query string da listagem: filtros e paginacao achatados em um modelo so.

    Existe por causa de uma armadilha do FastAPI que custou tempo para achar. Ele expande
    um modelo Pydantic anotado com `Query()` em parametros individuais, mas apenas **um
    por endpoint**. Declarando dois (`filtros` e `paginacao`), ele nao reclama: passa a
    exigir dois query params literalmente chamados `filtros` e `paginacao`. Contrato
    errado, sem erro nenhum no boot.

    Herdo dos dois schemas em vez de repetir os campos, e devolvo cada um pronto para o
    service, que continua recebendo dois objetos com responsabilidades separadas.
    """

    def filtros(self) -> FiltrosProduto:
        return FiltrosProduto.model_validate(self)

    def paginacao(self) -> Paginacao:
        return Paginacao.model_validate(self)
