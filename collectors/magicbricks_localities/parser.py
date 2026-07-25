from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit


CHALLENGE_MARKERS = (
    "captcha", "verify you are human", "access denied", "unusual traffic",
    "temporarily blocked", "security check", "cloudflare",
)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(value or "")).strip()


def canonical_url(value: str, base_url: str = "https://www.magicbricks.com/") -> str:
    parts = urlsplit(urljoin(base_url, value))
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def is_challenge(html: str) -> bool:
    folded = clean_text(re.sub(r"<[^>]+>", " ", html)).casefold()
    return any(marker in folded for marker in CHALLENGE_MARKERS)


class _ListingParser(HTMLParser):
    def __init__(self, page_url: str):
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.stack: list[tuple[str, dict[str, str]]] = []
        self.cards: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self.capture: str | None = None
        self.buffer: list[str] = []
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        self.stack.append((tag, a))
        classes = set(a.get("class", "").split())
        if a.get("id") == "domcache_locality_detail":
            self.meta.update({k.removeprefix("data-"): v for k, v in a.items() if k.startswith("data-")})
        if tag == "div" and "loc-card" in classes:
            self.current = {"_depth": len(self.stack), "page_url": self.page_url}
        if self.current is None:
            return
        if tag == "a" and "loc-card__title" in classes and a.get("href"):
            self.current["source_url"] = canonical_url(a["href"], self.page_url)
            self.capture = "title"
            self.buffer = []
        elif "loc-card__price" in classes:
            self.capture = "price"
            self.buffer = []
        elif "loc-card__rating" in classes:
            self.capture = "rating"
            self.buffer = []
        elif "loc-card__review" in classes or "loc-card__reviews" in classes:
            self.capture = "reviews"
            self.buffer = []

    def handle_data(self, data: str) -> None:
        if self.current is not None:
            self.current.setdefault("_all_text", []).append(data)
        if self.capture:
            self.buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.capture and self.stack and self.stack[-1][0] == tag:
            value = clean_text(" ".join(self.buffer))
            if value and self.current is not None:
                self.current[self.capture] = value
            self.capture, self.buffer = None, []
        if self.current is not None and len(self.stack) == self.current.get("_depth") and tag == "div":
            self._finish_card()
        if self.stack:
            self.stack.pop()

    def _finish_card(self) -> None:
        card = self.current or {}
        text = clean_text(" ".join(card.pop("_all_text", [])))
        card.pop("_depth", None)
        if "source_url" in card:
            card["card_text"] = text
            if not card.get("title"):
                card["title"] = text.split("₹", 1)[0].strip()
            self.cards.append(card)
        self.current = None


def _number(pattern: str, text: str, cast: type = float) -> Any:
    match = re.search(pattern, text, re.I)
    if not match:
        return None
    raw = match.group(1).replace(",", "")
    try:
        return cast(raw)
    except ValueError:
        return None


def parse_listing_page(html: str, page_url: str) -> dict[str, Any]:
    parser = _ListingParser(page_url)
    parser.feed(html)
    meta = parser.meta
    cards = []
    # Cards contain deeply nested, occasionally unbalanced markup. Locality-title
    # anchors are the stable boundary advertised by the page itself.
    anchors = list(re.finditer(
        r'<a\b(?=[^>]*\bclass=["\'][^"\']*\bloc-card__title\b[^"\']*["\'])(?=[^>]*\bhref=["\'](?P<href>[^"\']+)["\'])[^>]*>(?P<title>.*?)</a>',
        html, re.I | re.S,
    ))
    raw_cards: list[dict[str, Any]] = []
    for index, anchor in enumerate(anchors):
        end = anchors[index + 1].start() if index + 1 < len(anchors) else min(len(html), anchor.end() + 30000)
        raw_cards.append({
            "page_url": page_url,
            "source_url": canonical_url(anchor.group("href"), page_url),
            "title": clean_text(re.sub(r"<[^>]+>", " ", anchor.group("title"))),
            "card_text": clean_text(re.sub(r"<[^>]+>", " ", html[anchor.end():end])),
        })
    for card in raw_cards:
        text = card.pop("card_text", "")
        title = clean_text(card.get("title", ""))
        name, _, city = title.partition(",")
        price_values = [int(v.replace(",", "")) for v in re.findall(r"₹\s*([\d,]+)", text)]
        card.update({
            "name": name.strip(),
            "source_city_name": city.strip() or meta.get("cityname"),
            "source_city_id": meta.get("cityid"),
            "price_per_sqft_min": price_values[0] if price_values else None,
            "price_per_sqft_max": price_values[1] if len(price_values) > 1 else (price_values[0] if price_values else None),
            "rating": _number(r"\b([0-5]\.\d)\s+[\d,]+\s+reviews?", text),
            "reviews": _number(r"([\d,]+)\s+reviews?", text, int),
            "rank": _number(r"Rank\s+([\d,]+)", text, int),
        })
        # Overview URLs carry a stable locality identity; the detail page supplies locid.
        card["link_key"] = card["source_url"].casefold()
        cards.append(card)
    return {
        "source_city_name": meta.get("cityname"),
        "source_city_id": meta.get("cityid"),
        "total_localities": _number(r"^([\d,]+)$", meta.get("totallocality", ""), int),
        "current_page": _number(r"^([\d,]+)$", meta.get("currentpage", ""), int),
        "records": cards,
        "challenge": is_challenge(html),
    }


def _attr_block(html: str, element_id: str) -> dict[str, str]:
    match = re.search(rf"<span\b[^>]*id=[\"']{re.escape(element_id)}[\"'][^>]*>", html, re.I)
    if not match:
        return {}
    return {k.casefold(): html_lib.unescape(v) for k, _, v in re.findall(r"([\w:-]+)\s*=\s*([\"'])(.*?)\2", match.group(0), re.S)}


def parse_detail_page(html: str, source_url: str) -> dict[str, Any]:
    attrs = _attr_block(html, "domcache_locality_detail")
    visible = clean_text(re.sub(r"<script\b.*?</script>|<style\b.*?</style>|<[^>]+>", " ", html, flags=re.I | re.S))
    name = attrs.get("data-locname")
    city = attrs.get("data-cityname")
    source_id = attrs.get("data-locid")
    rating = _number(rf"{re.escape(name or '')}\s+is rated as\s+([0-5](?:\.\d+)?)\s*/\s*5", visible)
    reviews = _number(r"basis\s+([\d,]+)\s+reviews", visible, int)
    if rating is None:
        rating = _number(r"([0-5](?:\.\d+)?)\s+([\d,]+)\s+reviews", visible)
    if reviews is None:
        reviews = _number(r"([\d,]+)\s+reviews", visible, int)
    avg = _number(r'data-lmtavgprice=["\']([\d.]+)', html)
    return {
        "source_entity_id": source_id,
        "name": name,
        "source_city_name": city,
        "source_city_id": attrs.get("data-cityid"),
        "source_url": canonical_url(source_url),
        "latitude": _number(r"^(-?[\d.]+)$", attrs.get("data-latitude", "")),
        "longitude": _number(r"^(-?[\d.]+)$", attrs.get("data-longitude", "")),
        "price_per_sqft_avg": avg,
        "rating": rating,
        "reviews": reviews,
        "challenge": is_challenge(html),
    }
