## TKOS Ontology Runtime — local test aggregator.
##
## Quick start:
##   make install      # python -m pip install -e '.[dev]'
##   make test-fast    # the three pure-Python suites (no Java/Openllet needed)
##   make test         # full regression gate, adds the Openllet SWRL acceptance test
##
## Each recipe runs a single runner and fails fast on any non-zero exit, so the
## whole suite acts as a regression gate. Runners resolve their own root from the
## file location, so this Makefile is independent of the working directory.

PYTHON ?= python3

.PHONY: install test test-fast test-shacl test-context test-conformance test-swrl

install:
	$(PYTHON) -m pip install -e '.[dev]'

test-shacl:
	$(PYTHON) tests/run_v2_3_shacl.py

test-context:
	$(PYTHON) tests/run_v2_3_context_pack.py

test-conformance:
	$(PYTHON) tests/run_instance_conformance.py

# Pure-Python gate for the fast local feedback loop.
test-fast: test-shacl test-context test-conformance

# Full regression gate. Adds the Openllet SWRL acceptance test, which needs Java
# and a built Openllet CLI (openllet/openllet.sh builds it on first run via Maven).
test: test-fast test-swrl

test-swrl:
	$(PYTHON) tests/run_v2_3_swrl_openllet.py
