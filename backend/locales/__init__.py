"""Language catalogs for backend-authored, human-facing text. One flat
``STRINGS: dict[str, str]`` module per supported language; ``i18n``
(the package root's ``i18n.py``) picks between them and does the
``{...}`` formatting.
"""
