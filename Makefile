PYTHON=python3
PYTHON_VENV=env
PYTHON_PACKAGING_VENV=$(PYTHON_VENV)-packaging
PYTHON_TESTING_ENV=$(PYTHON_VENV)-qa
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
	rm -rf $(PYTHON_PACKAGING_VENV)

server: env
	. $(PYTHON_VENV)/bin/activate && \
	lxa-iobus-server \
		$(INTERFACE) \
		--lss-address-cache-file=$(LSS_ADDRESS_CACHE_FILE) \
		$(args)

# packaging environment #######################################################
$(PYTHON_PACKAGING_VENV)/.created: REQUIREMENTS.packaging.txt
	rm -rf $(PYTHON_PACKAGING_VENV) && \
	$(PYTHON) -m venv $(PYTHON_PACKAGING_VENV) && \
	. $(PYTHON_PACKAGING_VENV)/bin/activate && \
	pip install --upgrade pip && \
	pip install -r REQUIREMENTS.packaging.txt
	date > $(PYTHON_PACKAGING_VENV)/.created

packaging-env: $(PYTHON_PACKAGING_VENV)/.created

sdist: packaging-env
	. $(PYTHON_PACKAGING_VENV)/bin/activate && \
	rm -rf dist *.egg-info && \
	./setup.py sdist

_release: sdist
	. $(PYTHON_PACKAGING_VENV)/bin/activate && \
	twine upload dist/*

# testing #####################################################################
$(PYTHON_TESTING_ENV)/.created: REQUIREMENTS.qa.txt
	rm -rf $(PYTHON_TESTING_ENV) && \
	$(PYTHON) -m venv $(PYTHON_TESTING_ENV) && \
	. $(PYTHON_TESTING_ENV)/bin/activate && \
	pip install pip --upgrade && \
	pip install -r ./REQUIREMENTS.qa.txt && \
	date > $(PYTHON_TESTING_ENV)/.created

qa: $(PYTHON_TESTING_ENV)/.created
	. $(PYTHON_TESTING_ENV)/bin/activate && \
	black --check --diff . && \
	flake8
