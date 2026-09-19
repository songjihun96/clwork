"""EPUB 2/3 parser written on the standard library + defusedxml.

EbookLib is not used: it is AGPL-licensed, which is a poor fit for a closed-source network service.

Security (docs/security.md §4): the archive is never extracted to disk; entry count, total
uncompressed size and per-entry compression ratio are capped (zip bombs); XML metadata is parsed
with defusedxml (XXE / entity expansion); XHTML bodies go through html.parser, which does not
resolve external entities.
"""

import io
import posixpath
import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import unquote, urldefrag
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from story_core.ingestion.parsed import ChapterBuilder, IngestionError, ParsedBook, normalize_text

EPUB_MIMETYPE = b"application/epub+zip"


@dataclass(frozen=True, slots=True)
class EpubLimits:
    max_entries: int = 5_000
    max_total_uncompressed_bytes: int = 300 * 1024 * 1024
    max_entry_uncompressed_bytes: int = 50 * 1024 * 1024
    max_compression_ratio: int = 200


_NS = {
    "container": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
}
_XHTML_TYPES = frozenset({"application/xhtml+xml", "text/html"})
_ENCODING_DECL = re.compile(rb"""^\s*<\?xml[^>]*encoding=["']([A-Za-z0-9._-]+)["']""")


def looks_like_epub(data: bytes) -> bool:
    # The OCF spec requires an uncompressed first entry named "mimetype".
    return data[:4] == b"PK\x03\x04" and data[30:38] == b"mimetype" and EPUB_MIMETYPE in data[38:120]


class _Archive:
    def __init__(self, data: bytes, limits: EpubLimits) -> None:
        try:
            self._zip = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise IngestionError("invalid_epub", "Not a valid EPUB (zip) file") from exc
        infos = self._zip.infolist()
        if len(infos) > limits.max_entries:
            raise IngestionError("epub_too_complex", "EPUB has too many files")
        total = 0
        for info in infos:
            name = info.filename
            if name.startswith(("/", "\\")) or ".." in name.split("/") or ":" in name:
                raise IngestionError("invalid_epub", "EPUB contains an unsafe file path")
            if info.file_size > limits.max_entry_uncompressed_bytes:
                raise IngestionError("epub_too_large", "EPUB contains an oversized file")
            if info.compress_size and info.file_size / info.compress_size > limits.max_compression_ratio:
                raise IngestionError("epub_too_large", "EPUB compression ratio is suspicious")
            total += info.file_size
        if total > limits.max_total_uncompressed_bytes:
            raise IngestionError("epub_too_large", "EPUB is too large when uncompressed")
        self._names = {info.filename for info in infos}

    def read(self, name: str) -> bytes:
        if name not in self._names:
            raise IngestionError("invalid_epub", "EPUB references a missing file")
        return self._zip.read(name)

    def has(self, name: str) -> bool:
        return name in self._names


def _xml(data: bytes) -> Element:
    try:
        root: Element = SafeET.fromstring(data)
        return root
    except (SafeET.ParseError, DefusedXmlException) as exc:
        raise IngestionError("invalid_epub", "EPUB metadata is not valid XML") from exc


def _decode_markup(data: bytes) -> str:
    match = _ENCODING_DECL.match(data[:200])
    encoding = match.group(1).decode("ascii") if match else "utf-8"
    try:
        return data.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        return data.decode("utf-8", errors="replace")


def _resolve(base_dir: str, href: str) -> str:
    path = unquote(urldefrag(href)[0])
    return posixpath.normpath(posixpath.join(base_dir, path)) if base_dir else posixpath.normpath(path)


# ----------------------------------------------------------------------------- XHTML


_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "li",
        "blockquote",
        "pre",
        "dd",
        "dt",
        "td",
        "th",
        "section",
        "article",
        "aside",
        "figcaption",
        "header",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
    }
)
_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_SKIP_TAGS = frozenset({"script", "style", "head", "title", "nav", "svg", "math", "rt", "rp"})


@dataclass(frozen=True, slots=True)
class _Block:
    kind: str  # "heading" | "paragraph" | "break"
    text: str = ""
    level: int = 0


class _BlockExtractor(HTMLParser):
    """Flattens XHTML into heading/paragraph/break blocks; nested blocks emit their own text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[_Block] = []
        self._buffer: list[str] = []
        self._skip_depth = 0
        self._heading_stack: list[int] = []

    def _flush(self) -> None:
        text = normalize_text("".join(self._buffer))
        self._buffer.clear()
        if not text:
            return
        if self._heading_stack:
            self.blocks.append(_Block("heading", text, self._heading_stack[-1]))
        else:
            self.blocks.append(_Block("paragraph", text))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "br":
            self._buffer.append(" ")
        elif tag == "hr":
            self._flush()
            self.blocks.append(_Block("break"))
        elif tag in _BLOCK_TAGS:
            self._flush()
            if tag in _HEADINGS:
                self._heading_stack.append(_HEADINGS[tag])
        elif tag == "img":
            alt = dict(attrs).get("alt")
            if alt and alt.strip() in {"*", "***", "◇"}:
                self._flush()
                self.blocks.append(_Block("break"))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in ("br", "hr", "img"):
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag in _BLOCK_TAGS:
            self._flush()
            if tag in _HEADINGS and self._heading_stack:
                self._heading_stack.pop()

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._buffer.append(data)

    def close(self) -> None:
        super().close()
        self._flush()


class _TocExtractor(HTMLParser):
    """Collects (href, label) pairs from an EPUB3 navigation document's toc nav."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[tuple[str, str]] = []
        self._nav_depth = 0
        self._in_toc = False
        self._href: str | None = None
        self._label: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "nav":
            self._nav_depth += 1
            kind = attributes.get("epub:type") or attributes.get("role") or ""
            if "toc" in kind:
                self._in_toc = True
        elif tag == "a" and self._in_toc:
            self._href = attributes.get("href")
            self._label = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "nav":
            self._nav_depth -= 1
            if self._nav_depth <= 0:
                self._in_toc = False
        elif tag == "a" and self._href is not None:
            label = normalize_text("".join(self._label))
            if label:
                self.entries.append((self._href, label))
            self._href = None

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._label.append(data)


