"""Document parsing: files → section trees."""

from regtrace.parsing.html import fetch_html, parse_html, parse_html_file
from regtrace.parsing.pdf import parse_pdf

__all__ = ["fetch_html", "parse_html", "parse_html_file", "parse_pdf"]
