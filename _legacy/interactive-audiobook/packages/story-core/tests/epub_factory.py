"""Builds small EPUB files in memory for tests (no binary fixtures in the repo)."""

import io
import zipfile

CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""


def xhtml(body: str, title: str = "t") -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        f"<head><title>{title}</title><style>p {{ margin: 0 }}</style></head><body>{body}</body></html>"
    )


def build_epub(
    documents: list[tuple[str, str]],
    *,
    title: str = "등대지기의 밤",
    author: str = "샘플",
    nav: list[tuple[str, str]] | None = None,
    extra_files: dict[str, bytes] | None = None,
    non_linear: set[str] | None = None,
) -> bytes:
    """documents: [(file name under OEBPS/text/, xhtml)]; nav: [(href relative to OEBPS/, label)]."""
    manifest = []
    spine = []
    for index, (name, _) in enumerate(documents):
        manifest.append(f'<item id="d{index}" href="text/{name}" media-type="application/xhtml+xml"/>')
        linear = ' linear="no"' if non_linear and name in non_linear else ""
        spine.append(f'<itemref idref="d{index}"{linear}/>')
    if nav is not None:
        manifest.append(
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        )
    opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:uuid:test</dc:identifier><dc:title>{title}</dc:title><dc:creator>{author}</dc:creator>
    <dc:language>ko</dc:language>
  </metadata>
  <manifest>{"".join(manifest)}</manifest>
  <spine>{"".join(spine)}</spine>
</package>"""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED
        )
        archive.writestr("META-INF/container.xml", CONTAINER, compress_type=zipfile.ZIP_DEFLATED)
        archive.writestr("OEBPS/content.opf", opf, compress_type=zipfile.ZIP_DEFLATED)
        for name, content in documents:
            archive.writestr(f"OEBPS/text/{name}", content, compress_type=zipfile.ZIP_DEFLATED)
        if nav is not None:
            links = "".join(f'<li><a href="{href}">{label}</a></li>' for href, label in nav)
            archive.writestr(
                "OEBPS/nav.xhtml",
                xhtml(f'<nav epub:type="toc"><ol>{links}</ol></nav>'),
                compress_type=zipfile.ZIP_DEFLATED,
            )
        for name, data in (extra_files or {}).items():
            archive.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
    return buffer.getvalue()


SAMPLE_EPUB_DOCS = [
    ("cover.xhtml", xhtml('<div><img src="cover.jpg" alt="표지"/></div>')),
    (
        "ch1.xhtml",
        xhtml(
            "<h1>1장 · 바람이 바뀌던 날</h1>"
            "<p>섬의 끝에는 오래된 등대가 하나 서 있었다. 하얀 벽은 소금기에 바래 있었다.</p>"
            "<p>등대지기 하람은 매일 해 질 무렵&nbsp;계단을 올랐다.</p>"
            "<hr/>"
            "<p>그날은 바람의 냄새가 달랐다.</p>"
            "<script>alert('x')</script>"
        ),
    ),
    ("ch1-continued.xhtml", xhtml("<p>멀리서 작은 불빛 하나가 깜박였다.</p>")),
    (
        "ch2.xhtml",
        xhtml(
            "<section><h2>2장 · 낮게 뜬 불빛</h2>"
            "<div><p>하람은 손전등을 챙겨 <em>바위길</em>로 내려갔다.</p></div>"
            "<h3>병 속의 편지</h3>"
            "<p>불빛은 유리병 안에서 흔들렸다.<br/>병마개를 열었다.</p></section>"
        ),
    ),
]
