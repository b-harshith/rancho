"""Ezyschooling multi-stage collector."""

from .collector import normalize_school, parse_detail_document, parse_page_payload

__all__ = ["normalize_school", "parse_detail_document", "parse_page_payload"]
