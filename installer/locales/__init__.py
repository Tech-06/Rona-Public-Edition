"""Language catalogs for the installer's own output. One flat
``STRINGS: dict[str, str]`` module per supported language;
``installer.i18n`` picks between them and does the ``{...}`` formatting.
Independent from ``rona_cli.locales`` (the CLI's own catalog) -- see the
language plan's "Ortak sözleşme" table for why each component's language
lives and is looked up separately.
"""
