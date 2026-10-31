# quakeloc — Design Specification

| | |
|---|---|
| **Status** | Draft for review |
| **Date** | 2026-10-31 |
| **Repository** | https://github.com/a169n/applied_5 (default branch `main`) |
| **Context** | Assignment 5 — *DevOps and CI/CD: Automating Processes for Research Projects* |

## 1. Goal and success criteria

Build a small but genuine piece of research software and wrap it in a complete DevOps
toolchain, so that the assignment can be graded at full marks plus the CD bonus:

| Rubric item | Points | How this project earns it |
|---|---|---|
| Theory report | 30 | 3-page English report; examples drawn from this project (reproducibility, data versioning, scientific tests) |
| Docker | 15 | Multi-stage `Dockerfile` (test / data / runtime targets), non-root, healthcheck, OCI labels, provenance |
| Jenkins CI | 25 | Jenkins-as-code (JCasC + Job DSL), multibranch pipeline that tests every commit, builds, smoke-tests and pushes the image |
| Git & automation | 10 | `main` + feature branches + PRs, Makefile mirroring CI, tagged release, red-build demo branch |
| Practical report | 10 | 1–2 pages with screenshots, links and lessons learned |
| Bonus: CD | +10 | Automatic deploy to Minikube with readiness self-test, smoke Job and automatic rollback |

**Success** = on the student's Mac, one `make jenkins-up` brings up a pre-configured
Jenkins; a push to `main` produces a green pipeline that ends with the new version
running in Minikube; a push of the demo bug branch produces a red pipeline that stops
before any image is built.

All deliverables (code, comments, docs, reports) are in **English**.

## 2. The research problem

Almaty lies at the foot of the northern Tien Shan, one of the most seismically active
intracontinental regions on Earth (1887 Verny M~7.3, 1911 Kemin M~8). Routine
earthquake monitoring answers two questions for every event: *when did the P wave
arrive at each station* and *where was the source*. `quakeloc` implements the classic,
textbook chain:

1. **Detection** — STA/LTA energy ratio trigger (Allen 1978; Withers et al. 1998).
2. **Onset picking** — AIC picker (Maeda 1985) inside a window anchored to the trigger.
3. **Location** — Geiger's method (1912) solved as damped Gauss–Newton
   (Levenberg–Marquardt) for epicentre `(x, y)` and origin time `t0`, with a linearised
   covariance and a 95 % confidence ellipse.

Deliberate scope limits (stated in README and reports): P phase only, 1-layer
(homogeneous) velocity model, depth fixed, 2-D epicentre, no magnitude.

## 3. Data strategy — hybrid (synthetic + real snapshot + live refresh)

| Layer | Source | Used by | Why |
|---|---|---|---|
| **Synthetic** | Seeded generator in `quakeloc.synth` | Unit, property and science tests; `/simulate`, `/demo`, readiness self-test | The true answer is known exactly, so tests can assert physics (exact inversion, calibrated uncertainty) |
| **Real snapshot** | Frozen subset of real earthquakes recorded by the **KNET** network (FDSN code `KN`, northern Tien Shan, open data, DOI 10.7914/SN/KN) with catalog solutions from **USGS** | "Real-data validation" CI stage; `/events` endpoints | Shows the method works on real seismograms; compares our epicentres with an independent catalog |
| **Live APIs** | USGS FDSN Event (`earthquake.usgs.gov/fdsnws/event/1`), EarthScope FDSN Station + Dataselect (`service.earthscope.org/fdsnws/...`) | `quakeloc.data.fetch` CLI and the separate `quakeloc-refresh-data` Jenkins job only | Data acquisition is automated and repeatable, but never makes the main CI flaky |

Key rule: **the main pipeline never touches the network for data.** It runs on
committed, checksummed inputs; refreshing data is a separate, reviewed action
(fetch → diff → commit via PR). This is the data-versioning argument used in the
theory report.

### 3.1 Synthetic generator (`quakeloc.synth`)

- Randomness: `numpy.random.default_rng(SeedSequence(seed))`; child streams via
  `SeedSequence.spawn` (one per station) so adding a station does not change others.
