# quakeloc — Design Specification

| | |
|---|---|
| **Status** | Rev 2 — approved by the student on 2026-11-01 |
| **Date** | 2026-10-31 |
| **Repository** | https://github.com/a169n/applied_5 (default branch `main`) |
| **Context** | Assignment 5 — *DevOps and CI/CD: Automating Processes for Research Projects* |
| **Revision history** | rev 1: initial draft. rev 2: incorporates an independent multi-reviewer audit (34 verified findings: numerical contracts, detector calibration for filtered data, Docker/Jenkins/Minikube details on macOS, real-data bootstrap). |

## 1. Goal and success criteria

Build a small but genuine piece of research software and wrap it in a complete DevOps
toolchain, so that the assignment can be graded at full marks plus the CD bonus:

| Rubric item | Points | How this project earns it |
|---|---|---|
| Theory report | 30 | 3-page English report; examples drawn from this project (reproducibility, data versioning, scientific tests) |
| Docker | 15 | Multi-stage `Dockerfile` (`deps` / `test` / `artifacts` / `data` / `runtime` targets), non-root, healthcheck, OCI labels, provenance |
| Jenkins CI | 25 | Jenkins-as-code (JCasC + Job DSL), multibranch pipeline that tests every pushed commit, builds, smoke-tests and pushes the image |
| Git & automation | 10 | `main` + feature branches + PRs, Makefile mirroring CI, tagged release, red-build demo branch |
| Practical report | 10 | 1–2 pages with screenshots, links and lessons learned |
| Bonus: CD | +10 | Automatic deploy to Minikube with readiness self-test, smoke Job and automatic rollback |

**Success** = on the student's Mac, `minikube start` followed by `make jenkins-up` brings
up a pre-configured Jenkins; a push to `main` produces a green pipeline that ends with the
new version running in Minikube; a push of the demo bug branch produces a red pipeline that
fails at the unit-test stage, **before the runtime image is built or pushed**.

All deliverables (code, comments, docs, reports) are in **English**.

## 2. The research problem

The northern Tien Shan — the mountain belt between Bishkek and Almaty — is one of the
most seismically active intracontinental regions on Earth (1887 Verny M~7.3, 1911 Kemin
M~8, both damaging Almaty). Routine earthquake monitoring answers two questions for
every event: *when did the P wave arrive at each station* and *where was the source*.
`quakeloc` implements the classic, textbook chain:

1. **Detection** — STA/LTA energy-ratio trigger (Allen 1978; Withers et al. 1998).
2. **Onset picking** — AIC picker (Maeda 1985) inside a window anchored to the trigger.
3. **Location** — Geiger's method (1912) solved as damped Gauss–Newton
   (Levenberg–Marquardt) for epicentre `(x, y)` and origin time `t0`, with a linearised
   covariance and a 95 % confidence ellipse.

Where the real data comes from: the open **KNET** network (FDSN code `KN`) sits in the
Chu valley / Kyrgyz range around Bishkek, about **190 km WSW of Almaty**. The real-data
validation events are therefore in the northern Tien Shan near Bishkek, not in Almaty
itself; Almaty is the regional motivation, and reports say so explicitly.

Deliberate scope limits (stated in README and reports): P phase only, 1-layer
(homogeneous) velocity model, depth fixed, 2-D epicentre, no magnitude.

## 3. Data strategy — hybrid (synthetic + real snapshot + live refresh)

| Layer | Source | Used by | Why |
|---|---|---|---|
| **Synthetic** | Seeded generator `quakeloc.synth` | Unit, property and science tests; `/simulate`, `/demo`, readiness self-test | The true answer is known exactly, so tests can assert physics (exact inversion, calibrated uncertainty) |
| **Real snapshot** | Frozen subset of real earthquakes recorded by **KNET** (`KN`, open data, DOI 10.7914/SN/KN) with catalog solutions from **USGS ComCat** | "Real-data validation" CI stage; `/events` endpoints | Shows the method works on real seismograms; compares our epicentres with an independent catalog |
| **Live APIs** | USGS FDSN Event (`earthquake.usgs.gov/fdsnws/event/1`), EarthScope FDSN Station + Dataselect (`service.earthscope.org/fdsnws/...`) | `quakeloc.data.fetch` CLI (`make data`) and the separate `quakeloc-refresh-data` Jenkins job only | Data acquisition is automated and repeatable, but never makes the main CI flaky |

Key rule: **the main pipeline never touches the network for data.** It runs on
committed, checksummed inputs; refreshing data is a separate, reviewed action
(fetch → relocate → diff → commit via PR). This is the data-versioning argument used in
the theory report.

