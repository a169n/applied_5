# quakeloc

Earthquake detection and location service for the northern Tien Shan, validated on the open
KNET network near Bishkek, about 190 km WSW of Almaty. Almaty is the regional motivation; the
real-data results are for the Bishkek area.

Built for *Assignment 5: DevOps and CI/CD, Automating Processes for Research Projects*. It
detects P-wave arrivals (STA/LTA), picks onsets (AIC) and locates epicentres with 95 % error
ellipses (Geiger's method), and ships with a Docker image, a Jenkins CI/CD pipeline and a
Kubernetes (Minikube) deployment.

## Quickstart

```sh
make venv                         # Python 3.12 environment (needs uv)
.venv/bin/python -m quakeloc.calibrate --seed 42 --out artifacts/
.venv/bin/pytest                  # all tests, natively (real-data tests use artifacts/)
.venv/bin/uvicorn quakeloc.api:app --port 8000   # then open http://localhost:8000
```

The same steps in the shipped environment, exactly as CI runs them:

```sh
make image-test lint test calibrate science realdata image smoke
```

`docs/RUNBOOK.md` covers Jenkins, Minikube and refreshing the data on macOS.
`docs/design/quakeloc-design.md` is the design specification.

The web client at `/` lists the real earthquakes and maps our location and 95 % ellipse against
USGS. It is one HTML file served by the API, with no build step; `/docs` has the API reference.

## Scope limits

P phase only, one-layer (homogeneous) velocity model of 6.0 km/s, depth fixed at 10 km, 2-D
epicentre, no magnitude estimation. The causal band-pass filter adds a known positive bias of
about 0.07 s to picks and origin times. USGS solutions are used as a reference, not as ground
truth: catalog locations carry several kilometres of uncertainty themselves.

## Real-data results

The snapshot holds **4 events** (M 4.0 to 4.9, 2013 to 2015). The EarthScope archive returned
no KN waveforms for most of the 2005 to 2025 catalog period, so lowering the magnitude limit to
3.5 added no qualifying event. All 4 locate, with RMS 0.11 to 0.27 s and mislocations against
USGS of **2.8, 7.5, 12.2 and 18.3 km**, and origin-time differences of up to 3.5 s.

Four events are a demonstration, not a statistical validation. The 95 % ellipses (semi-major
axes 1.7 to 17 km) reflect pick scatter only: they exclude the one-layer model and the fixed
depth, so the USGS epicentre often lies outside them. The largest mislocation and origin-time
difference occur for the event USGS places deepest (21 km against our fixed 10 km), which
suggests those limitations matter, though it does not prove the cause.

## Data

- **Synthetic:** seeded generator on a fictitious network (`config/network.json`), used by
  tests because the true answer is known exactly.
- **Real snapshot:** `data/real/`, frozen and checksummed. The main pipeline never touches the
  network for data; refreshing is a separate job followed by a reviewed pull request.

Data citations: KNET, Kyrgyz Digital Network, FDSN code `KN`,
[doi:10.7914/SN/KN](https://doi.org/10.7914/SN/KN); USGS Comprehensive Earthquake Catalog
(ComCat), <https://earthquake.usgs.gov/data/comcat/>.

## Possible extensions

Magnitude estimation, depth inversion, S phases, 3-D velocity models, real-time streaming
(SeedLink), additional networks, multi-architecture images, GitHub webhooks through a tunnel.