- Network: `config/network.json` — 8 **fictitious** stations on a ~100 km local
  Cartesian grid (labelled fictitious in the file). Stable, independent of real data.
- Travel time (shared with the locator, `quakeloc.model`):
  `t_i = t0 + sqrt((x_i−x)² + (y_i−y)² + (z + h_i)²) / Vp`, `Vp = 6.0 km/s`,
  source depth `z = 10 km`, station elevation `h_i` (0 for the synthetic network).
- Trace: 100 Hz, 60 s; Gaussian noise (σ = 1) plus a **causal** wavelet
  `w(t) = A·sin(2π·5 Hz·t)·exp(−t/0.3 s)` for `t ≥ 0`, 0 before, starting exactly at the
  arrival time, so "onset" is unambiguous (a Ricker wavelet would make it ambiguous).
- Amplitude: `A` chosen so the requested SNR (= `A/σ`) holds at the nearest station,
  decaying as `1/r` to the others; single-trace helpers take an explicit SNR.

### 3.2 Real snapshot (`data/real/`)

Produced by `python -m quakeloc.data.fetch` (ObsPy 1.5.1, only in the `data` image):

1. Station metadata for network `KN` from EarthScope (`level=channel`); network centroid.
2. Events from USGS: M ≥ 4.0, 2005-01-01 … 2025-12-31, epicentre within 100 km of the
   centroid.
3. For each event, vertical channel (`HHZ`, else `BHZ`) waveforms for stations within
   150 km, window `[origin − 60 s, origin + 120 s]`. The 150 km cap keeps the first
   arrival a crustal P (Pg) phase, matching the 1-layer model.
4. Keep events with ≥ 6 stations of complete data and azimuthal gap ≤ 200°; take the
   best ≤ 10 by station count.
5. Write `events.json` (catalog solution, magnitude, USGS id), `stations.json`
   (code, lat, lon, elevation, channel, sampling rate), `waveforms/<event_id>.npz`
   (raw int32/float32 counts, start time, rate), and `MANIFEST.json` (SHA-256 of every
   file, exact query URLs, fetch timestamp, ObsPy/numpy versions, data citation).

Expected size 2–5 MB, committed to Git. If the snapshot is absent (not fetched yet),
the real-data stage is reported as **UNSTABLE/skipped**, never silently green.

### 3.3 Real-data processing (`quakeloc.realdata`)

- Verify every file's SHA-256 against `MANIFEST.json` before use.
- Demean, 5 % cosine taper, **causal** 4-pole Butterworth band-pass 2–8 Hz
  (`scipy.signal.sosfilt`). Causal, so no filter energy leaks before the true onset;
  the small group delay is documented.
- Lat/lon → local km by an equirectangular projection about the network centroid
  (error < 0.5 % within 150 km, far below the location uncertainty).
- Detection + AIC pick per station (same code as synthetic), locate with the station
  elevations included and depth fixed at 10 km (independent of the catalog depth).
- Output per event: our `(lat, lon, t0)`, ellipse, RMS, picks, **mislocation vs USGS
  (km)** and Δt0. The USGS solution is treated as a reference, *not* ground truth
  (teleseismic catalog locations themselves carry several-km uncertainty).

## 4. Algorithms and numerical contracts

