"""Contrato de autenticacao."""

from app.schemas.base import CustomModel


class TokenResponse(CustomModel):
    access_token: str
    token_type: str = "bearer"
