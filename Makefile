# Detect Windows native Make while letting WSL use the Unix scripts.
ifeq ($(OS),Windows_NT)
ifeq ($(wildcard /proc/version),)
WINDOWS_NATIVE := 1
endif
endif

# Use the virtualenv's dbt executable for the current platform.
ifeq ($(WINDOWS_NATIVE),1)
DBT := .venv/Scripts/dbt.exe
else
DBT := .venv/bin/dbt
endif

.PHONY: setup up down logs dbt-test dbt-run

# Prepare the local environment and start the project services.
setup:
ifeq ($(WINDOWS_NATIVE),1)
	powershell.exe -NoProfile -ExecutionPolicy Bypass -File setup.ps1
else
	./setup.sh
endif

# Start or stop the Docker Compose stack.
up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

# Run dbt commands against the project under dbt_harvest.
dbt-test:
	$(DBT) test --project-dir dbt_harvest

dbt-run:
	$(DBT) run --project-dir dbt_harvest
