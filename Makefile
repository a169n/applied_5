# Every CI stage is a target here; the Jenkinsfile calls these same targets.
# Nothing bind-mounts the workspace: under Jenkins, workspace paths differ between the
# Jenkins container and the host Docker daemon. Build contexts are streamed and results are
# copied out with `docker cp`.

TAG ?= dev
IMAGE ?= quakeloc
GIT_SHA ?= $(shell git rev-parse HEAD)
SHORT_SHA ?= $(shell git rev-parse --short HEAD)
BUILD_NUMBER ?= local
TEST_IMAGE = quakeloc-test:$(TAG)
RUNTIME_IMAGE = $(IMAGE):$(SHORT_SHA)
FAST = not science and not realdata
SEED = 42

# Fetch parameters (config/realdata.json holds the defaults).
FETCH_ARGS ?=

.PHONY: venv image-test lint test calibrate science realdata image smoke golden data \
	realdata-gates jenkins-up jenkins-down deploy clean-build

venv:
	uv venv --python 3.12 .venv
	VIRTUAL_ENV=.venv uv pip install -r requirements-dev.txt
	VIRTUAL_ENV=.venv uv pip install -e .

image-test:
	docker build --target test -t $(TEST_IMAGE) .

lint:
	docker run --rm $(TEST_IMAGE) sh -c 'ruff check . && ruff format --check .'

# Fast suite with the 80 % coverage gate. A failing test stays red and its report survives.
test:
	@mkdir -p reports
	set +e; \
	docker run --name t-unit-$(TAG) $(TEST_IMAGE) pytest -m "$(FAST)" \
		--junitxml=/reports/unit.xml --cov --cov-report=term \
		--cov-report=xml:/reports/coverage.xml --cov-fail-under=80; \
	rc=$$?; \
	docker cp t-unit-$(TAG):/reports/. reports/; \
	docker rm t-unit-$(TAG) > /dev/null; \
	exit $$rc

# Calibrate twice in separate containers; the outputs must be byte-identical.
calibrate:
	@rm -rf artifacts artifacts.second
	docker run --name t-cal1-$(TAG) $(TEST_IMAGE) \
		python -m quakeloc.calibrate --seed $(SEED) --out /artifacts
	docker run --name t-cal2-$(TAG) $(TEST_IMAGE) \
		python -m quakeloc.calibrate --seed $(SEED) --out /artifacts
	docker cp t-cal1-$(TAG):/artifacts artifacts
	docker cp t-cal2-$(TAG):/artifacts artifacts.second
	docker rm t-cal1-$(TAG) t-cal2-$(TAG) > /dev/null
	cmp artifacts/detector.json artifacts.second/detector.json
	cmp artifacts/manifest.json artifacts.second/manifest.json
	@rm -rf artifacts.second
	@echo "Reproducibility gate passed: calibration outputs are byte-identical."

artifacts/detector.json:
	$(MAKE) calibrate

# Scientific tests plus the SNR experiment, which is reported rather than gated.
science: artifacts/detector.json
	@mkdir -p reports
	docker create --name t-sci-$(TAG) -e QUAKELOC_ARTIFACTS=/artifacts $(TEST_IMAGE) sh -c \
		'pytest -m science --junitxml=/reports/science.xml \
		&& python -m quakeloc.experiment --artifacts /artifacts --out /reports/snr_sweep.csv'
	docker cp artifacts/. t-sci-$(TAG):/artifacts
	set +e; \
	docker start -a t-sci-$(TAG); \
	rc=$$?; \
	docker cp t-sci-$(TAG):/reports/. reports/; \
	docker rm t-sci-$(TAG) > /dev/null; \
	exit $$rc
	@if [ -f reports/snr_sweep.csv ]; then cp reports/snr_sweep.csv artifacts/snr_sweep.csv; fi

