# Runtime bootstrap belongs at executable boundaries

Each executable performs `config.load_and_apply_settings()` before it reads configuration-dependent values; library imports never load `.env`, resolve settings, or mutate process configuration. The Discord application is assembled by a factory after bootstrap rather than through an import-time global. The bootstrap loads the repository `.env` through the direct `python-dotenv` dependency without replacing a non-empty process value, then applies `config.json` only to unset or empty values. This favors explicit startup assembly over convenient import-time globals because the latter made behavior depend on import order and left entry points with inconsistent configuration.

Rejected alternative: relying on `uv run --env-file` instead of application bootstrap. It would make essential runtime behavior depend on how a command happens to be invoked, while scheduled, service, and direct-Python execution can omit the flag.
