# Real-data snapshot

A frozen subset of real earthquakes recorded by the open **KNET** network (FDSN code `KN`,
DOI 10.7914/SN/KN, around Bishkek, about 190 km WSW of Almaty), with catalog solutions from
USGS ComCat. Produced by `make data` (`python -m quakeloc.data.fetch`).

The snapshot is present if and only if `MANIFEST.json` exists here. The manifest records
the SHA-256 of every file, the exact query URLs, parameters and data citations. Refreshing
is a reviewed action: fetch, relocate, compare, then commit through a pull request.