| Module | Contract |
|---|---|
| `detect.sta_lta` | Classic energy STA/LTA (STA 0.5 s, LTA 10 s, trailing windows) vectorised with cumulative sums; ratio = 0 during LTA warm-up. `detect.sta_lta_naive` (double loop) exists only as a test oracle. Trigger on/off with hysteresis (`on` = calibrated, `off` = 1.5). |
| `pick.aic_pick` | `AIC(k) = k·ln var(x[:k]) + (N−k−1)·ln var(x[k+1:])` on `[trigger − 3 s, trigger + 1 s]`; returns the integer sample of the global minimum and its time. |
| `locate.locate` | Unknowns `(x, y, t0)`; start at the earliest-arriving station, `t0` = earliest pick − its travel time. LM with damping λ (×10 on rejected step, ÷10 on accepted), stop when step < 1e-6 km or 50 iterations. |
| Covariance | `C = s²(GᵀG)⁻¹`. If the pick σ is **known**, `s = σ` and the 95 % ellipse uses the χ²₂ quantile `−2 ln 0.05 = 5.991`. If σ is **estimated** from residuals (`ν = n − 3` dof), the ellipse uses `2·F₂,ν(0.95)` with the closed form `F₂,ν(p) = (ν/2)·((1−p)^(−2/ν) − 1)` (e.g. ν = 5 → 2 × 5.786). No scipy needed for either quantile. |
| Guards | `< 4` picks, near-collinear stations (smallest/largest singular value of centred station coordinates < 0.05), or non-convergence raise a typed `LocationError` → HTTP 422 with a clear message, never a silent wrong answer. |

### 4.1 Calibration build step (`python -m quakeloc.calibrate --seed 42 --out artifacts/`)

Seeded benchmark: 150 synthetic events + 150 noise-only windows. Sweep the trigger
threshold, choose the best F1 subject to a false-alarm rate ≤ 1 %. Writes
`detector.json` (threshold, precision, recall, pick-error median/MAD, mean location
error) and `manifest.json` (git SHA, seed, numpy version, SHA-256 of outputs). These are
**build artifacts**: archived by Jenkins and baked into the image, never committed.

### 4.2 Experiment (`python -m quakeloc.experiment`)

SNR sweep (fixed seeds): recall, pick error and location error vs SNR → `snr_sweep.csv`,
used as a figure in the practical report.

## 5. Service (FastAPI)

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness only |
| `GET /ready` | Readiness: `detector.json` loaded **and** its hash matches `manifest.json` **and** a built-in canned synthetic event is located within 0.5 km. Kubernetes never routes traffic to a pod whose maths is broken. |
| `GET /version` | Git SHA, build number, package/numpy versions, artifact hash, snapshot hash |
| `POST /simulate` | `{seed, x_km, y_km, snr}` → synthetic multi-station event (size-capped) |
| `POST /pick` | `{samples[], fs_hz}` → triggers + AIC picks (≤ 200 k samples) |
| `POST /locate` | `{picks:[{station, t}], sigma_s?}` → `x_km, y_km, t0, rms_s, iterations, cond, ellipse{a_km, b_km, azimuth_deg}`; 422 on guards |
| `GET /demo` | Full synthetic chain for seed 42: truth vs estimate, error km (used by smoke tests) |
| `GET /events` | Real snapshot events (id, time, magnitude, USGS location) |
| `GET /events/{id}/locate` | Run the real-data chain on one snapshot event; our solution vs USGS, mislocation km |

Interactive docs at `/docs` (Swagger UI) — useful for report screenshots.

## 6. Repository layout

```
.
├── CLAUDE.md                     # handoff/context for Claude Code (cloud → local)
├── README.md                     # quickstart, badges, limitations, data citation
├── Makefile                      # every CI stage runnable locally
├── Dockerfile  .dockerignore
├── Jenkinsfile                   # main CI/CD pipeline (multibranch)
├── pyproject.toml                # package, ruff, pytest (markers: science, realdata)
├── requirements.txt              # runtime, exact pins (numpy, scipy, fastapi, uvicorn, pydantic)
├── requirements-dev.txt          # + pytest, pytest-cov, hypothesis, httpx, ruff
├── requirements-data.txt         # + obspy==1.5.1 (fetch tool only)
├── config/network.json           # fictitious synthetic network
├── data/real/                    # committed real snapshot + MANIFEST.json
├── src/quakeloc/
│   ├── model.py  synth.py  detect.py  pick.py  locate.py  stats.py
│   ├── pipeline.py               # traces → picks → location (shared by API, demo, real data)
│   ├── calibrate.py  experiment.py
│   ├── realdata.py               # snapshot verification + processing
│   ├── data/fetch.py             # ObsPy-based downloader (imported only in the data image)
│   ├── schemas.py  api.py  smoke.py
├── tests/                        # unit / property / science / realdata / api / golden
├── k8s/                          # namespace, deployment, service, smoke-job
├── jenkins/
│   ├── Dockerfile                # jenkins/jenkins:lts-jdk17 + docker CLI + kubectl
│   ├── plugins.txt
│   ├── casc.yaml                 # JCasC: admin user, credentials, jobs (Job DSL)
│   ├── docker-compose.yml  up.sh  make-kubeconfig.sh  .env.example
│   └── Jenkinsfile.refresh-data  # parameterised live-data refresh job
└── docs/
    ├── design/quakeloc-design.md # this file
    ├── RUNBOOK.md                # step-by-step for macOS
    └── reports/                  # theory + practical report sources, DOCX/PDF, figures
```

