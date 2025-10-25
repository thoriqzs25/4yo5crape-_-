from flask import Flask, render_template, request, jsonify, send_file, Response, stream_with_context
import os
import json
from datetime import datetime, timedelta
from venue_scraper import VenueScraper
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
            'Processing all'
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

        # Run the scraper with stdout capture
        log_capture = LogCapture(log_callback, message_queue)
        with redirect_stdout(log_capture):
            scraper = VenueScraper(config)
            scraper.scrape_venues()

        # Get results
        venues_data = scraper.venues

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
        config = {
            'base_url': 'https://ayo.co.id',
            'venues_path': '/venues',
            'sortby': int(data.get('sortby', 5)),
            'tipe': 'venue',
            'lokasi': data.get('lokasi', ''),
            'cabor': int(data.get('cabor', 7)),
            'max_venues_to_test': int(data.get('max_venues', 0)),
            'use_selenium': False,  # Always use API mode (faster and more reliable)
            'use_api': True,  # Always use API mode
            'date': data.get('date', datetime.now().strftime('%Y-%m-%d')),
            'max_pages': int(data.get('max_pages', 1)),
            'start_time': data.get('start_time', ''),  # Optional start time filter (HH:MM format)
            'end_time': data.get('end_time', ''),  # Optional end time filter (HH:MM format)
            'cheapest_first': data.get('cheapest_first', False)  # Sort results by cheapest first
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

def generate_output_text(venues_data, config):
    """Generate formatted output text similar to the original script"""
    output = []
    output.append("=" * 80)
    output.append(f"VENUE SCRAPING RESULTS")
    output.append(f"Date: {config['date']}")
    output.append(f"Location: {config['lokasi'] or 'All Locations'}")
    output.append(f"Sport: {'Tennis' if config['cabor'] == 7 else 'Padel' if config['cabor'] == 12 else config['cabor']}")
    output.append(f"Total venues found: {len(venues_data)}")
    if config.get('cheapest_first'):
        output.append(f"Sorted by: Cheapest First")
    output.append("=" * 80)
    output.append("")

    # If cheapest_first is enabled, collect and sort all slots by price
    if config.get('cheapest_first'):
        all_slots = []
        for venue in venues_data:
            venue_name = venue['name']
            venue_url = venue['url']

            # Collect slots from available_fields
            if 'available_fields' in venue and venue['available_fields']:
                for field in venue['available_fields']:
                    field_name = field.get('field_name', 'Unknown Field')
                    if field.get('time_slots'):
                        for slot in field['time_slots']:
                            all_slots.append({
                                'venue_name': venue_name,
                                'venue_url': venue_url,
                                'field_name': field_name,
                                'start_time': slot.get('start_time', 'N/A'),
                                'end_time': slot.get('end_time', 'N/A'),
                                'price': slot.get('price', 0)
                            })
            # Collect slots from time_slots (fallback)
            elif 'time_slots' in venue and venue['time_slots']:
                if isinstance(venue['time_slots'][0], dict):
                    for slot in venue['time_slots']:
                        all_slots.append({
                            'venue_name': venue_name,
                            'venue_url': venue_url,
                            'field_name': slot.get('field_name', 'Unknown'),
                            'start_time': slot.get('start_time', 'N/A'),
                            'end_time': slot.get('end_time', 'N/A'),
                            'price': slot.get('price', 0)
                        })

        # Sort slots by price (ascending)
        all_slots.sort(key=lambda x: int(x['price']) if x['price'] and str(x['price']).isdigit() else float('inf'))

        # Display sorted slots
        for i, slot in enumerate(all_slots, 1):
            price = slot['price']
            if price and price != 'N/A':
                try:
                    price_formatted = f"Rp {int(price):,}"
                except:
                    price_formatted = str(price)
            else:
                price_formatted = 'Price not available'

            output.append(f"{i}. {slot['venue_name']} - {slot['field_name']}")
            output.append(f"   Time: {slot['start_time']} - {slot['end_time']}  |  {price_formatted}")
            output.append(f"   URL: {slot['venue_url']}")
            output.append("")

        return "\n".join(output)

    for i, venue in enumerate(venues_data, 1):
        output.append(f"{i}. {venue['name']}")
        output.append(f"   URL: {venue['url']}")
        if venue.get('venue_id'):
            output.append(f"   Venue ID: {venue['venue_id']}")

        # Check if venue was scraped or not
        was_scraped = ('available_fields' in venue) or ('time_slots' in venue) or ('slot_status' in venue)

        if not was_scraped:
            output.append(f"   Status: Not scraped")
            output.append("")
            continue

        # Check for available_fields (API mode data structure)
        if 'available_fields' in venue and venue['available_fields']:
            output.append(f"   \n   AVAILABLE SLOTS:")
            for field in venue['available_fields']:
                field_name = field.get('field_name', 'Unknown Field')
                field_status = field.get('slot_status', 'Unknown')
                output.append(f"\n   Field: {field_name} ({field_status})")

                # Show time slots for this field
                if field.get('time_slots'):
                    output.append(f"   Available Hours & Prices:")
                    for slot in field['time_slots']:
                        start = slot.get('start_time', 'N/A')
                        end = slot.get('end_time', 'N/A')
                        price = slot.get('price', 'N/A')
                        # Format price with thousands separator
                        if price != 'N/A' and price != '':
                            try:
                                price_formatted = f"Rp {int(price):,}"
                            except:
                                price_formatted = price
                        else:
                            price_formatted = 'Price not available'
                        output.append(f"      • {start} - {end}  |  {price_formatted}")

        # Fallback for time_slots (Selenium mode or old data structure)
        elif 'time_slots' in venue and venue['time_slots']:
            output.append(f"\n   AVAILABLE SLOTS ({len(venue['time_slots'])} slots):")

            # Check if time_slots are objects (with detailed info) or just strings
            if isinstance(venue['time_slots'][0], dict):
                # Group slots by field name for better readability
                slots_by_field = {}
                for slot in venue['time_slots']:
                    field = slot.get('field_name', 'Unknown')
                    if field not in slots_by_field:
                        slots_by_field[field] = []
                    slots_by_field[field].append(slot)

                # Display slots grouped by field
                for field_name, slots in slots_by_field.items():
                    output.append(f"\n   Field: {field_name}")
                    output.append(f"   Available Hours & Prices:")
                    for slot in slots:
                        start = slot.get('start_time', 'N/A')
                        end = slot.get('end_time', 'N/A')
                        price = slot.get('price', 'N/A')
                        # Format price with thousands separator
                        if price != 'N/A' and price != '':
                            try:
                                price_formatted = f"Rp {int(price):,}"
                            except:
                                price_formatted = price
                        else:
                            price_formatted = 'Price not available'
                        output.append(f"      • {start} - {end}  |  {price_formatted}")
            else:
                # If time_slots are strings, display them as before
                for slot in venue['time_slots']:
                    output.append(f"      - {slot}")
        elif 'slot_status' in venue:
            # Venue was checked but has no slots
            output.append(f"   Status: {venue['slot_status']}")
        else:
            output.append(f"   Status: Not scraped")

        output.append("")

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
    port = int(os.environ.get('PORT', 3000))
    app.run(host='0.0.0.0', port=port, debug=True)
