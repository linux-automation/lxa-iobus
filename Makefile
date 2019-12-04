OLD_PYTHON=python3.5
OLD_PYTHON_VENV=old_env
INTERFACE=can0
SOCKET=/tmp/canopen_master.sock


$(OLD_PYTHON_VENV)/.created: setup.py
	rm -rf $(OLD_PYTHON_VENV) && \
	$(OLD_PYTHON) -m venv $(OLD_PYTHON_VENV) && \
	. $(OLD_PYTHON_VENV)/bin/activate && \
	pip install -e . && \
	date > $(OLD_PYTHON_VENV)/.created

old_env: $(OLD_PYTHON_VENV)/.created

old-clean:
	rm -rf $(OLD_PYTHON_VENV)

old-server: old_env
	. $(OLD_PYTHON_VENV)/bin/activate && \
	remotelab_canopen $(INTERFACE) --socket=$(SOCKET) $(args)

old-client: old_env
	. $(OLD_PYTHON_VENV)/bin/activate && \
	remotelab_canopen_cmd -s $(SOCKET) $(args)
