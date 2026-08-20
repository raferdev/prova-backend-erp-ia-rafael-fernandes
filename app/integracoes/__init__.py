"""Gateways para outros bounded contexts do ERP.

Pasta propria porque isto nao e persistencia (`repositories/` fala com o banco) nem regra
de negocio (`services/`). Sao adaptadores para servicos que pertencem a outros modulos:
Clientes, Financeiro e Logistica. Misturar isso em `repositories/` faria a camada mentir
sobre o que ela e.
"""
