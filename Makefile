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
	python3 -m pip install -e .[full] && \
	date > $(PYTHON_VENV)/.created

.PHONY: env clean server

env: $(PYTHON_VENV)/.created

clean:
	rm -rf $(PYTHON_VENV)
	rm -rf $(PYTHON_PACKAGING_VENV)
	rm -rf $(PYTHON_TESTING_ENV)

# Note that there is no check if any of the source files has changed,
# so you will have to manually run make clean to test any changes you
# have made.
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
	python3 -m pip install --upgrade pip && \
	python3 -m pip install -r REQUIREMENTS.packaging.txt
	date > $(PYTHON_PACKAGING_VENV)/.created

.PHONY: packaging-env build _release

packaging-env: $(PYTHON_PACKAGING_VENV)/.created

sdist: packaging-env
	. $(PYTHON_PACKAGING_VENV)/bin/activate && \
	rm -rf dist *.egg-info && \
	./setup.py sdist

_release: sdist
	. $(PYTHON_PACKAGING_VENV)/bin/activate && \
	twine upload dist/*

# testing #####################################################################
$(PYTHON_TESTING_ENV)/.created:
	rm -rf $(PYTHON_TESTING_ENV) && \
	$(PYTHON) -m venv $(PYTHON_TESTING_ENV) && \
	. $(PYTHON_TESTING_ENV)/bin/activate && \
	python3 -m pip install pip --upgrade && \
	python3 -m pip install ruff codespell && \
	date > $(PYTHON_TESTING_ENV)/.created

node_modules/.created:
	rm -rf node_modules && \
	npm install -D prettier prettier-plugin-toml && \
	date > node_modules/.created

.PHONY: qa qa-codespell qa-ruff qa-ruff-fix qa-prettier

qa: qa-codespell qa-ruff qa-prettier

qa-codespell: $(PYTHON_TESTING_ENV)/.created
	. $(PYTHON_TESTING_ENV)/bin/activate && \
	codespell

qa-ruff: $(PYTHON_TESTING_ENV)/.created
	. $(PYTHON_TESTING_ENV)/bin/activate && \
	ruff format --check --diff && ruff check

qa-ruff-fix: $(PYTHON_TESTING_ENV)/.created
	. $(PYTHON_TESTING_ENV)/bin/activate && \
	ruff format && ruff check --fix

qa-prettier: node_modules/.created
	npx prettier --check pyproject.toml
	npx prettier --check lxa_iobus/server/static/index.html
	npx prettier --check lxa_iobus/server/static/main.js
	npx prettier --check lxa_iobus/server/static/style.css
