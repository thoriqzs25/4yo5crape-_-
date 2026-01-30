from flask import Flask, render_template, request, jsonify, send_file, Response, stream_with_context
import os
import json
from datetime import datetime, timedelta
from venue_scraper import VenueScraper
from gelora_scraper import GeloraScraper
import io
import sys
from contextlib import redirect_stdout
import requests
import threading
import queue
import uuid
import time

app = Flask(__name__)

# Store for progress logs and scraping sessions
progress_logs = {}
scraping_sessions = {}

# Rate limiting configuration
RATE_LIMIT_SECONDS = 120  # 2 minutes cooldown
rate_limit_store = {}  # {ip_address: last_scrape_timestamp}

@app.route('/')
def index():
    return render_template('index.html')

class LogCapture(io.StringIO):
    """Custom StringIO that also sends logs to a callback"""
    def __init__(self, callback, message_queue=None):
        super().__init__()
        self.callback = callback
        self.message_queue = message_queue

    def write(self, s):
        super().write(s)
        if s.strip():  # Only send non-empty lines
            self.callback(s)
            if self.message_queue:
                # Send to SSE queue
                self.message_queue.put(s.strip())
        return len(s)

def filter_progress_logs(logs):
    """Filter logs to show only relevant progress information"""
    lines = logs.split('\n') if isinstance(logs, str) else [logs]
    filtered = []

    # Keywords to skip (very verbose/debug info)
    skip_keywords = [
        'API URL:',
        'Found count_drop',
        'innerHTML',
        'Selenium',
        'WebDriver',
        'field_id',
        'sport_id'
    ]

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Skip verbose debug lines
        if any(keyword in line for keyword in skip_keywords):
            continue

        # Keep most progress lines - this is less aggressive filtering
        if any(keyword in line for keyword in [
            'Found venue:',
            'Scraping page',
            'Processing:',
            'Checking slots',
            'Total venues',
            'Page',
            'Field:',
            'slot available',
            '✅', '❌',
            'Scraping completed',
            'available fields',
            'Processing all',
            '[AYO]',
            '[GELORA]',
            'Gelora scraper',
            'Gelora scraping',
            'Fetching date:',
            'total slots'
        ]):
            filtered.append(line)

    if not filtered:
        return None  # Return None instead of a placeholder to avoid duplicate messages

    return '\n'.join(filtered)

def run_scraper_thread(session_id, config):
    """Run the scraper in a background thread"""
    try:
        session = scraping_sessions[session_id]
        message_queue = session['queue']

        def log_callback(msg):
            pass  # LogCapture will handle the queue directly

        # Run the scraper(s) with stdout capture
        log_capture = LogCapture(log_callback, message_queue)
        platform = config.get('platform', 'ayo')

        with redirect_stdout(log_capture):
            venues_data = []

            if platform in ('ayo', 'all'):
                print("=" * 40)
                print("[AYO] Starting AYO scraper...")
                print("=" * 40)
                ayo_scraper = VenueScraper(config)
                ayo_scraper.scrape_venues()
                for v in ayo_scraper.venues:
                    v['platform'] = 'ayo'
                venues_data.extend(ayo_scraper.venues)

            if platform in ('gelora', 'all'):
                print("=" * 40)
                print("[GELORA] Starting Gelora scraper...")
                print("=" * 40)
                gelora_scraper = GeloraScraper(config)
                gelora_scraper.scrape_venues()
                for v in gelora_scraper.venues:
                    v['platform'] = 'gelora'
                venues_data.extend(gelora_scraper.venues)

        # Generate output text
        output_text = generate_output_text(venues_data, config)

        # Store results in session
        session['completed'] = True
        session['success'] = True
        session['data'] = venues_data
        session['output'] = output_text
        session['count'] = len(venues_data)

        # Send completion message
        message_queue.put('__COMPLETE__')

    except Exception as e:
        import traceback
        session = scraping_sessions.get(session_id)
        if session:
            session['completed'] = True
            session['success'] = False
            error_detail = f"{str(e)}\n{traceback.format_exc()}"
            session['error'] = error_detail
            session['queue'].put(f'__ERROR__: {str(e)}')

def get_client_ip():
    """Get the client's IP address, handling proxies"""
    if request.headers.get('X-Forwarded-For'):
        # If behind a proxy, get the original IP
        ip = request.headers.get('X-Forwarded-For').split(',')[0].strip()
    elif request.headers.get('X-Real-IP'):
        ip = request.headers.get('X-Real-IP')
    else:
        ip = request.remote_addr
    return ip

