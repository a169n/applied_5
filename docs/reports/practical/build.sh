#!/usr/bin/env bash
# Practical report: Markdown -> DOCX -> PDF. Fails unless the PDF has 1 or 2 pages.
set -euo pipefail
cd "$(dirname "$0")"
[ -f reference.docx ] || uv run --no-project --with python-docx python ../theory/make_reference.py reference.docx 10.5 1.0 2.0
pandoc practical.md --reference-doc=reference.docx -o practical.docx
# Pandoc sizes table columns for a 14 cm page; Word could clip images wider than that grid.
python3 - <<'PY'
import re, shutil, zipfile
shutil.move("practical.docx", "tmp.docx")
with zipfile.ZipFile("tmp.docx") as old, zipfile.ZipFile("practical.docx", "w", zipfile.ZIP_DEFLATED) as new:
    for item in old.infolist():
        data = old.read(item.filename)
        if item.filename == "word/document.xml":
            data = re.sub(rb'<w:gridCol w:w="3960" ?/>', b'<w:gridCol w:w="4819"/>', data)
        new.writestr(item, data)
PY
rm tmp.docx
soffice --headless --convert-to pdf practical.docx > /dev/null
pages=$(pdfinfo practical.pdf | awk '/^Pages:/ {print $2}')
echo "pages=$pages"
[ "$pages" -le 2 ]
