# AYO Slots Utopia

Web scraper for [ayo.co.id](https://ayo.co.id), an Indonesian sports venue booking platform. Scrapes venue listings (tennis, padel, pickleball), extracts slot availability, and filters by sport, location, time range, and price.

## Tech Stack

- **Backend:** Python 3.11, Flask, BeautifulSoup4, Selenium, Requests, Gunicorn
- **Frontend:** Vanilla HTML/CSS/JS single-page app with Server-Sent Events (SSE) for real-time progress
- **Deployment:** Render (primary), Vercel, Heroku, Replit

## Project Structure

```
ayo-scrape/
├── app.py                      # Flask web app: routes, SSE progress, rate limiting, session management
├── venue_scraper.py            # Main scraper: multi-page venue discovery, slot extraction, API/Selenium modes
├── single_venue_scraper.py     # Selenium-based single venue scraper with CABOR field filtering
├── templates/
│   └── index.html              # Full SPA frontend (~1000 lines): form, progress, results display
├── api/
│   └── index.py                # Vercel serverless entry point (imports Flask app)
├── static/                     # Static assets directory
├── config.env                  # Local environment configuration
├── sample.env                  # Example env file
├── requirements.txt            # Python dependencies
├── runtime.txt                 # Python version (3.11.0)
├── Makefile                    # Dev commands: run, dry-run, setup, web, help
├── Procfile                    # Heroku deployment
├── render.yaml                 # Render deployment (Singapore region, free tier)
├── vercel.json                 # Vercel deployment
├── .replit                     # Replit config
├── .github/workflows/deploy.yml # GitHub Actions CI/CD
├── knowledge.txt               # Detailed scraping knowledge base
├── venues_data.json            # Output: scraped data (generated)
├── venues_output.txt           # Output: formatted results (generated)
└── single_venue_result.json    # Output: single venue test result
```

## Key Components

### `venue_scraper.py` — Main Orchestrator

`VenueScraper` class handles the full scraping workflow:

- `build_venues_url(page)` — Constructs search URLs. Uses manual `&`-joining (not `urlencode`) because ayo.co.id expects `+` not `%2B`.
- `scrape_venues(max_pages)` — Multi-page venue list scraping with pagination. Calls `process_venue_slots()` after discovery.
- `extract_venue_info(soup)` — Parses `div.venue-card-item` cards for name (from `img[alt]`), URL (from `a[href]`), and venue_id (from `id="venue-{id}"`).
- `get_venue_slot_info_api(venue_id, venue_name)` — **Primary method.** Calls `GET /venues-ajax/op-times-and-fields?venue_id={id}&date={date}` JSON API. Filters by `sport_id` matching `cabor` config. Applies time range filtering.
- `get_venue_slot_info(venue_url)` — Static HTML fallback for slot extraction.
- `is_slot_within_time_range(slot_start_time)` — Filters slots by `start_time`/`end_time` config (HH:MM format, inclusive).
- `process_venue_slots()` — Routes to API, Selenium, or static scraping based on config.
- `save_results()` — Writes `venues_output.txt` with hierarchical format (venue > field > slots). Only includes venues with available slots.
- `dry_run()` — Preview mode: shows pages, venue count, config summary without scraping. Triggered via `--dry-run` CLI flag.
- `get_total_pages(soup)` — Extracts pagination from `div#venue-pagination`.

Entry point: `main()` reads config from `config.env` or env vars, runs dry-run or full scrape.

### `single_venue_scraper.py` — Selenium Scraper

`SingleVenueScraper` class for browser-automated scraping:

- Headless Chrome with `WebDriverWait` for JS-rendered content
- Waits for `div#field-list-container` to populate
- Extracts fields from `div.field-container` elements
- Sport type detection: checks `div.field_desc_point` text for "tennis"/"padel", falls back to `sport` attribute
- CABOR filtering via `should_include_field()`: CABOR 7=Tennis only, 12=Padel only, other=all
- Time slots from `div.field-slot-item` — **uses `is-disabled` attribute** (not CSS class) to detect availability
- Falls back to static scraping if Selenium unavailable

### `app.py` — Flask Web Application

Routes:
- `GET /` — Serves `index.html`
- `POST /scrape` — Starts scraping session. Accepts JSON body with: `sortby`, `lokasi`, `cabor`, `max_venues`, `date`, `max_pages`, `start_time`, `end_time`, `cheapest_first`. Returns `session_id`. Always uses API mode.
- `GET /scrape/progress/<session_id>` — SSE endpoint streaming real-time log messages. Events: `data` (progress), `complete`, `error`.
- `GET /scrape/result/<session_id>` — Returns final JSON results after scraping completes.
- `GET /scrape/check-limit` — Returns rate limit status for client IP.
- `GET /autocity?term=...` — Proxies city autocomplete from `ayo.co.id/autocity`.
- `GET /download/<format>` — Downloads results as `json` or `txt`.

Architecture:
- UUID-based sessions stored in `scraping_sessions` dict
- Background threading via `threading.Thread` (daemon)
- `LogCapture` class redirects stdout to `queue.Queue` for SSE streaming
- Rate limiting: 120s cooldown per IP (via `X-Forwarded-For`, `X-Real-IP`, or `remote_addr`)
- `generate_output_text()` formats results; supports `cheapest_first` sorting (flattens all slots, sorts by price)

### `templates/index.html` — Frontend SPA

- Responsive mobile-first design
- Multi-select city autocomplete with chip UI (calls `/autocity`)
- Sport selection: Tennis (cabor=7), Padel (cabor=12), Pickleball (cabor=15)
- Sort options: Popularity, Name A-Z, Name Z-A
- Time range filter: start/end dropdowns (00:00–24:00 in 30-min increments)
- Cheapest-first toggle
- Max pages and max venues controls
- Date picker
- Real-time progress log display via SSE with formatted output
- Results area with copy-to-clipboard and download buttons
- Rate limit countdown timer UI

## Configuration

Parameters (from `config.env`, env vars, or Flask request body):

| Parameter | Default | Description |
|---|---|---|
| `BASE_URL` | `https://ayo.co.id` | Target website |
| `VENUES_PATH` | `/venues` | Venues list endpoint |
| `SORTBY` | `5` | Sort method (5=Popularity) |
| `CABOR` | `7` | Sport: 7=Tennis, 12=Padel, 15=Pickleball |
| `LOKASI` | `""` | Location filter (empty=all). Uses `+` for spaces. |
| `DATE` | `2025-01-15` | Query date (YYYY-MM-DD) |
| `MAX_PAGES` | `1` | Pages to scrape (0=all) |
| `MAX_VENUES_TO_TEST` | `3` | Venues to process (0=all) |
| `USE_API` | `False` | Use JSON API for slot data (CLI default off, web always on) |
| `USE_SELENIUM` | `True` | Use browser automation |
| `START_TIME` | `""` | Filter slots >= this time (HH:MM) |
| `END_TIME` | `""` | Filter slots <= this time (HH:MM) |
| `CHEAPEST_FIRST` | `False` | Sort output by price ascending (web only) |

Config priority: environment variables > `config.env` file > hardcoded defaults.

## Data Flow

1. `VenueScraper` fetches venue listing pages from `/venues?sortby=...&cabor=...&lokasi=...`
2. Parses `div.venue-card-item` for venue name, URL, and ID
3. For each venue, calls `/venues-ajax/op-times-and-fields?venue_id={id}&date={date}` (API mode)
4. Filters fields by `sport_id` matching `cabor`, filters slots by `is_available == 1` and time range
5. Outputs to console, `venues_output.txt`, and `venues_data.json`

## AYO API Details

### Venue Listing
- **URL:** `https://ayo.co.id/venues?sortby={sortby}&tipe=venue&lokasi={lokasi}&cabor={cabor}&page={page}`
- **HTML selectors:** `div.venue-card-item`, `div#venue-pagination`, `.count_drop` (JS-populated venue count)

### Slot Availability API
- **URL:** `https://ayo.co.id/venues-ajax/op-times-and-fields?venue_id={id}&date={YYYY-MM-DD}`
- **Response:** JSON with `op_time` (operating hours) and `fields[]` array
- **Field object:** `field_id`, `field_name`, `sport_id` (7=Tennis, 12=Padel, 15=Pickleball), `total_available_slots`, `slots[]`
- **Slot object:** `id`, `start_time` (HH:MM:SS), `end_time`, `price` (integer IDR), `date`, `is_available` (1=yes)

### City Autocomplete
- **URL:** `https://ayo.co.id/autocity?term={search_term}`

## Critical Implementation Notes

- **URL encoding:** `+` must stay as `+` in URLs, not `%2B`. Manual query string building is required.
- **Disabled slots:** Use `is-disabled` HTML **attribute** (`"true"`/`"false"`), NOT CSS class detection.
- **JS-rendered content:** `field-list-container` and `count_drop` are empty in static HTML, populated by JavaScript. Selenium required for these.
- **Rate limiting:** 120s per IP. Web app always uses API mode (no Selenium).
- **Request throttling:** 1s delay between page fetches, 2s between venue slot requests.

## Running Locally

```bash
make setup      # Create venv + install deps
make run        # CLI scraper (uses config.env)
make dry-run    # Preview without scraping
make web        # Flask app on port 3000
```

## Deployment

- **Render (primary):** `render.yaml` — Gunicorn, 1 worker, 120s timeout, Singapore region
- **Vercel:** `vercel.json` + `api/index.py` serverless function
- **Heroku:** `Procfile`
- **GitHub Actions:** `.github/workflows/deploy.yml` — auto-deploy on push to main