def check_rate_limit(ip):
    """Check if IP is rate limited. Returns (allowed, seconds_remaining)"""
    current_time = time.time()

    # Clean up old entries (older than rate limit period)
    cleanup_time = current_time - (RATE_LIMIT_SECONDS * 2)
    to_delete = [ip_addr for ip_addr, timestamp in rate_limit_store.items()
                 if timestamp < cleanup_time]
    for ip_addr in to_delete:
        del rate_limit_store[ip_addr]

    if ip in rate_limit_store:
        last_scrape = rate_limit_store[ip]
        time_since_last = current_time - last_scrape

        if time_since_last < RATE_LIMIT_SECONDS:
            seconds_remaining = int(RATE_LIMIT_SECONDS - time_since_last) + 1
            return False, seconds_remaining

    return True, 0

def update_rate_limit(ip):
    """Update the last scrape time for an IP"""
    rate_limit_store[ip] = time.time()

@app.route('/scrape/check-limit', methods=['GET'])
def check_scrape_limit():
    """Check if the user can scrape based on rate limiting"""
    client_ip = get_client_ip()
    allowed, seconds_remaining = check_rate_limit(client_ip)

    return jsonify({
        'allowed': allowed,
        'seconds_remaining': seconds_remaining,
        'rate_limit_seconds': RATE_LIMIT_SECONDS
    })

