"""HTML to plain text."""

from bs4 import BeautifulSoup

from kg_world_anvil.ingestion.text import clean_plain_text


def clean_html(text: str) -> str:
    soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    plain = soup.get_text(separator="\n")
    return clean_plain_text(plain)
