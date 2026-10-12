# Offline targets only; real API runs are explicit (see README).
RUN ?= runs/pilot
N ?= 50
SAMPLE = runs/sample_n$(N)_seed20261004.parquet

.PHONY: frame sample test mock power
frame: data/frame.parquet
data/frame.parquet: config.yaml k12aii/frame.py
	python3 -m k12aii build-frame
$(SAMPLE): data/frame.parquet k12aii/sample.py
	python3 -m k12aii sample --n $(N)
sample: $(SAMPLE)
test:
	python3 -m pytest -q tests
power:
	python3 -m k12aii power
mock: $(SAMPLE)       # full dry run with fake models/judge; results are NOT real
	rm -rf runs/mock
	python3 -m k12aii run --sample $(SAMPLE) --run-dir runs/mock --models mock-old mock-new
	python3 -m k12aii judge --run-dir runs/mock --judge-provider mock --judge-model mock
	python3 -m k12aii analyze --run-dir runs/mock
