PYTHON ?= python3

MODEL ?= haiku
EFFORT ?= medium

.PHONY: test dev eval llm-dry llm-sample llm-dev llm-test

test:  ## unit tests
	$(PYTHON) -m unittest

dev:  ## tune here: seed 7
	$(PYTHON) -m say_my_name run --seed 7 --companies 5000 --name dev

eval:  ## report numbers from here only: seed 2026
	$(PYTHON) -m say_my_name run --seed 2026 --name test

llm-dry:  ## phase 3: one prompt and a cost estimate, no API calls
	$(PYTHON) -m say_my_name adjudicate --name dev --dry-run

llm-sample:  ## phase 3: a fixed sample of 50 dev pairs (needs the [llm] extra and an API key)
	$(PYTHON) -m say_my_name adjudicate --name dev --model $(MODEL) --effort $(EFFORT) --limit 50

llm-dev:  ## phase 3: every REVIEW pair of dev; iterate the prompt here
	$(PYTHON) -m say_my_name adjudicate --name dev --model $(MODEL) --effort $(EFFORT)

llm-test:  ## phase 3: held-out numbers, once the prompt is frozen
	$(PYTHON) -m say_my_name adjudicate --name test --model $(MODEL) --effort $(EFFORT)
