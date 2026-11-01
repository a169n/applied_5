#!/usr/bin/env bash
# Theory report: Markdown -> DOCX -> PDF. Fails unless the PDF has exactly 3 pages.
set -euo pipefail
cd "$(dirname "$0")"
[ -f reference.docx ] || uv run --no-project --with python-docx python make_reference.py reference.docx
pandoc theory.md --reference-doc=reference.docx -o theory.docx
soffice --headless --convert-to pdf theory.docx > /dev/null
pages=$(pdfinfo theory.pdf | awk '/^Pages:/ {print $2}')
echo "pages=$pages"
[ "$pages" -eq 3 ]
