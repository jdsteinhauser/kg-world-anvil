"""BBCode to plain text."""

import re

import bbcode

from kg_world_anvil.ingestion.text import clean_plain_text

_parser = bbcode.Parser()


def clean_bbcode(text: str) -> str:
    plain = _parser.format(text)
    plain = re.sub(r"\[/?[^\]]+\]", "", plain)
    return clean_plain_text(plain)
