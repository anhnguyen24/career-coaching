cat > Makefile << 'EOF'
.PHONY: install lint test build up down

install:
	pip install pre-commit && pre-commit install

lint:
	pre-commit run --all-files

test:
	pytest apps/ --coverage

up:
	docker compose up --build

down:
	docker compose down
EOF