@app.route('/scrape', methods=['POST'])
def scrape():
    try:
        # Rate limiting check
        client_ip = get_client_ip()
        allowed, seconds_remaining = check_rate_limit(client_ip)

        if not allowed:
            return jsonify({
                'success': False,
                'error': f'Rate limit exceeded. Please wait {seconds_remaining} seconds before scraping again.',
                'rate_limited': True,
                'seconds_remaining': seconds_remaining
            }), 429

        # Get form data
        data = request.get_json()

        # Build config from form inputs
        platform = data.get('platform', 'ayo')

        config = {
            'base_url': 'https://ayo.co.id',
            'venues_path': '/venues',
            'sortby': int(data.get('sortby') or 5),
            'tipe': 'venue',
            'lokasi': data.get('lokasi', ''),
            'cabor': int(data.get('cabor') or 7),
            'max_venues_to_test': int(data.get('max_venues') or 0),
            'use_selenium': False,  # Always use API mode (faster and more reliable)
            'use_api': True,  # Always use API mode
            'start_date': data.get('start_date') or datetime.now().strftime('%Y-%m-%d'),
            'end_date': data.get('end_date') or datetime.now().strftime('%Y-%m-%d'),
            'max_pages': int(data.get('max_pages') or 1),
            'start_time': data.get('start_time', ''),  # Optional start time filter (HH:MM format)
            'end_time': data.get('end_time', ''),  # Optional end time filter (HH:MM format)
            'cheapest_first': data.get('cheapest_first', False),  # Sort results by cheapest first
            'platform': platform
        }

        # Update rate limit for this IP
        update_rate_limit(client_ip)

        # Create a new scraping session
        session_id = str(uuid.uuid4())
        message_queue = queue.Queue()

        scraping_sessions[session_id] = {
            'queue': message_queue,
            'completed': False,
            'success': False,
            'data': None,
            'output': None,
            'count': 0
        }

        # Start scraping in background thread
        thread = threading.Thread(target=run_scraper_thread, args=(session_id, config))
        thread.daemon = True
        thread.start()

        return jsonify({
            'success': True,
            'session_id': session_id
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/scrape/progress/<session_id>')
def scrape_progress(session_id):
    """Server-Sent Events endpoint for scraping progress"""
    session = scraping_sessions.get(session_id)
    if not session:
        return jsonify({'error': 'Invalid session ID'}), 404

    def generate():
        message_queue = session['queue']
        while True:
            try:
                # Wait for a message with timeout
                message = message_queue.get(timeout=1)

                if message == '__COMPLETE__':
                    # Send completion event
                    yield f"event: complete\ndata: {json.dumps({'success': True})}\n\n"
                    break
                elif message.startswith('__ERROR__:'):
                    # Send error event
                    error_msg = message.replace('__ERROR__: ', '')
                    yield f"event: error\ndata: {json.dumps({'error': error_msg})}\n\n"
                    break
                elif message.startswith('__PROGRESS__:'):
                    # Send progress event — format: __PROGRESS__:platform:current:total
                    parts = message.split(':')
                    if len(parts) == 4:
                        plat = parts[1]
                        current = int(parts[2])
                        total = int(parts[3])
                    else:
                        plat = 'ayo'
                        current = int(parts[1])
                        total = int(parts[2])
                    pct = int((current / total) * 100) if total > 0 else 0
                    yield f"event: progress\ndata: {json.dumps({'platform': plat, 'current': current, 'total': total, 'percent': pct})}\n\n"
                else:
                    # Filter and send progress message
                    filtered = filter_progress_logs(message)
                    if filtered:
                        yield f"data: {json.dumps({'message': filtered})}\n\n"
            except queue.Empty:
                # Send heartbeat to keep connection alive
                yield f": heartbeat\n\n"

                # Check if session completed while we were waiting
                if session.get('completed'):
                    if session.get('success'):
                        yield f"event: complete\ndata: {json.dumps({'success': True})}\n\n"
                    else:
                        yield f"event: error\ndata: {json.dumps({'error': session.get('error', 'Unknown error')})}\n\n"
                    break

    return Response(stream_with_context(generate()), mimetype='text/event-stream')

@app.route('/scrape/result/<session_id>')
def scrape_result(session_id):
    """Get the final result of a scraping session"""
    session = scraping_sessions.get(session_id)
    if not session:
        return jsonify({'error': 'Invalid session ID'}), 404

    if not session.get('completed'):
        return jsonify({'error': 'Scraping not yet completed'}), 400

    if not session.get('success'):
        return jsonify({
            'success': False,
            'error': session.get('error', 'Unknown error')
        }), 500

    return jsonify({
        'success': True,
        'data': session['data'],
        'output': session['output'],
        'count': session['count']
    })

def _get_venue_min_price(venue):
    """Get the minimum slot price for a venue (for cheapest-first sorting)."""
    min_price = float('inf')
    if venue.get('available_fields'):
        for field in venue['available_fields']:
            for slot in field.get('time_slots', []):
                try:
                    p = int(slot.get('price', 0))
                    if p > 0:
                        min_price = min(min_price, p)
                except (ValueError, TypeError):
                    pass
    elif venue.get('time_slots') and isinstance(venue['time_slots'][0], dict):
        for slot in venue['time_slots']:
            try:
                p = int(slot.get('price', 0))
                if p > 0:
                    min_price = min(min_price, p)
            except (ValueError, TypeError):
                pass
    return min_price

def _format_price(price):
    """Format price with thousands separator: 150000 -> 'Rp 150,000'"""
    if price is None or price == 'N/A' or price == '':
        return 'Price not available'
    try:
        p = int(price)
        if p <= 0:
            return 'Price not available'
        return f"Rp {p:,}"
    except (ValueError, TypeError):
        return str(price)

def _render_venue_block(venue, index, platform, output):
    """Render a single venue block in the standard grouped format."""
    ptag = f"[{venue.get('platform', 'ayo').upper()}] " if platform == 'all' else ''
    output.append(f"{index}. {ptag}{venue['name']}")
    output.append(f"   URL: {venue['url']}")
    if venue.get('venue_id'):
        output.append(f"   Venue ID: {venue['venue_id']}")

    was_scraped = ('available_fields' in venue) or ('time_slots' in venue) or ('slot_status' in venue)

    if not was_scraped:
        output.append(f"   Status: Not scraped")
        output.append("")
        return

    if 'available_fields' in venue and venue['available_fields']:
        output.append(f"   \n   AVAILABLE SLOTS:")
        for field in venue['available_fields']:
            field_name = field.get('field_name', 'Unknown Field')
            field_status = field.get('slot_status', 'Unknown')
            output.append(f"\n   Field: {field_name} ({field_status})")

            if field.get('time_slots'):
                output.append(f"   Available Hours & Prices:")
                for slot in field['time_slots']:
                    date = slot.get('date', '')
                    start = slot.get('start_time', 'N/A')
                    end = slot.get('end_time', 'N/A')
                    price_formatted = _format_price(slot.get('price', 'N/A'))
                    date_prefix = f"{date}  " if date else ""
                    output.append(f"      • {date_prefix}{start} - {end}  |  {price_formatted}")

    elif 'time_slots' in venue and venue['time_slots']:
        if isinstance(venue['time_slots'][0], dict):
            slots_by_field = {}
            for slot in venue['time_slots']:
                field = slot.get('field_name', 'Unknown')
                if field not in slots_by_field:
                    slots_by_field[field] = []
                slots_by_field[field].append(slot)

            output.append(f"\n   AVAILABLE SLOTS ({len(venue['time_slots'])} slots):")
            for field_name, slots in slots_by_field.items():
                output.append(f"\n   Field: {field_name}")
                output.append(f"   Available Hours & Prices:")
                for slot in slots:
                    date = slot.get('date', '')
                    start = slot.get('start_time', 'N/A')
                    end = slot.get('end_time', 'N/A')
                    price_formatted = _format_price(slot.get('price', 'N/A'))
                    date_prefix = f"{date}  " if date else ""
                    output.append(f"      • {date_prefix}{start} - {end}  |  {price_formatted}")
        else:
            output.append(f"\n   AVAILABLE SLOTS:")
            for slot in venue['time_slots']:
                output.append(f"      - {slot}")
    elif 'slot_status' in venue:
        output.append(f"   Status: {venue['slot_status']}")
    else:
        output.append(f"   Status: Not scraped")

    output.append("")

def generate_output_text(venues_data, config):
    """Generate formatted output text.

    Both normal and cheapest-first modes use the same grouped format
    (venue -> field -> slots). Cheapest-first sorts venues by their
    cheapest available slot price.
    """
    all_venues = venues_data
    venues_with_slots = [
        v for v in all_venues
        if v.get('available_fields') or v.get('time_slots')
    ]
    venues_no_slots = [
        v for v in all_venues
        if not (v.get('available_fields') or v.get('time_slots'))
    ]
    venues_data = venues_with_slots

    platform = config.get('platform', 'ayo')
    platform_label = {'ayo': 'AYO', 'gelora': 'Gelora', 'all': 'AYO + Gelora'}.get(platform, platform)

    output = []
    output.append("=" * 80)
    output.append(f"VENUE SCRAPING RESULTS")
    start_date = config.get('start_date', config.get('date', 'N/A'))
    end_date = config.get('end_date', start_date)
    if start_date == end_date:
        output.append(f"Date: {start_date}")
    else:
        output.append(f"Date: {start_date} to {end_date}")
    output.append(f"Location: {config['lokasi'] or 'All Locations'}")
    output.append(f"Sport: {'Tennis' if config['cabor'] == 7 else 'Padel' if config['cabor'] == 12 else 'Pickleball' if config['cabor'] == 15 else config['cabor']}")
    output.append(f"Platform: {platform_label}")
    output.append(f"Total venues checked: {len(all_venues)}")
    output.append(f"Venues with available slots: {len(venues_data)}")
    output.append(f"Venues with no slots: {len(venues_no_slots)}")
    if config.get('cheapest_first'):
        output.append(f"Sorted by: Cheapest First")
    output.append("=" * 80)

    # List venues with no available slots
    if venues_no_slots:
        output.append("")
        output.append(f"--- Checked but no slots available ({len(venues_no_slots)}) ---")
        for v in venues_no_slots:
            output.append(f"  - {v['name']} ({v['url']})")

    output.append("")

    # If cheapest_first, sort venues by their minimum slot price
    if config.get('cheapest_first'):
        venues_data = sorted(venues_data, key=_get_venue_min_price)

    # Render each venue in the same grouped format
    for i, venue in enumerate(venues_data, 1):
        _render_venue_block(venue, i, platform, output)

    return "\n".join(output)

@app.route('/autocity')
def autocity():
    """Proxy endpoint for city autocomplete"""
    try:
        term = request.args.get('term', '')
        if not term:
            return jsonify([])

        # Call the ayo.co.id autocity API
        response = requests.get(f'https://ayo.co.id/autocity?term={term}', timeout=5)
        response.raise_for_status()

        return jsonify(response.json())

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download/<format>')
def download(format):
    """Download results in different formats"""
    try:
        # Check if venues_data.json exists
        if not os.path.exists('venues_data.json'):
            return jsonify({'error': 'No data available. Please run scrape first.'}), 404

        with open('venues_data.json', 'r') as f:
            data = json.load(f)

        if format == 'json':
            return send_file('venues_data.json', as_attachment=True, download_name='venues_data.json')
        elif format == 'txt':
            if os.path.exists('venues_output.txt'):
                return send_file('venues_output.txt', as_attachment=True, download_name='venues_output.txt')
            else:
                return jsonify({'error': 'Text output not available'}), 404
        else:
            return jsonify({'error': 'Invalid format'}), 400

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3001))
    app.run(host='0.0.0.0', port=port, debug=True)