## 7. Docker

Multi-stage `Dockerfile` (base `python:3.12-slim`, multi-arch so it builds natively on
Apple Silicon and Intel):

| Target | Content |
|---|---|
| `builder` | Build wheels for exact-pinned runtime deps + the package; run `calibrate --seed 42` → `/artifacts` |
| `test` | `FROM builder` + dev deps + `tests/` + `data/real/`; default command runs pytest. CI runs lint and tests **inside this image**, i.e. in exactly the shipped environment |
| `data` | Runtime deps + `requirements-data.txt` (ObsPy); entrypoint `python -m quakeloc.data.fetch` |
| `runtime` | Clean `python:3.12-slim`, wheels installed `--no-index`, artifacts + config + real snapshot copied in, non-root uid 10001, `PYTHONDONTWRITEBYTECODE=1`, `OPENBLAS_NUM_THREADS=1`, `HEALTHCHECK` via `python -c urllib…/health`, OCI labels (`revision`, `source`, `created`), `EXPOSE 8000`, `CMD uvicorn quakeloc.api:app` |

Expected runtime image size ≈ 250–300 MB (numpy + scipy dominate).

## 8. CI/CD with Jenkins

### 8.1 Jenkins as code (runs on the Mac in Docker Desktop)

- `jenkins/Dockerfile`: `jenkins/jenkins:lts-jdk17` + Docker CLI (+ buildx) + `kubectl`
  (architecture-aware download) + plugins from `plugins.txt` (configuration-as-code,
  job-dsl, workflow-aggregator, git, credentials-binding, junit, coverage, timestamper,
  ws-cleanup, pipeline-stage-view, pipeline-graph-view).
- `casc.yaml` (JCasC): skips the setup wizard, creates the admin user from `.env`,
  creates the `dockerhub` username/token credential from `.env`, and defines two jobs
  with Job DSL:
  - **`quakeloc`** — multibranch pipeline on `https://github.com/a169n/applied_5.git`
    (public, no token needed), branch scan every 2 minutes ⇒ every new commit on any
    branch is built. (A laptop cannot receive GitHub webhooks without a tunnel; polling
    is the documented substitute.)
  - **`quakeloc-refresh-data`** — parameterised pipeline from `jenkins/Jenkinsfile.refresh-data`.
- `docker-compose.yml`: port 8080, `jenkins_home` volume, `/var/run/docker.sock`
  mounted (Jenkins drives the host Docker; container runs as root for socket access —
  acceptable for a local single-user setup, stated in the report), `.kube/` mounted
  read-only.
- `up.sh`: builds/starts Jenkins; if a `minikube` Docker network exists, connects the
  Jenkins container to it and regenerates the kubeconfig (`make-kubeconfig.sh`:
  flattened minikube context with the server rewritten to `https://$(minikube ip):8443`).

The pipeline never bind-mounts the workspace into containers (a path mismatch with the
host daemon would break it); build context is streamed by `docker build`, reports are
copied out with `docker cp`.

### 8.2 Main pipeline (`Jenkinsfile`, declarative)

Options: timestamps, build discarder, `disableConcurrentBuilds`.

