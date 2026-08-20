"""Testes de hash de senha e JWT.

Este arquivo nasceu de uma medição, não de intuição: `app/core/security.py` estava em 62%
de cobertura, e é o módulo onde um bug não dá erro — dá acesso indevido.

Não precisam de infraestrutura. A parte que toca o banco (`usuario_autenticado`) é coberta
pelos testes de rota em `test_produtos_auth.py`.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import (
    LIMITE_BCRYPT_BYTES,
    conferir_senha,
    criar_token,
    gerar_hash_senha,
)

settings = get_settings()


class TestHashDeSenha:
    def test_hash_nao_contem_a_senha(self):
        hash_gerado = gerar_hash_senha("senha-secreta-123")

        assert "senha-secreta-123" not in hash_gerado
        assert hash_gerado.startswith("$2b$")

    def test_senha_correta_confere(self):
        assert conferir_senha("senha-secreta-123", gerar_hash_senha("senha-secreta-123"))

    def test_senha_errada_nao_confere(self):
        assert not conferir_senha("outra-senha", gerar_hash_senha("senha-secreta-123"))

    def test_a_mesma_senha_gera_hashes_diferentes(self):
        """Salt aleatório: dois usuários com a mesma senha não podem ter o mesmo hash.

        Se tivessem, vazar o banco entregaria de graça quais contas compartilham senha.
        """
        primeiro = gerar_hash_senha("senha-igual")
        segundo = gerar_hash_senha("senha-igual")

        assert primeiro != segundo
        assert conferir_senha("senha-igual", primeiro)
        assert conferir_senha("senha-igual", segundo)

    def test_senha_acima_do_limite_do_bcrypt_e_recusada(self):
        """bcrypt trunca em 72 bytes.

        Sem esta checagem, duas senhas longas diferentes que compartilham os primeiros 72
        bytes virariam o mesmo hash, e uma autenticaria a outra. Prefiro recusar a truncar
        em silêncio.
        """
        with pytest.raises(ValueError, match="72 bytes"):
            gerar_hash_senha("a" * (LIMITE_BCRYPT_BYTES + 1))

    def test_senha_longa_nao_autentica_por_truncamento(self):
        """O ataque que o limite previne, escrito como teste."""
        base = "a" * LIMITE_BCRYPT_BYTES
        hash_gerado = gerar_hash_senha(base)

        assert conferir_senha(base, hash_gerado)
        assert not conferir_senha(base + "sufixo-diferente", hash_gerado)

    def test_acento_na_senha_funciona(self):
        """Senha em português tem acento, e acento ocupa mais de um byte em UTF-8."""
        senha = "não-vou-esquecer-çã"

        assert conferir_senha(senha, gerar_hash_senha(senha))


class TestToken:
    def test_token_carrega_o_id_do_usuario(self):
        usuario_id = uuid.uuid4()

        payload = jwt.decode(
            criar_token(usuario_id), settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )

        assert payload["sub"] == str(usuario_id)

    def test_token_tem_expiracao(self):
        payload = jwt.decode(
            criar_token(uuid.uuid4()), settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )

        expira = datetime.fromtimestamp(payload["exp"], UTC)
        assert expira > datetime.now(UTC)
        assert expira <= datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes + 1)

    def test_token_assinado_com_outro_segredo_e_rejeitado(self):
        """A garantia central do JWT: sem o segredo, não dá para forjar."""
        forjado = jwt.encode(
            {"sub": str(uuid.uuid4()), "exp": datetime.now(UTC) + timedelta(hours=1)},
            "segredo-do-atacante",
            algorithm="HS256",
        )

        with pytest.raises(jwt.InvalidTokenError):
            jwt.decode(forjado, settings.jwt_secret, algorithms=[settings.jwt_algorithm])

    def test_token_expirado_e_rejeitado(self):
        expirado = jwt.encode(
            {"sub": str(uuid.uuid4()), "exp": datetime.now(UTC) - timedelta(seconds=1)},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )

        with pytest.raises(jwt.ExpiredSignatureError):
            jwt.decode(expirado, settings.jwt_secret, algorithms=[settings.jwt_algorithm])

    def test_token_sem_assinatura_e_rejeitado(self):
        """O ataque `alg: none`: o atacante troca o algoritmo por "nenhum" e assina nada.

        Passar `algorithms=` explicitamente é o que fecha isso, e este teste garante que
        alguém não vai "simplificar" removendo o argumento depois.
        """
        sem_assinatura = jwt.encode(
            {"sub": str(uuid.uuid4()), "exp": datetime.now(UTC) + timedelta(hours=1)},
            key="",
            algorithm="none",
        )

        with pytest.raises(jwt.InvalidTokenError):
            jwt.decode(sem_assinatura, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
