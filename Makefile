## TKOS Ontology Runtime — local test aggregator.
##
## Quick start:
##   make install      # python -m pip install -e '.[dev]'
##   make test-fast    # full pure-Python gate (legacy runners + runtime pytest)
##   make test         # full regression gate, adds the Openllet SWRL acceptance test
##
## Each recipe runs a single runner and fails fast on any non-zero exit, so the
## whole suite acts as a regression gate. Runners resolve their own root from the
## file location, so this Makefile is independent of the working directory.

PYTHON ?= python3

.PHONY: install generate test test-fast test-shacl test-context test-conformance test-isomorphism test-runtime test-swrl

install:
	$(PYTHON) -m pip install -e '.[dev]'

# Regenerate derived ontology artifacts from the JSON-LD source.
generate:
	$(PYTHON) scripts/export_schema_ttl.py
	$(PYTHON) scripts/export_protege_view.py

test-shacl:
	$(PYTHON) tests/run_v2_3_shacl.py

test-context:
	$(PYTHON) tests/run_v2_3_context_pack.py

test-conformance:
	$(PYTHON) tests/run_instance_conformance.py

test-isomorphism:
	$(PYTHON) tests/run_schema_isomorphism.py

test-runtime:
	$(PYTHON) -m pytest tests/test_runtime_*.py tests/test_agent_harness.py tests/test_decision_context_compiler.py tests/test_render_units.py tests/test_openai_text_polisher.py -v

# Pure-Python gate for the fast local feedback loop.
test-fast: test-shacl test-context test-conformance test-isomorphism test-runtime

# Full regression gate. Adds the Openllet SWRL acceptance test, which needs Java
# and a built Openllet CLI (openllet/openllet.sh builds it on first run via Maven).
test: test-fast test-swrl

test-swrl:
	$(PYTHON) tests/run_v2_3_swrl_openllet.py
