PYTHON ?= python3

.PHONY: test dev eval

test:  ## unit tests
	$(PYTHON) -m unittest

dev:  ## tune here: seed 7
	$(PYTHON) -m say_my_name run --seed 7 --companies 5000 --name dev

eval:  ## report numbers from here only: seed 2026
	$(PYTHON) -m say_my_name run --seed 2026 --name test
