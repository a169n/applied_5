# quakeloc runbook (macOS)

Tested on an Apple M4 with 16 GB RAM, Docker Desktop, Minikube v1.39.0 and Kubernetes v1.37.0.
Run every command from the repository root.

## 1. Check the prerequisites

```sh
brew install minikube kubectl uv gh pandoc poppler   # plus Docker Desktop and LibreOffice
docker info --format '{{.MemTotal}}'                  # must be at least 6 GB
```

If it is lower, raise it in Docker Desktop under Settings > Resources > Memory (8 GB on a
16 GB Mac).

## 2. Create the Jenkins secrets (once)

Never commit these files or paste them anywhere. They are gitignored.

```sh
openssl rand -base64 18 > jenkins/secrets/admin_password
echo 'DOCKERHUB_USER=<your-docker-hub-username>' > jenkins/.env
```

Create a **public** Docker Hub repository named `quakeloc` (Minikube pulls it without
credentials) and an access token with read and write scope at
<https://app.docker.com/settings/personal-access-tokens>, then save the token without echoing it:

```sh
read -rs TOKEN && printf '%s' "$TOKEN" > jenkins/secrets/dockerhub_token; unset TOKEN
```

## 3. Start Minikube, then Jenkins

The order matters: `up.sh` connects Jenkins to the Minikube network and writes its kubeconfig.

```sh
minikube start --driver=docker --memory=2200mb --cpus=2
make jenkins-up
```

Open <http://localhost:8080> and log in as `admin` with the password in
`jenkins/secrets/admin_password`.

**After a reboot or `minikube stop`, run both commands again.** If Minikube is not running,
`up.sh` still starts Jenkins with CD disabled and says so; stage 10 is then skipped.

If you changed `jenkins/.env` or the secrets, recreate the container so that they load:

```sh
docker compose -f jenkins/docker-compose.yml up -d --force-recreate && make jenkins-up
```

## 4. Run the pipeline

Push a branch. Branch indexing runs every 2 minutes, so the build starts within about 2
minutes. Feature branches stop after the container smoke test. Only `main` pushes to Docker
Hub and deploys, and only if the build is SUCCESS: a build marked UNSTABLE never ships.

To reproduce a stage locally, use the Makefile target of the same name:

```sh
make image-test lint test calibrate science realdata image smoke
```

If `git push` hangs without output, macOS is probably waiting on a keychain prompt. Answer it,
or use the GitHub CLI login for that push:

```sh
git -c credential.helper= -c 'credential.helper=!gh auth git-credential' push
```

## 5. See the deployed service

```sh
kubectl -n quakeloc get pods
minikube service quakeloc -n quakeloc --url    # keep this terminal open; prints a local URL
```

Then open `<url>/docs`, `<url>/version` or `<url>/events`.

## 6. Refresh the real data

Either run the Jenkins job `quakeloc-refresh-data`, which archives the new snapshot as a
tarball, or run it directly:

```sh
make data FETCH_ARGS="--min-mag 3.5"
make image-test calibrate realdata-gates    # writes config/realdata_gates.json
make image-test calibrate realdata          # second pass: the image must contain the new gates
```

Commit the snapshot and `config/realdata_gates.json` in the same pull request, with the
reason in the description. Gates change only together with the snapshot.

If too few events qualify, lower the magnitude with `FETCH_ARGS`; the values used are recorded
in `data/real/MANIFEST.json`. Widening the dates does not help at present: in November 2026
EarthScope returned HTTP 204 for KN outside roughly 2013 to 2016 (sampled at 2011, 2014, 2016
and 2020), which is why the committed snapshot has only 4 events.

If the `data` image does not compile on your machine, use a native environment instead:

```sh
uv venv --python 3.12 .venv-data
VIRTUAL_ENV=.venv-data uv pip install -r requirements-data.txt -e .
.venv-data/bin/python -m quakeloc.data.fetch --out data/real --min-mag 3.5
```

## 7. Demonstrate a red build

```sh
git switch -c demo/broken-locator main
# in src/quakeloc/locate.py, _jacobian: change `dx / (VP_KM_S * r)` to `-dx / (VP_KM_S * r)`
git commit -am "Demo: negate the dt/dx column of the Jacobian"
git push -u origin demo/broken-locator
```

The build fails at stage 4 on `test_noise_free_exact_inversion`, before any runtime image is
built or pushed. Never merge this branch.

## 8. Stop everything

```sh
make jenkins-down      # keeps the jenkins_home volume
minikube stop          # or `minikube delete` to remove the cluster
```

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `up.sh` reports a missing file | Create it as in step 2. |
| Stage 10 is skipped | Minikube was not running when `up.sh` ran. Start it and run `make jenkins-up`. |
| `kubectl` in Jenkins cannot reach the cluster | The Minikube IP changed. Run `make jenkins-up` to regenerate the kubeconfig. |
| Stage 7 fails on `cmp` | Locally: `src/` or `config/` changed since the last calibration; run `make image-test calibrate`. Under Jenkins: something non-deterministic entered the calibration inputs. Do not bypass this. |
| Stage 6 fails with a missing gates file | The snapshot was committed without gates. Run `make realdata-gates`. |
| Pods stay not ready | `kubectl -n quakeloc describe pod`, then `curl <url>/ready`. The response states the reason. |
