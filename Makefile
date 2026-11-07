.PHONY: install run up stop down initdb migration-create migration-apply migration-down migration-current migration-history create-admin notifications-cleanup fcm-worker fcm-worker-once test-notifications

ifneq (,$(wildcard ./.env))
    include .env
    export
endif

VENV=.venv
PYTHON=$(VENV)/bin/python3

cmd-exists-%:
	@hash $(*) > /dev/null 2>&1 || \
		(echo "ERROR: '$(*)' must be installed and available on your PATH."; exit 1)

install:  ## Build and run Docker Compose services, then migrate forward to head
	docker compose build --no-cache
	docker compose up -d --force-recreate
	docker exec 321veganapi poetry run alembic upgrade head
	docker exec 321veganapi poetry run python -m scripts.create_admin_user

run: ## Build and run Docker Compose services
	docker compose build
	docker compose up

up:  ## Run Docker Compose services
	docker compose up

stop:	## Stop Docker Compose services
	docker compose stop

down:  ## Shutdown Docker Compose services
	docker compose down

initdb: ## Downgrade alambic to base and upgrade to head
	docker exec 321veganapi poetry run alembic downgrade base
	docker exec 321veganapi poetry run alembic upgrade head

migration-create: ## Generate alambic new migration
	docker exec 321veganapi poetry run alembic revision --autogenerate -m "new migration"

migration-apply: ## Apply alambic new migration
	docker exec 321veganapi poetry run alembic upgrade head

migration-down: ## Downgrade alambic last applied migration
	docker exec 321veganapi poetry run alembic downgrade -1

migration-current: ## Show alambic last applied migration
	docker exec 321veganapi poetry run alembic current

migration-history: ## Show alambic history
	docker exec 321veganapi poetry run alembic history

create-admin: ## Create the admin user
	docker exec 321veganapi poetry run python -m scripts.create_admin_user

notifications-cleanup: ## Delete notifications past their retention date
	docker exec 321veganapi poetry run python -m scripts.cleanup_notifications

fcm-worker: ## Build and start the FCM worker profile
	docker compose --profile fcm up -d --build 321veganfcmworker

fcm-worker-once: ## Process one FCM delivery batch and exit
	docker compose run --rm --no-deps 321veganfcmworker poetry run python -m scripts.fcm_worker --once

test-notifications: ## Run unit and isolated PostgreSQL concurrency tests (no real pushes)
	docker exec -e RUN_POSTGRES_NOTIFICATION_TESTS=1 321veganapi poetry run python -m unittest discover -s tests -v
