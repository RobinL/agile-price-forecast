# Frontend-only work does not need Python or cloud credentials.
DATA_MODE ?= demo
UV_CACHE_DIR ?= $(CURDIR)/.cache/uv
export UV_CACHE_DIR
export PLAYWRIGHT_BROWSERS_PATH = $(CURDIR)/.cache/ms-playwright

.PHONY: setup dev build preview-local demo-local import-research train-local evaluate-local collect-local forecast-local test format update-history-local verify-research-local score-local
setup:
	uv sync --locked
	npm ci
dev:
	DATA_MODE=$(DATA_MODE) npm run dev
build:
	DATA_MODE=$(DATA_MODE) npm run build
preview-local: build
	npm run preview
demo-local:
	uv run agile-forecast --state-dir runtime_state/demo demo
	uv run agile-forecast --state-dir runtime_state/demo train
	uv run agile-forecast --state-dir runtime_state/demo forecast
import-research:
	uv run agile-forecast import-research --from ../initial_experiments
train-local:
	uv run agile-forecast train
evaluate-local:
	uv run agile-forecast evaluate
collect-local:
	uv run agile-forecast collect
forecast-local:
	uv run agile-forecast forecast
test:
	uv run pytest -q
	npm test
format:
	uv run ruff format src tests
	npm run format

update-history-local:
	uv run agile-forecast update-history
verify-research-local:
	uv run agile-forecast verify-research --from ../initial_experiments
score-local:
	uv run agile-forecast score

# Offline preparation and inspection. These commands do not contact R2.
.PHONY: prepare-cloud-seed check-site
prepare-cloud-seed:
	uv run --locked agile-cloud prepare-seed
check-site:
	uv run --locked agile-cloud check-site
