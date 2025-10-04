# AYO Venue Scraper Makefile

.PHONY: run setup help

# Default target
run:
	source venv/bin/activate && python venue_scraper.py

# Setup virtual environment and install dependencies
setup:
	python3 -m venv venv
	source venv/bin/activate && pip install -r requirements.txt --break-system-packages

# Help target
help:
	@echo "Available targets:"
	@echo "  setup  - Create virtual environment and install dependencies"
	@echo "  run    - Run the venue scraper"
	@echo "  help   - Show this help message"
