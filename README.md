## AYO SLOTS UTOPIA

A venue scraper for ayo.co.id with both CLI and web interface.

### Quick Start

**CLI Version:**
```bash
cp sample.env config.env
make setup && make run
```

**Web Interface:**
```bash
make setup && make web
```
Then open http://localhost:3000 in your browser.

### Available Commands

- `make setup` - Install dependencies
- `make run` - Run CLI scraper
- `make web` - Run web interface on port 3000
- `make dry-run` - Preview what will be scraped
- `make help` - Show all commands