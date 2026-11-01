---
title: "Practical Report: CI/CD Pipeline for quakeloc"
author:
  - "Aibyn Talgatov, group CSE-2505M, student ID 255308"
  - "Astana IT University, Faculty of Computer Science and Engineering"
  - "Applied Software Development Project. Instructor: Akanova Akerke"
---

# 1. Project and links

quakeloc detects earthquakes (STA/LTA), picks P-wave onsets (AIC) and locates epicentres with 95 % error ellipses (Geiger's method). It is a FastAPI service validated on synthetic data and on a frozen snapshot of the KNET network near Bishkek. Repository: <https://github.com/a169n/applied_5>. Pipeline: [Jenkinsfile](https://github.com/a169n/applied_5/blob/main/Jenkinsfile). Image: <https://hub.docker.com/r/a169n/quakeloc>. Steps to reproduce: [docs/RUNBOOK.md](https://github.com/a169n/applied_5/blob/main/docs/RUNBOOK.md).

# 2. Steps

**Docker.** A multi-stage `Dockerfile` has separate `test`, `artifacts`, `data` and `runtime` targets. The runtime image contains no compilers or test tools and runs as a non-root user. It is 516 MB locally and 108.9 MB compressed on Docker Hub (Figure 3). A build fails if the calibration artifacts it bakes in differ from those the tests validated.

**Jenkins.** Jenkins runs in Docker and is configured entirely from the repository (Configuration as Code and Job DSL), so it can be recreated with one command. A multibranch job scans GitHub every 2 minutes, because a local Jenkins cannot receive webhooks. The ten stages are checkout, test image, lint, unit and property tests, scientific validation, real-data validation, runtime image, container smoke test, Docker Hub push and Minikube deploy. The last two run only on `main`. A separate job refreshes the data and never pushes; its first run fetched files identical to the committed snapshot.

**Git and automation.** Work reached `main` through a pull request, and every build and test stage has a `make` target with the same command, so CI failures can be reproduced locally.

**Deployment (bonus).** Stage 10 deploys the image tagged with the commit SHA to Minikube, runs a smoke Job inside the cluster and rolls back on failure. I tested the rollback manually.

# 3. Results

**Green run.** `main` build #1 passed all stages in 2 min 23 s (Figure 1) with 173 tests passing (Figure 4). Most stages were fast because the branch build had already filled the Docker layer cache. `/version` in the cluster returned the SHA of `main` HEAD, `d5ba3ca`.

![Figure 1. Green pipeline on `main`, build #1.](figures/jenkins_green.png){width=17cm}

**Red run.** Branch `demo/broken-locator` negates one column of the location Jacobian. Stage 4 failed with 47 of 162 tests failing, including `test_noise_free_exact_inversion` (Figure 2). Nothing was pushed or deployed: Docker Hub and the cluster stayed on `d5ba3ca`. This branch is never merged.

![Figure 2. Red pipeline on `demo/broken-locator`. The console reports stages 5 to 10 as "skipped due to earlier failure"; Stage View paints them as failed.](figures/jenkins_red.png){width=17cm}

**Cluster state** after the deploy (`kubectl -n quakeloc get pods`):

```text
NAME                        READY   STATUS      RESTARTS   AGE
quakeloc-57945b5df7-pmx4k   1/1     Running     0          5m25s
quakeloc-57945b5df7-tzzvg   1/1     Running     0          5m41s
quakeloc-smoke-6gcrg        0/1     Completed   0          5m19s
```

+-----------------------------------------------+-----------------------------------------------+
| ![](figures/dockerhub_tags.png){width=8.3cm}  | ![](figures/jenkins_tests.png){width=8.3cm}   |
|                                               |                                               |
| Figure 3. Docker Hub tags.                    | Figure 4. Jenkins test report.                |
+-----------------------------------------------+-----------------------------------------------+
| ![](figures/api_docs.png){width=8.3cm}        | ![](figures/snr_sweep.png){width=8.3cm}       |
|                                               |                                               |
| Figure 5. API documentation at `/docs`.       | Figure 6. Synthetic SNR sweep, seed 42.       |
+-----------------------------------------------+-----------------------------------------------+

![Figure 7. Response of `/events/usb000r68x/locate` from the Minikube deployment.](figures/api_locate.png){width=17cm}

**Science.** On synthetic data, recall rises from 0.89 at SNR 3 to 1.0 at SNR 5 and above, and mean location error falls from 1.54 km to 0.02 km (Figure 6). On real data all 4 events locate, at 2.8, 7.5, 12.2 and 18.3 km from the USGS epicentres. Four events are a demonstration, not a statistical validation. The ellipses cover pick scatter only, so the USGS epicentre often lies outside them.

# 4. Difficulties

- **Sparse real data.** EarthScope returned no KN waveforms for much of the catalog period, so only 4 events qualified and lowering the magnitude limit to 3.5 added none. I kept the 4 events and stated the limit instead of tuning the results.
- **Stale artifacts.** The identity check failed locally after `src/` changed, because the artifacts were older than the code. Recalibrating fixed it, and the runbook now lists this case.
- **Jenkins lost its network.** Recreating the container dropped its link to the Minikube network, so `make jenkins-up` now restores it.
- **A test hid failures.** A stub's final `exit 0` masked simulated `kubectl` failures, so a commit went in with two failing tests. The next commit fixed the stub.
- **Git on macOS.** `git push` hung on a keychain prompt; pushing through the GitHub CLI's credential helper solved it.

# 5. Conclusions

The pipeline turns a merge into a tested, published and deployed service without manual steps, and the red run shows that a scientific bug stops before release. The most useful decision was to test against known answers, since a generic smoke test would not have caught a sign error in the Jacobian. The main limits are the small real-data sample, the one-layer velocity model and a Jenkins instance that runs only on a laptop.