### 3.1 Synthetic generator (`quakeloc.synth`)

- Randomness: `numpy.random.default_rng(SeedSequence(seed))`; child streams via
  `SeedSequence.spawn` (one per station) so adding a station does not change others.
- Network: `config/network.json` — 8 **fictitious** stations on a ~100 km local
  Cartesian grid (labelled fictitious in the file), elevation 0. Independent of real data.
- Travel time (shared with the locator, `quakeloc.model`):
  `t_i = t0 + sqrt((x_i−x)² + (y_i−y)² + (z + h_i)²) / Vp`, `Vp = 6.0 km/s`,
  source depth `z = 10 km` below sea level, station elevation `h_i` **in km** above sea
  level (so the vertical leg is `z + h_i`).
- Trace: 100 Hz, 60 s, **starting at `t0 − 20 s`** (so the earliest possible arrival is at
  ≥ 21.7 s, after the 10 s LTA warm-up and the 3 s AIC pre-window). Gaussian noise
  (σ = 1, white) plus a **causal** wavelet `w(t) = A·sin(2π·5 Hz·t)·exp(−t/0.3 s)` for
  `t ≥ 0`, 0 before, starting exactly at the (continuous, off-grid) arrival time.
  Generator asserts every arrival lies in `[13 s, 58 s]` of the trace.
- SNR definitions (SNR = `A/σ`):
  - **single-trace helper** `synth.trace(snr, onset_s, seed)` — explicit SNR; used by all
    picking/detection tests;
  - **multi-station event** `synth.event(x, y, seed, min_snr)` — amplitude decays as `1/r`
    and is scaled so the *weakest* station has `min_snr`; per-station SNRs are returned.

### 3.2 Real snapshot (`data/real/`)

`data/real/README.md` is always committed (explains the snapshot), so the directory
exists even before any data is fetched. **"Snapshot present" ⇔ `data/real/MANIFEST.json`
exists.**

Produced by `python -m quakeloc.data.fetch` (ObsPy 1.5.1; only in the `data` image) with
parameters from `config/realdata.json`:

1. Pinned selection/projection **origin** `(42.58 °N, 74.78 °E)` (≈ KNET centre),
   recorded in the manifest. Station metadata for network `KN` from EarthScope at
   `level=channel`, epoch-aware (coordinates valid at each event's time).
2. Events from USGS: M ≥ 4.0, 2005-01-01 … 2025-12-31, epicentre ≤ 100 km from the origin.
3. For each event, vertical channel (`HHZ`, else `BHZ`) for stations ≤ 150 km from the
   epicentre, window `[origin − 60 s, origin + 120 s]`. The 150 km cap keeps the first
   arrival a crustal P (Pg) phase in this thick-crust region, matching the 1-layer model.
4. Keep events with ≥ 6 stations of complete data and azimuthal gap ≤ 200°. Rank
   deterministically: station count desc, azimuthal gap asc, magnitude desc, USGS id asc;
   keep the first `MAX_EVENTS` (default 10).
5. Write:
   - `events.json` — USGS id, origin time, lat, lon, depth, magnitude, and per station:
     network, station, location code, channel, sampling rate, lat, lon, `elevation_m`
     (epoch-correct for that event);
   - `waveforms/<event_id>.npz` — raw counts (int32/float32) per station + start times;
   - `MANIFEST.json` — SHA-256 of every file, exact query URLs, parameters, origin, fetch
     timestamp, ObsPy/numpy versions, data citations (KN DOI, USGS ComCat).

Expected size 2–5 MB, committed to Git.

### 3.3 Real-data processing (`quakeloc.realdata`)

- Verify every file's SHA-256 against `MANIFEST.json` before use.
- Preprocessing (shared function `pipeline.preprocess_real`): demean → 1 s cosine taper at
  both ends → **causal band-pass**
  `sos = scipy.signal.butter(2, [2, 8], btype="bandpass", fs=fs, output="sos")`
  ("4 poles = 2 per corner") applied with `scipy.signal.sosfilt`. Causal, so no filter
  energy appears before the true onset; the measured group delay (≈ 0.07 s at 5 Hz) is a
  known positive pick/t0 bias, stated in the results.
- STA/LTA output is forced to 0 for the first 15 s (taper + filter settling + LTA warm-up).
- Detection uses the **real-data threshold** `on_realdata` from `detector.json` (§4.1),
  not the white-noise one. Band-limited noise has far larger STA/LTA fluctuations
  (measured: FAR 1 % needs ≈ 3.9 vs ≈ 2.0 for white noise).
- Coordinates: spherical **azimuthal-equidistant** projection about the pinned origin
  (numpy-only, ~10 lines + inverse; error < 0.2 % for KNET event–station pairs).
  Mislocation vs USGS is computed with the haversine great-circle distance.
- `elevation_m` is converted to km exactly once, in `realdata.py`.
- Locate with depth fixed at 10 km (independent of the catalog depth). Outlier handling:
  while ≥ 5 picks remain, drop the pick with the largest |residual| if it exceeds 1.5 s
  and relocate; rejected picks are listed in the output.
- Output per event (`relocation.csv`): our `(lat, lon, t0)`, ellipse, RMS, picks used and
  rejected, **mislocation vs USGS (km)**, Δt0, and per trace the number of false triggers
  on the pre-event segment `[start + 20 s, origin − 5 s]` (an empirical FAR check). The USGS
  solution is a reference, *not* ground truth (catalog locations themselves carry
  several-km uncertainty).

## 4. Algorithms and numerical contracts

| Module | Contract |
|---|---|
| `detect.sta_lta` | Classic energy STA/LTA (STA 0.5 s, LTA 10 s, trailing windows) vectorised with cumulative sums. Returns the ratio array and `valid_from = n_lta − 1` (ratio is 0 before it). All-zero/flat input (LTA = 0) raises `SignalError`. `detect.sta_lta_naive` (double loop) exists only as a test oracle. |
| `detect.triggers` | On/off hysteresis (`on` = calibrated threshold, `off` = 1.5) → list of episodes `(on_idx, off_idx, peak_ratio)`. |
| Trigger selection | **One event per window:** the AIC window is anchored on the on-time of the *earliest* episode whose peak is ≥ 0.5 × the global maximum ratio (prefers P over a later, stronger S). No episode ⇒ "no detection". |
| `pick.aic_pick` | Window `w = x[trigger − 3 s : trigger + 1 s]` clipped to the trace, length `N`. `AIC(k) = k·ln var(w[:k]) + (N−k)·ln var(w[k:])` for `k ∈ [m, N−m]`, `m = 10` samples. Pick = `window_start + argmin k` (first sample of the signal segment). Window shorter than `2m` or any variance ≤ 0 ⇒ `SignalError`. Expected bias: ≈ +0.5…+1 sample late. |
| `locate.locate` | Unknowns `(x, y, t0)`; start at the earliest-arriving station, `t0` = earliest pick − its travel time. LM with damping λ (×10 on a rejected step, ÷10 on an accepted one), stop when the proposed (damped) step < 1e-6 km or after 50 iterations. **Success is declared only if** the undamped Gauss–Newton step `lstsq(G, r)` at the final point is < 1e-3 km and λ < 1e6; otherwise `LocationError("stalled")`. The Jacobian is a separate function `_jacobian` (injectable for tests). |
| Covariance | `C = s²(GᵀG)⁻¹`. **Known σ:** `s = σ`, 95 % ellipse uses `k² = χ²₂(0.95) = −2 ln 0.05 = 5.991`. **Estimated σ:** `s² = Σr²/ν`, `ν = n − 3`, `k² = 2·F₂,ν(0.95)` with the closed form `F₂,ν(p) = (ν/2)·((1−p)^(−2/ν) − 1)` (e.g. ν = 5 → 2 × 5.786). Semi-axes `= sqrt(k²·eig(C_xy))`. No scipy needed. |
| Guards | `< 4` picks, near-collinear stations (smallest/largest singular value of centred station coordinates < 0.05), stall or non-convergence ⇒ typed `LocationError` → HTTP 422 with a clear message, never a silent wrong answer. |

### 4.1 Calibration (`python -m quakeloc.calibrate --seed 42 --out artifacts/`)

Seeded benchmark with two calibrations:

- **`on_raw`** (synthetic, white noise): 150 single-station traces with per-trace SNR
  ~ U[3, 20] and 150 noise-only 60 s windows. Recall is per trace: a trigger whose on-time
  lies in `[onset − 0.2 s, onset + 1 s]`. Sweep the threshold; choose the best F1 subject to
  FAR ≤ 1 % (fraction of noise windows with any trigger). Expected ≈ 2.0.
- **`on_realdata`**: FAR ≤ 1 % per 50 s window on seeded Gaussian noise passed through
  *exactly* `pipeline.preprocess_real` (transient discarded). Expected ≈ 3.9.

A benchmark event that raises `LocationError` is **counted** (reported in the output), not
fatal. Writes `detector.json` (both thresholds, precision, recall overall and for SNR ≥ 5,
pick-error median/MAD, mean location error, LocationError count) and `manifest.json`
(seed, numpy version, SHA-256 of `src/` and `config/` inputs, SHA-256 of outputs).
**No git SHA in the artifacts**, so they are a pure function of their inputs (identical
in the test image, in the runtime image and across reruns). They are build artifacts:
archived by Jenkins and baked into the image, never committed.

### 4.2 Experiment (`python -m quakeloc.experiment`)

SNR sweep over fixed seeds: recall, pick error, location error and *waveform-chain*
ellipse coverage vs SNR → `snr_sweep.csv` (reported, not gated); used as a figure in the
practical report.

## 5. Service (FastAPI, `uvicorn --host 0.0.0.0 --port 8000`)

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness only |
| `GET /ready` | Readiness: `detector.json` loaded **and** its hash matches `manifest.json` **and** a built-in canned synthetic event (epicentre near the network centre, every station SNR ≥ 10) is located within 0.5 km. Independent of the real snapshot. Kubernetes never routes traffic to a pod whose maths is broken. |
| `GET /version` | Git SHA, build number, package/numpy versions, artifact hash, snapshot hash (`null` if no snapshot) |
| `POST /simulate` | `{seed, x_km, y_km, min_snr}` → synthetic multi-station event; `x_km, y_km` validated so all arrivals fall in `[13 s, 58 s]`; size-capped output |
| `POST /pick` | `{samples[], fs_hz}` → trigger episodes + AIC pick (≤ 200 k samples) |
| `POST /locate` | `{picks:[{station, t}], sigma_s?}` → `x_km, y_km, t0, rms_s, iterations, cond, ellipse{a_km, b_km, azimuth_deg}`; 422 on guards |
| `GET /demo` | Full synthetic chain for seed 42: truth vs estimate, error km (used by smoke tests) |
| `GET /events` | Real snapshot events (id, time, magnitude, USGS location); `[]` when no snapshot |
| `GET /events/{id}/locate` | Real-data chain on one snapshot event: our solution vs USGS, mislocation km; 404 for unknown id or no snapshot |

Interactive docs at `/docs` (Swagger UI) — useful for report screenshots.

## 6. Repository layout

```
.
├── CLAUDE.md                     # handoff/context for Claude Code (cloud → local)
├── README.md                     # quickstart, limitations, data citation
├── Makefile                      # every CI stage runnable locally
├── Dockerfile  .dockerignore
├── Jenkinsfile                   # main CI/CD pipeline (multibranch)
├── pyproject.toml                # package, ruff, pytest markers (science, realdata), coverage config
├── requirements.txt              # runtime, exact pins (numpy, scipy, fastapi, uvicorn, pydantic)
├── requirements-dev.txt          # + pytest, pytest-cov, hypothesis, httpx, ruff
├── requirements-data.txt         # + obspy==1.5.1 (fetch tool only)
├── config/
│   ├── network.json              # fictitious synthetic network
│   ├── realdata.json             # origin, selection parameters
│   └── realdata_gates.json       # created with the first snapshot (make realdata-gates)
├── data/real/                    # README.md always; snapshot + MANIFEST.json once fetched
├── src/quakeloc/
│   ├── model.py  synth.py  detect.py  pick.py  locate.py  stats.py  geo.py
│   ├── pipeline.py               # preprocess + detect + pick + locate (shared)
│   ├── calibrate.py  experiment.py  realdata.py
│   ├── data/fetch.py             # ObsPy downloader (imported only in the data image)
│   └── schemas.py  api.py  smoke.py
├── tests/                        # unit / property / science / realdata / api / golden
│   ├── golden/seed42.json
│   └── fixtures/mini_snapshot/   # tiny synthetic snapshot in the real format (labelled)
├── k8s/                          # namespace, deployment, service, smoke-job
├── jenkins/
│   ├── Dockerfile                # jenkins/jenkins:2.580.2-lts-jdk21 + docker CLI + kubectl
│   ├── plugins.txt               # pinned plugin versions
│   ├── casc.yaml                 # JCasC: admin user, credentials, jobs (Job DSL)
│   ├── docker-compose.yml  up.sh  make-kubeconfig.sh
│   ├── secrets/                  # gitignored files: admin_password, dockerhub_token
│   └── Jenkinsfile.refresh-data  # parameterised live-data refresh job
└── docs/
    ├── design/quakeloc-design.md # this file
    ├── RUNBOOK.md                # step-by-step for macOS
    └── reports/                  # theory + practical report sources, DOCX/PDF, figures
```

`.gitignore` is anchored (`/reports/`, `/artifacts/`) so `docs/reports/` is never
ignored, and excludes `.env`, `jenkins/secrets/*` (except a README), `jenkins/kubeconfig`
and `*.kubeconfig`.

## 7. Docker

Multi-stage `Dockerfile`, base `python:3.12-slim` (multi-arch: native on Apple Silicon
and Intel). `.dockerignore` excludes `.git`, `/reports`, `/artifacts`, `*.tar.gz`; every
stage `COPY`s explicit paths only.

| Target | Content |
|---|---|
| `deps` | `python:3.12-slim` + exact-pinned runtime deps (wheels built once and reused) |
| `test` | `FROM deps` + dev deps + `pyproject.toml`, `src/`, `config/`, `data/real/`, `tests/`. **No calibration step**, so a code bug can only fail in the test stages. CI runs lint and tests inside this image, i.e. in the shipped environment |
| `artifacts` | `FROM deps` + package; runs `calibrate --seed 42` → `/artifacts` |
| `data` | `FROM deps` + `gcc libc6-dev` (ObsPy 1.5.1 has no linux/arm64 wheel, so it compiles from source on Apple Silicon) + `requirements-data.txt` + package; entrypoint `python -m quakeloc.data.fetch` |
| `runtime` | Clean `python:3.12-slim`; runtime deps + package installed from the `deps` wheels; `/artifacts`, `config/`, `data/real/` copied in; `useradd -u 10001 -r app` and **numeric** `USER 10001:10001`; `PYTHONDONTWRITEBYTECODE=1`, `OPENBLAS_NUM_THREADS=1`; `HEALTHCHECK` via `python -c "urllib.request.urlopen('http://127.0.0.1:8000/health')"`; `EXPOSE 8000`; exec-form `CMD ["uvicorn", "quakeloc.api:app", "--host", "0.0.0.0", "--port", "8000"]`. `ARG GIT_SHA BUILD_NUMBER CREATED` are consumed **only in the last lines** (ENV for `/version`, OCI labels `revision`, `source`, `created`), so they never invalidate the layer cache of earlier stages |

Expected runtime image ≈ 250–300 MB (numpy + scipy dominate).

## 8. CI/CD with Jenkins

### 8.1 Jenkins as code (runs on the Mac in Docker Desktop)

- `jenkins/Dockerfile`: `jenkins/jenkins:2.580.2-lts-jdk21` (pinned; the `lts-jdk17` line
  is end-of-life) + Docker CLI (+ buildx) + `kubectl` (architecture-aware download) +
  plugins from `plugins.txt` with **pinned versions** (configuration-as-code, job-dsl,
  workflow-aggregator, git, credentials-binding, junit, coverage, timestamper, ws-cleanup,
  pipeline-stage-view, pipeline-graph-view).
- `casc.yaml` (JCasC): no setup wizard, `numExecutors: 1`, admin user, `dockerhub`
  username/password credential, and two jobs via Job DSL:
  - **`quakeloc`** — multibranch pipeline on `https://github.com/a169n/applied_5.git`
    (public, no token needed) with periodic branch indexing every 2 minutes: **every push
    (each branch head) is built within about 2 minutes**. A laptop cannot receive GitHub
    webhooks without a tunnel; the report notes that webhooks would remove the delay.
  - **`quakeloc-refresh-data`** — pipeline from `jenkins/Jenkinsfile.refresh-data` on
    `*/main`, with its parameters declared in Job DSL (so they exist before the first run):
    `START=2005-01-01`, `END=2025-12-31`, `MIN_MAG=4.0`, `MAX_EVENTS=10`.
- Secrets: compose `secrets:` (`admin_password`, `dockerhub_token`, files under the
  gitignored `jenkins/secrets/`) mounted at `/run/secrets/`, resolved by JCasC as
  `${admin_password}` / `${dockerhub_token}`. Only the non-secret `DOCKERHUB_USER` is an
  environment variable. The pipeline uses the token only via `withCredentials` +
  `docker login --password-stdin`.
- `docker-compose.yml`: port 8080, `jenkins_home` volume, `/var/run/docker.sock` mounted
  (Jenkins drives the host Docker; the container runs as root for socket access —
  acceptable for a local single-user setup, stated in the report), `jenkins/kubeconfig`
  mounted read-only at `/kube/config` with `KUBECONFIG=/kube/config`, JVM `-Xmx768m`.
- `make-kubeconfig.sh`: writes **only** `jenkins/kubeconfig` (mode 600) via
  `kubectl config view --flatten --minify --context minikube`, then
  `kubectl config set-cluster minikube --server=https://$(minikube ip):8443 --kubeconfig jenkins/kubeconfig`.
  It never touches `~/.kube/config`.
- `up.sh`: requires `minikube status` = Running for CD (otherwise starts Jenkins with CD
  disabled and says so); reads the `minikube` network subnet, connects Jenkins with a
  fixed high address in it (`docker network connect --ip <prefix>.250 minikube <jenkins>`,
  never the node's static `.2`), regenerates the kubeconfig. Order: `minikube start` →
  `make jenkins-up`; after a reboot or `minikube stop`, re-run `make jenkins-up`.

The pipeline never bind-mounts the workspace into containers (paths differ between the
Jenkins container and the host daemon); the build context is streamed by `docker build`,
and reports are copied out with `docker cp`.

### 8.2 Main pipeline (`Jenkinsfile`, declarative)

Options: timestamps, build discarder, `disableConcurrentBuilds`. Local names include the
branch and build: `TAG = ${SHORT_SHA}-${BRANCH_NAME sanitised}-${BUILD_NUMBER}`.

| # | Stage | Branches | What it does |
|---|---|---|---|
| 1 | Checkout | all | `checkout scm`; `GIT_SHA`, `SHORT_SHA`, `TAG` |
| 2 | Build test image | all | `docker build --target test -t quakeloc-test:$TAG .` |
| 3 | Lint | all | `ruff check .` + `ruff format --check .` in the test image |
| 4 | Unit & property tests | all | `pytest -m "not science and not realdata"` with JUnit XML + coverage; **gate: 80 %** |
| 5 | Scientific validation | all | Calibrate (seed 42) **twice in separate containers** and require byte-identical outputs (reproducibility gate); `pytest -m science`; SNR experiment; archive `detector.json`, `manifest.json`, `snr_sweep.csv` |
| 6 | Real-data validation | all | If `data/real/MANIFEST.json` is missing: `unstable('real-data snapshot missing')`. Else verify checksums, relocate all events, `pytest -m realdata` against `config/realdata_gates.json`, archive `relocation.csv` |
| 7 | Build runtime image | all | `docker build --target runtime --build-arg GIT_SHA --build-arg BUILD_NUMBER --build-arg CREATED -t $IMAGE:$SHORT_SHA .`; then `docker create` + `docker cp` the baked `/artifacts` and assert their SHA-256 equals the files archived in stage 5 ("tested = shipped") |
| 8 | Container smoke test | all | Per-build network `qk-$TAG`; app container `app-$TAG` on it; a second container on the same network runs `python -m quakeloc.smoke --url http://app-$TAG:8000` (so a loopback-only bind would fail here): waits for `/ready`, checks `/version` SHA, `/demo` error < 1 km, and one `/events/{id}/locate` — or prints `SKIP: no snapshot` when `/events` is empty |
| 9 | Push to Docker Hub | `main`, build result SUCCESS | `docker login --password-stdin`; push `:$SHORT_SHA`; then `docker tag … :latest` and push `:latest` (only here, so feature branches never touch `:latest`) |
| 10 | Deploy to Minikube | `main`, build result SUCCESS, kubeconfig present | See below |

Stages 9–10 use `when { allOf { branch 'main'; expression { currentBuild.currentResult == 'SUCCESS' } } }`
— an UNSTABLE build (e.g. no snapshot yet) never ships.

Test stages 3–6 follow one pattern, so a failing test stays red and its report is still
published (no `|| true` anywhere):

```sh
set +e
docker run --name t-$TAG quakeloc-test:$TAG pytest ... --junitxml=/reports/unit.xml
rc=$?
docker cp t-$TAG:/reports ./reports; docker rm t-$TAG
exit $rc
```

`post { always }`: `junit 'reports/*.xml'`, coverage publishing, archive artifacts with
fingerprints, remove the per-build containers and network, remove `quakeloc-test:$TAG`,
`cleanWs()`.

**Stage 10 in order:**
1. `kubectl apply -f k8s/namespace.yaml`; render `deployment.yaml` (replace `__IMAGE__` with
   `$IMAGE:$SHORT_SHA`) and `service.yaml`, `kubectl apply` them.
2. `kubectl -n quakeloc rollout status deploy/quakeloc --timeout=180s`.
3. `kubectl -n quakeloc delete job quakeloc-smoke --ignore-not-found --wait=true`, then
   `kubectl create -f` the rendered `smoke-job.yaml` (never part of a directory-wide apply).
4. Poll `.status.succeeded` / `.status.failed` with a 120 s timeout; always print
   `kubectl logs job/quakeloc-smoke`.
5. On failure: `kubectl rollout undo` **only if** `rollout history` shows ≥ 2 revisions;
   then fail the build.

**Red-build demo:** branch `demo/broken-locator` negates the entire ∂t/∂x column in
`locate._jacobian`. `tests/test_locate.py::test_noise_free_exact_inversion` fails in
stage 4, so the build is red **before the runtime image is built or pushed** (the test
image has no calibration step, so stage 2 still succeeds). Screenshot for the report; the
branch is never merged.

### 8.3 Data refresh job (`jenkins/Jenkinsfile.refresh-data`)

Builds the `data` target, runs the fetcher into a fresh directory, **relocates the new
snapshot** (`quakeloc.realdata`) and prints: a diff against the committed `MANIFEST.json`
(events added/removed, changed hashes) and the new `relocation.csv` next to the current
gates. Archives the new snapshot + relocation as a tarball. It does **not** push; a human
commits the snapshot through a PR, where the main pipeline re-validates it.

### 8.4 Real-data gates bootstrap

`make realdata-gates` relocates the snapshot in the test image and writes
`config/realdata_gates.json`: max median mislocation = 1.5 × measured median, max RMS =
1.5 × measured max RMS, minimum fraction of events located = measured, plus a `rationale`
field and the snapshot hash it was derived from. It is committed **in the same PR as the
first snapshot**. Rule: gates change only in a PR that also changes the snapshot, with the
rationale in the PR description. A snapshot without gates makes stage 6 fail (not skip).

## 9. Kubernetes (Minikube, docker driver)

- `namespace.yaml` — `quakeloc`.
- `deployment.yaml` — 2 replicas, `RollingUpdate` (`maxUnavailable: 0`), container port
  `8000` named `http`, `readinessProbe` → `/ready`, `livenessProbe` → `/health`, requests
  100m/128Mi, limits 500m/384Mi, image placeholder `__IMAGE__`, and
  `securityContext: {runAsNonRoot: true, runAsUser: 10001, runAsGroup: 10001,
  allowPrivilegeEscalation: false, readOnlyRootFilesystem: true}`.
- `service.yaml` — `ports: [{name: http, port: 8000, targetPort: http, nodePort: 30080}]`
  (on macOS: `minikube service quakeloc -n quakeloc --url`).
- `smoke-job.yaml` — same image and securityContext,
  `python -m quakeloc.smoke --url http://quakeloc.quakeloc.svc:8000`, `backoffLimit: 0`,
  `ttlSecondsAfterFinished: 600`.

The image reaches Minikube via Docker Hub (public repository). Built on the Mac, the
image architecture matches the Minikube node (arm64 on Apple Silicon, amd64 on Intel).

## 10. Testing strategy

Coverage config: `source = ["quakeloc"]`, `omit = ["*/quakeloc/data/fetch.py"]`,
`[tool.coverage.paths]` maps `src/quakeloc` ↔ `*/site-packages/quakeloc`. The 80 % gate
applies in stage 4 only, so the fast suite itself must cover calibrate/experiment (tiny
`n`), smoke (against `TestClient`) and realdata (against `tests/fixtures/mini_snapshot`).
`--cov-fail-under` is passed on the stage-4 command line, never in `addopts`.

| Group | Marker | Examples |
|---|---|---|
| Model | – | Analytic travel time (60 km offset, 10 km depth → `sqrt(60²+10²)/6` s to 1e-12); elevation: `h = 3.4 km` → `sqrt(d² + 13.4²)/6` |
| Geo | – | Azimuthal-equidistant round trip; distances vs a few tabulated geodesic values |
| Detection | – | Vectorised STA/LTA = naive oracle (rtol 1e-9, atol 1e-12) on seeded traces with SNR ≤ 100; amplitude-scale invariance; noise-only mean of `ratio[valid_from:]` ≈ 1 (±0.05); flat input raises `SignalError` |
| Picking | – | Single-trace helper, 200 traces at SNR 10 with off-grid onsets: p95 ≤ 0.04 s, p99 ≤ 0.15 s, max ≤ 0.3 s. Shift equivariance (Hypothesis, derandomised CI profile): prepending `k ∈ [0, 2000]` samples of N(0, σ²) noise shifts the pick by exactly `k` (with `assume` that no trigger episode starts before the original onset − 3 s) |
| Location | – | Noise-free exact inversion (1e-6 km, 1e-6 s, ≤ 10 iterations) inside and at the edge of the network (`test_noise_free_exact_inversion`); constant pick shift moves only `t0`; guards (3 picks, collinear) raise; a deliberately wrong injected Jacobian raises `LocationError` or fails exactness |
| Statistics | – | Closed-form χ²₂ and F₂,ν quantiles vs tabulated values |
| Science | `science` | Ellipse coverage over 200 trials with analytic arrivals + i.i.d. N(0, 0.02²) pick noise, in both known-σ and estimated-σ modes, asserted **separately** for epicentres inside the network and outside it (x ∈ [110, 150] km): fraction in [0.90, 0.99]; calibration recall ≥ 0.95 for SNR ≥ 5 at FAR ≤ 1 %; golden seed-42 picks exact, locations rtol 1e-6 |
| Real data | `realdata` | Snapshot checksums; every event processed; median mislocation vs USGS, max RMS and located fraction within `config/realdata_gates.json` |
| API | – | TestClient: schemas, 422 paths, `/ready` 503 when the artifact hash is tampered with, `/version` content, `/events` = `[]` and 404 without a snapshot, fixture-snapshot event locates |
| Determinism | – | Same seed ⇒ identical arrays; different seeds ⇒ different arrays |

Goldens are regenerated only through `make golden` in a reviewed commit; a missing golden
fails the test (never skips). numpy is pinned exactly because only bit-generator streams
are guaranteed stable across versions (NEP 19).

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
| Lint, unit, property, science tests (incl. fixture-snapshot real-data code) | ✅ | ✅ |
| Docker build (`deps`/`test`/`artifacts`/`runtime`) + container smoke (events check prints SKIP until a snapshot exists) | ✅ (proxy CA workaround, cloud-only, never committed) | ✅ |
| `data` image on arm64 | ❌ (cloud is amd64) | ✅ |
| Real-data fetch from USGS/EarthScope | ❌ blocked by network policy unless the domains are allowed | ✅ |
| Real-data validation on a committed snapshot | ✅ once the snapshot exists | ✅ |
| Jenkins boot via JCasC + pipeline run | Attempt (depends on plugin-site access) | ✅ |
| Minikube deploy | ❌ | ✅ |
| Screenshots | ❌ | ✅ |

## 13. Git workflow

`main` is the default branch and always green. Work happens on feature branches
(currently `feat/quakeloc`), merged via pull requests after the pipeline is
green. Only `main` pushes images and deploys. Release tag `v1.0.0` marks the submitted
version.

## 14. Out of scope

Magnitude estimation, depth inversion, S phases, 3-D velocity models, real-time
streaming (SeedLink), additional seismic networks, multi-architecture image publishing,
GitHub webhooks via tunnels, Helm charts. Possible extensions are listed in the README.

## 15. Risks and mitigations

| Risk | Mitigation |
|---|---|
| KNET data gaps for chosen years | Fetcher keeps only events with ≥ 6 complete stations and widens nothing silently; if fewer than ~5 events qualify, the RUNBOOK says to widen `START/END` or lower `MIN_MAG` to 3.5 and record it in the manifest |
| Real mislocations larger than expected (1-layer model, filter delay, Pg/Pn) | Distance cap 150 km, elevation term, outlier rejection, gates derived from the first honest run with stated headroom; limitations discussed in the reports |
| LM divergence or stall | Earliest-station start, damping, iteration cap, undamped-step convergence check, typed error; tested |
| Floating-point differences between the cloud CPU and the Mac | Integer picks compared exactly, floats with rtol; byte-identity only required within one machine |
| ObsPy compilation on Apple Silicon | `data` target installs `gcc libc6-dev`; fallback: `make data` in a native macOS venv (an arm64 macOS wheel exists) |
| Jenkins ↔ Minikube networking on macOS | Jenkins joins the `minikube` network at a fixed `.250` address; kubeconfig rewritten to the node IP; startup order scripted in `up.sh` and RUNBOOK |
| Memory on 8 GB Macs (Docker Desktop VM gets 50 % of RAM by default) | RUNBOOK step 1: Docker Desktop → Resources → Memory ≥ 6 GB (8 GB on 16 GB Macs), verified with `docker info`; `minikube start --memory=2200mb --cpus=2`; Jenkins `-Xmx768m`, 1 executor |