| # | Stage | Branches | What it does |
|---|---|---|---|
| 1 | Checkout | all | `checkout scm`; `GIT_SHA`, `SHORT_SHA` |
| 2 | Build test image | all | `docker build --target test -t quakeloc-test:$SHORT_SHA .` |
| 3 | Lint | all | `ruff check` + `ruff format --check` in the test image |
| 4 | Unit & property tests | all | `pytest -m "not science and not realdata"` with JUnit XML + coverage (fail under 80 %) |
| 5 | Scientific validation | all | Calibrate (seed 42) **twice in separate containers** and require byte-identical outputs (reproducibility gate); `pytest -m science` (coverage of ellipses, golden regression, recall ≥ 0.95); SNR experiment; archive `detector.json`, `manifest.json`, `snr_sweep.csv` |
| 6 | Real-data validation | all | Verify snapshot checksums; relocate all snapshot events; `pytest -m realdata` (gates in `config/realdata_gates.json`); archive `relocation.csv`. Missing snapshot ⇒ stage UNSTABLE |
| 7 | Build runtime image | all | `docker build --target runtime --build-arg GIT_SHA … -t $IMAGE:$SHORT_SHA -t $IMAGE:latest .` (reuses layer cache from stage 2) |
| 8 | Container smoke test | all | Run the image, then a second container in its network namespace runs `python -m quakeloc.smoke` (waits for `/ready`, checks `/version` SHA, `/demo` error < 1 km, one `/events/{id}/locate`) |
| 9 | Push to Docker Hub | `main` | `docker login --password-stdin` with the `dockerhub` credential; push `:$SHORT_SHA` and `:latest` |
| 10 | Deploy to Minikube | `main` | Render manifests with the exact image tag; `kubectl apply`; `rollout status --timeout=180s`; run the smoke `Job`, wait for completion; on any failure `kubectl rollout undo` and fail the build |

`post`: JUnit + coverage publishing, artifacts with fingerprints, remove smoke
containers, prune the per-build test image, `cleanWs()`.

**Red-build demo:** branch `demo/broken-locator` flips the sign of one Jacobian term;
Jenkins goes red at stage 4 and never builds or ships an image (screenshot for the
report). It is never merged.

### 8.3 Data refresh job (`jenkins/Jenkinsfile.refresh-data`)

Parameters `START`, `END`, `MIN_MAG`, `MAX_EVENTS`. Builds the `data` target, runs the
fetcher into a fresh directory, prints a diff against the committed `MANIFEST.json`
(events added/removed, changed hashes), archives the new snapshot as a tarball. It does
**not** push; a human commits the new snapshot through a PR, where the main pipeline
re-validates it.

## 9. Kubernetes (Minikube, docker driver)

- `namespace.yaml` — `quakeloc`.
- `deployment.yaml` — 2 replicas, `RollingUpdate` (`maxUnavailable: 0`),
  `readinessProbe` → `/ready`, `livenessProbe` → `/health`, requests 100m/128Mi,
  limits 500m/384Mi, `runAsNonRoot`, `readOnlyRootFilesystem`, image placeholder
  `__IMAGE__` rendered by the pipeline.
- `service.yaml` — NodePort 30080 → 8000 (`minikube service quakeloc -n quakeloc --url` on macOS).
- `smoke-job.yaml` — same image, `python -m quakeloc.smoke --url http://quakeloc.quakeloc.svc:8000`, `backoffLimit: 0`, `ttlSecondsAfterFinished: 600`.

The image reaches Minikube via Docker Hub (public repository). Built on the Mac, the
image architecture matches the Minikube node (arm64 on Apple Silicon, amd64 on Intel).

## 10. Testing strategy

