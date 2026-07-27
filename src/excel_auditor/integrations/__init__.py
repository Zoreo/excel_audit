"""External integrations (Microsoft Teams webhooks, MCP server).

Everything in this package is scaffolding around the application services in
``services.py`` / ``query_service.py``: no analysis logic lives here, only
transport, card formatting and command parsing. The Teams router is mounted
into the FastAPI app only when ``EXCEL_AUDITOR_TEAMS_ENABLED=1``; the MCP
server is started explicitly via ``python -m excel_auditor.integrations.mcp_server``.
"""
