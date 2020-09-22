PYTHON=python3.7
PYTHON_VENV=env
INTERFACE=can0

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
	lxa-iobus-server $(INTERFACE) $(args)