| Group | Marker | Examples |
|---|---|---|
| Model | – | Analytic travel time (60 km offset, 10 km depth → `sqrt(60²+10²)/6` s to 1e-12); elevation term |
| Detection | – | Vectorised STA/LTA = naive oracle (rtol 1e-9); amplitude-scale invariance; noise-only mean ratio ≈ 1 (±0.05) |
| Picking | – | Shift equivariance (Hypothesis, derandomised CI profile): prepending k samples shifts the pick by exactly k; p95 pick error ≤ 0.03 s and max ≤ 0.1 s at SNR ≥ 10 over 200 seeded events |
| Location | – | Noise-free exact inversion (1e-6 km, 1e-6 s, ≤ 10 iterations) inside and at the edge of the network; constant pick shift moves only `t0`; guards (3 picks, collinear) raise |
| Statistics | – | Closed-form χ²₂ and F₂,ν quantiles vs tabulated values |
| Science | `science` | 95 % ellipse coverage in [0.90, 0.99] over 200 trials, both known-σ and estimated-σ modes; calibration recall ≥ 0.95 at FAR ≤ 1 %; golden seed-42 picks exact, locations rtol 1e-6 |
| Real data | `realdata` | Snapshot checksums; every event locates without error; median mislocation vs USGS and max RMS within `config/realdata_gates.json` (gates frozen after the first real run, with the rationale recorded) |
| API | – | TestClient: schemas, 422 paths, `/ready` 503 when the artifact hash is tampered with, `/version` content |
| Determinism | – | Same seed ⇒ identical arrays; different seeds ⇒ different arrays |

Goldens are regenerated only through `make golden` in a reviewed commit. numpy is pinned
exactly because only bit-generator streams are guaranteed stable across versions (NEP 19).

## 11. Reports

- **Theory report** (`docs/reports/theory/`): exactly 3 pages, 12 pt, 1.5 spacing, compact
  header block (no separate title page), sections: (1) DevOps goals/principles/benefits,
  (2) CI/CD overview, (3) DevOps tools in research environments (reproducibility crisis,
  environment drift, data versioning), (4) Docker / Jenkins / Kubernetes in scientific and
  engineering projects (including this one), (5) conclusion; IEEE-style references.
  Built from Markdown by a script into DOCX, converted to PDF with LibreOffice, page
  count verified.
- **Practical report** (`docs/reports/practical/`): 1–2 pages, steps, screenshots,
  repository/Jenkinsfile links, difficulties, conclusions — finalised after the local run.
- Title data (name, group, university, course, instructor) supplied by the student.

## 12. Environments and verification split

| Check | Cloud session | Student's Mac |
|---|---|---|
| Lint, unit, property, science tests | ✅ | ✅ |
| Docker build (all targets) + container smoke | ✅ (needs proxy CA workaround, cloud-only) | ✅ |
| Real-data fetch from USGS/EarthScope | ❌ blocked by network policy unless the domains are allowed | ✅ |
| Real-data validation on a committed snapshot | ✅ once the snapshot exists | ✅ |
| Jenkins boot via JCasC + pipeline run | Attempt (depends on plugin-site access) | ✅ |
| Minikube deploy | ❌ | ✅ |
| Screenshots | ❌ | ✅ |

## 13. Git workflow

`main` is the default branch and always green. Work happens on feature branches
(currently `claude/cool-curie-5vimra`), merged via pull requests after the pipeline is
green. Only `main` pushes images and deploys. Release tag `v1.0.0` marks the submitted
version.

## 14. Out of scope

Magnitude estimation, depth inversion, S phases, 3-D velocity models, real-time
streaming (SeedLink), multi-architecture image publishing, GitHub webhooks via tunnels,
Helm charts. Possible extensions are listed in the README.

## 15. Risks and mitigations

| Risk | Mitigation |
|---|---|
| KNET data gaps for chosen years | Fetcher selects only events with ≥ 6 complete stations; can widen years or add open networks (e.g. `KR`) via parameters |
| Real mislocations larger than expected (1-layer model, Pg/Pn crossover) | Distance cap 150 km, elevation term, gates frozen from the first honest run; limitations discussed in reports |
| LM divergence from a poor start | Earliest-station start + damping + iteration cap + typed error; tested |
| Floating-point differences between the cloud CPU and the Mac | Integer picks compared exactly, floats with rtol; byte-identity only required within one machine |
| Jenkins ↔ Minikube networking on macOS | Jenkins joins the `minikube` Docker network; kubeconfig rewritten to the node IP; scripted in `up.sh` |
| 8 GB RAM laptops | Minikube `--memory=3g`, Jenkins heap 1 GB, documented in RUNBOOK |
