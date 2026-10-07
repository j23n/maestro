# Reference study and review endpoint (docs/12, task M6.6). Standard library only.
PYTHON ?= python3

.PHONY: test serve
test:
	cd $(CURDIR) && $(PYTHON) -m unittest -v test_server 2>&1

serve:
	cd $(CURDIR) && $(PYTHON) server.py serve --port 8787
