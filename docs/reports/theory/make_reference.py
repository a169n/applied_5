"""Create reference.docx: A4, Times New Roman. Args: out [size_pt spacing margin_cm]."""

import subprocess
import sys

from docx import Document
from docx.shared import Cm, Pt, RGBColor

OUT = sys.argv[1]
SIZE, SPACING, MARGIN = (*map(float, sys.argv[2:5]), 12, 1.5, 2.5)[:3]  # defaults: theory report
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
    setattr(section, side, Cm(MARGIN))


def style(name, bold=False, italic=False, spacing=SPACING, before=0, after=0):
    s = doc.styles[name]
    s.font.name, s.font.size = "Times New Roman", Pt(SIZE)
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
for name in ("Source Code", "Verbatim Char"):  # code needs a font every machine has
    if name in [s.name for s in doc.styles]:
        doc.styles[name].font.name, doc.styles[name].font.size = "Courier New", Pt(SIZE - 1.5)
style("Image Caption", after=6)
style("Captioned Figure", before=3)
doc.save(OUT)