# Verify checksums, relocate all snapshot events, enforce config/realdata_gates.json.
realdata: artifacts/detector.json
	@test -f data/real/MANIFEST.json || (echo "No real snapshot: run make data" && exit 1)
	@mkdir -p reports
	docker create --name t-real-$(TAG) -e QUAKELOC_ARTIFACTS=/artifacts $(TEST_IMAGE) sh -c \
		'python -m quakeloc.realdata --snapshot data/real --artifacts /artifacts \
			--out /reports/relocation.csv \
		&& pytest -m realdata --junitxml=/reports/realdata.xml'
	docker cp artifacts/. t-real-$(TAG):/artifacts
	set +e; \
	docker start -a t-real-$(TAG); \
	rc=$$?; \
	docker cp t-real-$(TAG):/reports/. reports/; \
	docker rm t-real-$(TAG) > /dev/null; \
	exit $$rc

# Build the runtime image, then prove the baked artifacts are the ones just tested.
image: artifacts/detector.json
	docker build --target runtime --build-arg GIT_SHA=$(GIT_SHA) \
		--build-arg BUILD_NUMBER=$(BUILD_NUMBER) \
		--build-arg CREATED=$(shell date -u +%Y-%m-%dT%H:%M:%SZ) \
		-t $(RUNTIME_IMAGE) .
	@rm -rf artifacts.baked
	docker create --name t-baked-$(TAG) $(RUNTIME_IMAGE)
	docker cp t-baked-$(TAG):/artifacts artifacts.baked
	docker rm t-baked-$(TAG) > /dev/null
	cmp artifacts/detector.json artifacts.baked/detector.json
	cmp artifacts/manifest.json artifacts.baked/manifest.json
	@rm -rf artifacts.baked
	@echo "Tested = shipped: baked artifacts match the tested ones."

# A second container on a per-build network, so a loopback-only bind would fail here.
smoke:
	docker network create qk-$(TAG)
	docker run -d --name app-$(TAG) --network qk-$(TAG) $(RUNTIME_IMAGE)
	set +e; \
	docker run --rm --network qk-$(TAG) $(RUNTIME_IMAGE) \
		python -m quakeloc.smoke --url http://app-$(TAG):8000; \
	rc=$$?; \
	if [ $$rc -ne 0 ]; then docker logs app-$(TAG); fi; \
	docker rm -f app-$(TAG) > /dev/null; \
	docker network rm qk-$(TAG) > /dev/null; \
	exit $$rc

# Regenerate the golden file. Only in a reviewed commit.
golden: image-test
	docker run --name t-golden-$(TAG) $(TEST_IMAGE) python tests/golden/regen.py
	docker cp t-golden-$(TAG):/app/tests/golden/seed42.json tests/golden/seed42.json
	docker rm t-golden-$(TAG) > /dev/null

# The only targets that use the network for data.
data:
	docker build --target data -t quakeloc-data:dev .
	docker run --rm -v "$(CURDIR)/data/real:/out" quakeloc-data:dev --out /out $(FETCH_ARGS)

# Derive the gates from the snapshot; commit them in the same PR as the first snapshot.
realdata-gates: image-test artifacts/detector.json
	docker create --name t-gates-$(TAG) $(TEST_IMAGE) python -m quakeloc.realdata \
		--snapshot data/real --artifacts /artifacts --out /reports/relocation.csv \
		--write-gates /reports/realdata_gates.json
	docker cp artifacts/. t-gates-$(TAG):/artifacts
	docker start -a t-gates-$(TAG)
	docker cp t-gates-$(TAG):/reports/realdata_gates.json config/realdata_gates.json
	docker rm t-gates-$(TAG) > /dev/null

jenkins-up:
	jenkins/up.sh

jenkins-down:
	docker compose -f jenkins/docker-compose.yml down

deploy:
	k8s/deploy.sh $(RUNTIME_IMAGE)

# Removes anything a failed or aborted build left behind.
clean-build:
	-docker rm -f t-unit-$(TAG) t-cal1-$(TAG) t-cal2-$(TAG) t-sci-$(TAG) t-real-$(TAG) \
		t-baked-$(TAG) t-gates-$(TAG) t-golden-$(TAG) app-$(TAG)
	-docker network rm qk-$(TAG)
	-docker rmi $(TEST_IMAGE)
