"""Language catalogs for the ``rona`` CLI's own output (help text, prompts,
messages). One flat ``STRINGS: dict[str, str]`` module per supported
language; ``rona_cli.i18n`` picks between them and does the ``{...}``
formatting. See ``rona_cli.i18n`` for the lookup/fallback rules.
"""
