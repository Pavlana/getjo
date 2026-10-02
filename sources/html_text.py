"""HTML job descriptions to plain text, shared by the sources that return HTML."""

from html.parser import HTMLParser

# Tags that start a new line on a page; without a space here, "<li>Python</li><li>SQL</li>"
# would become "PythonSQL" and the scorer couldn't quote either word.
_BLOCK_TAGS = {"p", "br", "li", "ul", "ol", "div", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td"}


class _TextExtractor(HTMLParser):
    """Collects the plain-text content of an HTML fragment, tags dropped."""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _BLOCK_TAGS:
            self._parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self._parts.append(" ")

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def html_to_text(html_content: str) -> str:
    """Plain text of an HTML fragment, whitespace collapsed to single spaces."""
    parser = _TextExtractor()
    parser.feed(html_content)
    return " ".join(parser.text().split())
