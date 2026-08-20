"""Popula o banco com dados minimos para conseguir usar a API.

Rodar com:  python -m app.core.seed

Idempotente de proposito: rodar duas vezes nao duplica nada nem quebra. Seed que so
funciona em banco vazio e seed que ninguem roda.

As credenciais saem do ambiente (SEED_USUARIO_EMAIL / SEED_USUARIO_SENHA) com um padrao
obvio de desenvolvimento. Isso nao e usuario de producao.
"""

import asyncio
import os
from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionLocal, engine
from app.core.security import gerar_hash_senha
from app.models.produto import Produto
from app.models.usuario import Usuario

EMAIL_PADRAO = os.getenv("SEED_USUARIO_EMAIL", "admin@erp.local")
SENHA_PADRAO = os.getenv("SEED_USUARIO_SENHA", "admin123")

# Nove produtos, e a quantidade nao e arbitraria: a listagem pagina de cinco em cinco,
# entao com cinco produtos nao existe pagina 2 e o controle de paginacao some da tela.
# Os testes de paginacao passavam so porque eu tinha criado um produto extra a mao durante
# o desenvolvimento -- num clone novo eles falhavam. Seed que nao exercita o proprio
# comportamento da aplicacao e seed incompleto.
#
# A mistura de saldos tambem e proposital: uns acima do minimo, uns no limiar exato e um
# zerado, para o filtro de estoque baixo ter o que mostrar logo no primeiro acesso.
PRODUTOS = [
    ("Cabo HDMI 2m", "Cabo HDMI 2.1 de 2 metros", Decimal("39.90"), 120, 20),
    ("Teclado mecanico ABNT2", "Switch marrom, layout ABNT2", Decimal("289.00"), 8, 10),
    ("Monitor 27 polegadas", "IPS 1440p 75Hz", Decimal("1499.90"), 3, 5),
    ("Mouse sem fio", "2.4GHz com receptor USB", Decimal("89.90"), 45, 15),
    ("Hub USB-C 7 portas", "HDMI, USB 3.0 e leitor SD", Decimal("219.00"), 0, 4),
    ("Webcam 1080p", "Autofoco com microfone estereo", Decimal("199.90"), 27, 8),
    ("SSD NVMe 1TB", "PCIe 4.0, leitura 7000MB/s", Decimal("649.00"), 12, 12),
    ("Fonte 650W 80 Plus", "Modular, certificacao Bronze", Decimal("459.90"), 6, 3),
    ("Suporte de monitor", "Articulado, VESA 75/100", Decimal("129.90"), 31, 10),
]


async def semear() -> None:
    async with SessionLocal() as session:
        existente = await session.scalar(select(Usuario).where(Usuario.email == EMAIL_PADRAO))
        if existente is None:
            session.add(Usuario(email=EMAIL_PADRAO, senha_hash=gerar_hash_senha(SENHA_PADRAO)))
            print(f"usuario criado: {EMAIL_PADRAO}")
        else:
            print(f"usuario ja existe: {EMAIL_PADRAO}")

        for nome, descricao, preco, quantidade, minimo in PRODUTOS:
            ja_existe = await session.scalar(select(Produto).where(Produto.nome == nome))
            if ja_existe is None:
                session.add(
                    Produto(
                        nome=nome,
                        descricao=descricao,
                        preco=preco,
                        quantidade_estoque=quantidade,
                        estoque_minimo=minimo,
                    )
                )

        await session.commit()

    await engine.dispose()
    print("seed concluido")


if __name__ == "__main__":
    asyncio.run(semear())
