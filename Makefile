PYTHON=python3.5
PYTHON_VENV=env
INTERFACE=can0
SOCKET=/tmp/canopen_master.sock


$(PYTHON_VENV)/.created: setup.py
	rm -rf $(PYTHON_VENV) && \
	$(PYTHON) -m venv $(PYTHON_VENV) && \
	. $(PYTHON_VENV)/bin/activate && \
	pip install -e . && \
	date > $(PYTHON_VENV)/.created

env: $(PYTHON_VENV)/.created

clean:
	rm -rf $(PYTHON_VENV)

server: env
	. $(PYTHON_VENV)/bin/activate && \
	remotelab_canopen $(INTERFACE) --socket=$(SOCKET) $(args)

client: env
	. $(PYTHON_VENV)/bin/activate && \
	remotelab_canopen_cmd -s $(SOCKET) $(args)
