SHELL := /bin/bash
SRC_DIR := src
TEST_DIR := tests
VENV_DIR := .venv
CONFIG_PATH := etc/config.json
BUILD_DIR := build
ARTIFACT := $(BUILD_DIR)/agent.zip

.PHONY: install test run invoke build clean

install:
	uv venv $(VENV_DIR)
	uv pip install -r requirements.txt

test:
	source $(VENV_DIR)/bin/activate && python -m pytest $(TEST_DIR)/ -v

run:
	source $(VENV_DIR)/bin/activate && \
	AGENT_CONFIG_PATH=$(CONFIG_PATH) \
	python -m src.handler

invoke:
	@echo "Sending test prompt to local agent..."
	@curl -s -X POST http://localhost:8080/invoke \
		-H "Content-Type: application/json" \
		-d '{"prompt": "Hello, what can you help me with?"}' | jq .

build:
	rm -rf $(BUILD_DIR)
	mkdir -p $(BUILD_DIR)/package
	cp -r $(SRC_DIR) $(BUILD_DIR)/package/
	source $(VENV_DIR)/bin/activate && \
		pip install -r requirements.txt -t $(BUILD_DIR)/package/
	cd $(BUILD_DIR)/package && zip -r ../agent.zip . -x '*.pyc' '__pycache__/*'
	@echo "Built artifact: $(ARTIFACT)"

clean:
	rm -rf $(BUILD_DIR) $(VENV_DIR)
