"""
Tạo BeautifulSoup dùng chung: ưu tiên lxml, chưa cài thì dùng html.parser.
"""

import importlib.util
import logging

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HTML_PARSER = "lxml" if importlib.util.find_spec("lxml") is not None else "html.parser"

_has_warned = False


def make_soup(html: str) -> BeautifulSoup:
    """
    Phân tích HTML bằng parser tốt nhất đang có.
    """
    global _has_warned
    if HTML_PARSER != "lxml" and not _has_warned:
        logger.warning("Chưa cài lxml, đang dùng html.parser (chậm hơn). Cài bằng: pip install -r requirements.txt")
        _has_warned = True

    return BeautifulSoup(html or "", HTML_PARSER)
