PYTHON=python3
PYTHON_VENV=env
INTERFACE=can0
LSS_ADDRESS_CACHE_FILE=lss-address-cache.json

$(PYTHON_VENV)/.created: setup.py
	rm -rf $(PYTHON_VENV) && \
	$(PYTHON) -m venv $(PYTHON_VENV) && \
	. $(PYTHON_VENV)/bin/activate && \
	pip install -e .[full] && \
	date > $(PYTHON_VENV)/.created

env: $(PYTHON_VENV)/.created

clean:
	rm -rf $(PYTHON_VENV)

server: env
	. $(PYTHON_VENV)/bin/activate && \
	lxa-iobus-server \
		$(INTERFACE) \
		--lss-address-cache-file=$(LSS_ADDRESS_CACHE_FILE) \
		$(args)