# ----------------------------------------------------------------------------- main


def parse_epub(data: bytes, limits: EpubLimits | None = None) -> ParsedBook:
    if not looks_like_epub(data):
        raise IngestionError("invalid_epub", "Not an EPUB file (missing mimetype entry)")
    archive = _Archive(data, limits or EpubLimits())

    container = _xml(archive.read("META-INF/container.xml"))
    rootfile = container.find(".//container:rootfile", _NS)
    opf_path = rootfile.get("full-path") if rootfile is not None else None
    if not opf_path:
        raise IngestionError("invalid_epub", "EPUB container has no package document")
    opf_dir = posixpath.dirname(opf_path)
    opf = _xml(archive.read(opf_path))

    title_el = opf.find(".//dc:title", _NS)
    creator_el = opf.find(".//dc:creator", _NS)
    title = normalize_text(title_el.text or "") if title_el is not None and title_el.text else None
    author = normalize_text(creator_el.text or "") if creator_el is not None and creator_el.text else None

    manifest: dict[str, tuple[str, str, str]] = {}
    for item in opf.findall(".//opf:manifest/opf:item", _NS):
        item_id, href = item.get("id"), item.get("href")
        if item_id and href:
            manifest[item_id] = (
                _resolve(opf_dir, href),
                item.get("media-type", ""),
                item.get("properties", ""),
            )

    toc_titles = _read_toc(archive, opf, manifest)

    spine = opf.find(".//opf:spine", _NS)
    if spine is None:
        raise IngestionError("invalid_epub", "EPUB has no reading order (spine)")

    builder = ChapterBuilder()
    for itemref in spine.findall("opf:itemref", _NS):
        if itemref.get("linear", "yes") == "no":
            continue
        entry = manifest.get(itemref.get("idref", ""))
        if entry is None or entry[1] not in _XHTML_TYPES or "nav" in entry[2].split():
            continue
        path = entry[0]
        extractor = _BlockExtractor()
        extractor.feed(_decode_markup(archive.read(path)))
        extractor.close()
        _add_document(builder, extractor.blocks, toc_titles.get(path))

    chapters = builder.result()
    if not chapters:
        raise IngestionError("empty_book", "The EPUB has no readable text")
    return ParsedBook(title=title or None, author=author or None, chapters=chapters)


def _read_toc(archive: _Archive, opf: Element, manifest: dict[str, tuple[str, str, str]]) -> dict[str, str]:
    titles: dict[str, str] = {}
    nav = next((entry for entry in manifest.values() if "nav" in entry[2].split()), None)
    if nav is not None and archive.has(nav[0]):
        parser = _TocExtractor()
        parser.feed(_decode_markup(archive.read(nav[0])))
        parser.close()
        nav_dir = posixpath.dirname(nav[0])
        for href, label in parser.entries:
            titles.setdefault(_resolve(nav_dir, href), label)
        if titles:
            return titles

    spine = opf.find(".//opf:spine", _NS)
    ncx_entry = manifest.get(spine.get("toc", "")) if spine is not None else None
    if ncx_entry is not None and archive.has(ncx_entry[0]):
        ncx = _xml(archive.read(ncx_entry[0]))
        ncx_dir = posixpath.dirname(ncx_entry[0])
        for point in ncx.iter(f"{{{_NS['ncx']}}}navPoint"):
            label_el = point.find("ncx:navLabel/ncx:text", _NS)
            content = point.find("ncx:content", _NS)
            if label_el is not None and label_el.text and content is not None and content.get("src"):
                titles.setdefault(_resolve(ncx_dir, content.get("src", "")), normalize_text(label_el.text))
    return titles


def _add_document(builder: ChapterBuilder, blocks: list[_Block], toc_title: str | None) -> None:
    if not any(b.kind == "paragraph" for b in blocks):
        return  # cover pages, image-only pages, blank separators

    first_heading = next((b for b in blocks if b.kind == "heading"), None)
    chapter_title = toc_title or (first_heading.text if first_heading else None)
    consumed_heading = False
    if chapter_title:
        builder.start_chapter(chapter_title)
    elif not builder.chapters:
        builder.start_chapter("본문")
    # else: an untitled document continues the previous chapter (books are often split into files).

    for block in blocks:
        if block.kind == "heading":
            if not consumed_heading and chapter_title and block is first_heading:
                consumed_heading = True
                if normalize_text(block.text) == normalize_text(chapter_title) or toc_title is None:
                    continue
            builder.start_section(block.text)
        elif block.kind == "break":
            builder.scene_break()
        else:
            builder.add_paragraph(block.text)
