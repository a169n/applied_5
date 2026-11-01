"""Create reference.docx: A4, 2.5 cm margins, Times New Roman 12 pt, 1.5 line spacing."""

import subprocess
import sys

from docx import Document
from docx.shared import Cm, Pt, RGBColor

OUT = sys.argv[1]
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
with open(OUT, "wb") as f:
    f.write(
        subprocess.run(
            ["pandoc", "--print-default-data-file", "reference.docx"],
            check=True,
            capture_output=True,
        ).stdout
    )

doc = Document(OUT)
section = doc.sections[0]
section.page_width, section.page_height = Cm(21.0), Cm(29.7)
for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
    setattr(section, side, Cm(2.5))


def style(name, bold=False, italic=False, spacing=1.5, before=0, after=0):
    s = doc.styles[name]
    s.font.name, s.font.size = "Times New Roman", Pt(12)
    s.font.bold, s.font.italic = bold, italic
    s.font.color.rgb = RGBColor(0, 0, 0)
    rpr = s.element.get_or_add_rPr()
    fonts = rpr.find(f"{W}rFonts")
    for attr in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme", "cstheme"):
        fonts.attrib.pop(
            f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}{attr}", None
        )
    for attr in ("ascii", "hAnsi", "eastAsia", "cs"):
        fonts.set(
            f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}{attr}",
            "Times New Roman",
        )
    p = s.paragraph_format
    p.line_spacing, p.space_before, p.space_after = spacing, Pt(before), Pt(after)


for name in ("Normal", "Body Text", "First Paragraph", "Compact"):
    style(name)
style("Title", bold=True, spacing=1.0, after=4)
style("Author", spacing=1.0)
style("Heading 1", bold=True, before=6)
doc.save(OUT)
