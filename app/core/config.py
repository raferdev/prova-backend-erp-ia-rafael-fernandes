"""Configuracao central da aplicacao.

Toda variavel sensivel entra por ambiente (.env em dev, secrets manager em prod).
Usamos pydantic-settings para que a config seja *validada no boot*: se faltar uma
variavel obrigatoria a aplicacao nao sobe, em vez de quebrar no primeiro request.
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# HMAC-SHA256 usa chave de 256 bits. Segredo menor que isso reduz o custo de forjar um
# token, e a RFC 7518 (secao 3.2) exige chave de pelo menos o tamanho do hash.
TAMANHO_MINIMO_JWT_SECRET = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_debug: bool = True

    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    cache_ttl_seconds: int = 60

    @field_validator("jwt_secret")
    @classmethod
    def segredo_precisa_ser_forte(cls, valor: str) -> str:
        """Recusa segredo curto no boot.

        Descobri isso rodando os testes: o PyJWT emite `InsecureKeyLengthWarning` para
        chave abaixo de 32 bytes, e tanto o segredo de teste quanto o do `.env.example`
        estavam abaixo. Aviso em log e o tipo de coisa que ninguem le; recusar o boot,
        nao.

        Gere um com:  python -c "import secrets; print(secrets.token_urlsafe(48))"
        """
        if len(valor.encode()) < TAMANHO_MINIMO_JWT_SECRET:
            raise ValueError(
                f"JWT_SECRET precisa de ao menos {TAMANHO_MINIMO_JWT_SECRET} bytes "
                f"(recebeu {len(valor.encode())}). Gere com "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return valor

    @property
    def database_url(self) -> str:
        """DSN async (driver asyncpg) usado pelo SQLAlchemy."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache
def get_settings() -> Settings:
    """Cacheado: a config e lida do ambiente uma unica vez por processo.

    Tambem serve como dependencia do FastAPI, o que permite sobrescrever
    a config nos testes via dependency_overrides.
    """
    return Settings()  # type: ignore[call-arg]
