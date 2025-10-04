# AYO Venue Scraper Makefile

.PHONY: run dry-run setup help

# Default target
run:
	source venv/bin/activate && source config.env && python venue_scraper.py

# Dry run to preview what will be scraped
dry-run:
	source venv/bin/activate && source config.env && python venue_scraper.py --dry-run

# Setup virtual environment and install dependencies
setup:
	python3 -m venv venv
	source venv/bin/activate && pip install -r requirements.txt --break-system-packages

# Help target
help:
	@echo "Available targets:"
	@echo "  setup    - Create virtual environment and install dependencies"
	@echo "  run      - Run the venue scraper"
	@echo "  dry-run  - Preview what will be scraped without actually scraping"
	@echo "  help     - Show this help message"
