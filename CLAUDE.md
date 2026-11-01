# CLAUDE.md — quakeloc (Assignment 5: DevOps & CI/CD for research projects)

This file gives Claude Code the full context of this repository so work can continue
seamlessly — first in a cloud session, later on the student's Mac. **Keep it up to date:**
whenever a milestone is finished or a decision changes, update "Status" and "Next steps".

## What this repo is

A university assignment (*Assignment 5 — DevOps and CI/CD: Automating Processes for
Research Projects*), graded out of 100 + 10 bonus:

- Theory report, 3 pages (30 pts)
- Docker image (15), Jenkins CI pipeline (25), Git & automation (10), practical report
  with screenshots (10), bonus CD deployment (+10)

The practical project is **quakeloc**: earthquake detection (STA/LTA), onset picking
(AIC) and epicentre location (Geiger / Levenberg–Marquardt with 95 % error ellipses) for
the northern Tien Shan, served by FastAPI, built with Docker, CI/CD in Jenkins, deployed
to Minikube. Real data comes from the KNET network around **Bishkek (~190 km WSW of
Almaty)** — Almaty is the regional motivation only; never describe the real-data results
as "Almaty region".

**The design spec is the source of truth:** `docs/design/quakeloc-design.md`.
Read it before changing anything.

## Decisions already made with the student (do not re-ask)

- All deliverables (code, comments, docs, reports) in **English**. The student chats in
  Russian; answer in the language they write in.
- Theory report: **exactly 3 pages**, 12 pt, 1.5 line spacing, DOCX + PDF, compact
  header instead of a separate title page (unless the student says otherwise).
- Project: **quakeloc**, hybrid data = synthetic (tests) + committed real snapshot of
  KNET (`KN`) waveforms with USGS catalog solutions + live-API refresh job.
- Student's machine: **macOS** (Docker Desktop). Chip and RAM: *not yet provided*.
- CD bonus: **yes**, Minikube (docker driver), deployed automatically by Jenkins.
- Docker Hub push: **yes** — the student will create an account; username *not yet provided*.
- Theory report examples anchored in the project's domain (seismology / research software).
- `main` is the GitHub default branch. Feature work happens on branches and goes to
  `main` via PRs; Jenkins pushes/deploys only from `main`.

## Student data needed for reports (fill in when provided)

| Field | Value |
|---|---|
| Full name (Latin) | Aibyn Talgatov |
| Group / student ID | CSE-2505M / 255308 |
| University, faculty | Astana IT University, Computer Science and Engineering |
| Course name | Applied Software Development Project |
| Instructor | Akanova Akerke |
| Mac chip / RAM | Apple M4 (arm64) / 16 GB; Docker VM 7.65 GiB |
| Docker Hub username | _pending_ |
| GitHub | `a169n` — repo https://github.com/a169n/applied_5 |

## Status

| Milestone | State |
|---|---|
| Assignment analysed, project chosen (multi-agent idea selection) | done |
| `main` created as default branch | done |
| Design spec `docs/design/quakeloc-design.md` | rev 2 — approved by student 2026-11-01 |
| Implementation plan | approved: `docs/superpowers/plans/2026-11-01-quakeloc.md`; native execution on branch `feat/quakeloc` |
| Python package + tests | done on `feat/quakeloc` (fixture snapshot; real snapshot pending) |
| Dockerfile / Makefile / Jenkins (JCasC) | done on `feat/quakeloc`; k8s in progress |
| Real-data snapshot `data/real/` | not started — **blocked in cloud** (see below) |
| Theory report (3 pages) | not started |
| RUNBOOK for macOS | not started |
| Local run on Mac + screenshots | not started (student) |
| Practical report (1–2 pages) | not started (needs screenshots) |

## Cloud-session limitations (why some work must happen on the Mac)

The cloud container's egress proxy only allows package registries, Docker Hub and
GitHub. Consequences:

1. **USGS / EarthScope / EMSC are blocked** (`earthquake.usgs.gov`,
   `service.earthscope.org`, `service.iris.edu`, `www.seismicportal.eu` → HTTP 403).
   The real-data snapshot must be fetched on the Mac (`make data`) unless the student
   adds these domains to the cloud environment's allowed domains.
2. **No Minikube / Kubernetes** in the cloud; deployment can only be tested on the Mac.
3. **Docker builds in the cloud need a proxy workaround:** containers don't trust the
   proxy CA. Cloud-only trick: build a local base image `cloud-py312` = `python:3.12-slim`
   + `/root/.ccr/ca-bundle.crt` with `PIP_CERT`/`SSL_CERT_FILE` set, retag it as
   `python:3.12-slim` in the cloud daemon only, and build with `--network host` plus
   `HTTPS_PROXY` build args. **Never commit this workaround** — on the Mac, plain
   `docker build` works.
4. The Docker daemon is not running by default in the cloud: start it with
   `dockerd > /tmp/dockerd.log 2>&1 &`.
5. `get.jenkins.io` is blocked; the Jenkins *image* (`jenkins/jenkins:2.580.2-lts-jdk21`,
   multi-arch) pulls fine from Docker Hub, but plugin downloads (updates.jenkins.io) may be
   blocked — Jenkins may only be fully testable on the Mac. Do not use `lts-jdk17`
   (frozen at 2.541.3, Java 17 end-of-life).
6. ObsPy: use **1.5.1** (1.4.1 fails on Python 3.12 without `pkg_resources`). Verified
   working with numpy 2.5 in `python:3.12-slim` **on amd64 only**; it maps `EARTHSCOPE` →
   `https://service.earthscope.org`. There is **no linux/arm64 wheel**, so on Apple
   Silicon the `data` Docker target compiles it from source and needs `gcc libc6-dev`
   (already in the spec); a native macOS venv also works (arm64 macOS wheel exists).
7. The cloud is amd64; the Mac may be arm64. Anything architecture-specific (the `data`
   image, kubectl download in the Jenkins image) is only proven on the Mac.

## Conventions

- Python 3.12, `src/` layout, package `quakeloc`. Ruff for lint + format.
- Exact pins in `requirements*.txt`; numpy pinned exactly (RNG reproducibility, NEP 19).
- Tests: pytest markers `science` and `realdata`; Hypothesis CI profile is derandomised.
- Every CI stage has a `make` target with the same command (Makefile mirrors Jenkinsfile).
- Never fetch data inside the main pipeline or tests; only the refresh job/CLI uses the network.
- Commits: imperative mood, small and focused. Do not push to `main` directly unless the
  student asks; use PRs.

## Next steps

1. Execute `docs/superpowers/plans/2026-11-01-quakeloc.md` task by task, in this order:
   core science package + tests → Dockerfile → Makefile → Jenkins (JCasC) → k8s → fetch
   tool → reports → RUNBOOK.
2. One fresh reviewer checks the whole branch at the end.
3. On the Mac: follow `docs/RUNBOOK.md` (fetch real data, start Jenkins + Minikube,
   run the pipeline, take screenshots), then finish the practical report.

## Handoff prompt for Claude Code on the Mac

When continuing locally, open a terminal in the cloned repo, run `claude`, and paste:

```text
Read CLAUDE.md and docs/design/quakeloc-design.md first. We are continuing the
quakeloc project (Assignment 5, DevOps & CI/CD) that was started in a Claude Code
cloud session, which could not reach the seismic data APIs or run Minikube.
I am now on my Mac with Docker Desktop. Check the "Status" and "Next steps"
sections of CLAUDE.md, verify the current state of the repo (git log, tests,
docker build), then help me with the remaining local-only steps: fetch the real
KNET/USGS data snapshot (make data), start Jenkins and Minikube (docs/RUNBOOK.md),
get the pipeline green on main including the Minikube deploy, take the screenshots
for the report, and finish docs/reports/practical. Ask me before pushing to main.
Keep CLAUDE.md updated as we go.
```
