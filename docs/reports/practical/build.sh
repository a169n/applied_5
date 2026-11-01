#!/usr/bin/env bash
# Practical report: Markdown -> DOCX -> PDF. Fails unless the PDF has 1 or 2 pages.
set -euo pipefail
cd "$(dirname "$0")"
[ -f reference.docx ] || uv run --no-project --with python-docx python ../theory/make_reference.py reference.docx 10.5 1.0 2.0
pandoc practical.md --reference-doc=reference.docx -o practical.docx
soffice --headless --convert-to pdf practical.docx > /dev/null
pages=$(pdfinfo practical.pdf | awk '/^Pages:/ {print $2}')
echo "pages=$pages"
[ "$pages" -le 2 ]
