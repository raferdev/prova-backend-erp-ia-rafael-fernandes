"""Servidor MCP que expõe as ferramentas do ERP a um agente.

Fica em pasta própria por ser um entrypoint alternativo da aplicação, no mesmo sentido que
`main.py` é o entrypoint HTTP e `app/workers/` é o da fila. Ele consome a API pública por
HTTP, e não as camadas internas -- ver `cliente_erp.py` para o porquê.
"""
