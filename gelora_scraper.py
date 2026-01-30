import requests
from bs4 import BeautifulSoup
import time
import re
from datetime import datetime, timedelta


class GeloraScraper:
    """Scraper for gelora.id venue listing and slot availability.

    Two-phase approach:
    1. Listing pages (/venue?...) to discover venues and field IDs
    2. Field pages (/field/{id}?Date=...) to get per-slot prices
    """

    def __init__(self, config=None):
        self.config = config or {}
        self.base_url = 'https://www.gelora.id'
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
        })
        self.venues = []

    def format_date_gelora(self, date_str):
        """Convert YYYY-MM-DD to DD-MMM-YYYY (gelora format)"""
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        return dt.strftime('%d-%b-%Y')

    def get_date_range(self):
        """Generate list of date strings from start_date to end_date"""
        start = datetime.strptime(self.config['start_date'], '%Y-%m-%d')
        end = datetime.strptime(self.config['end_date'], '%Y-%m-%d')
        dates = []
        current = start
        while current <= end:
            dates.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)
        return dates

    def is_slot_within_time_range(self, slot_start_time):
        """Check if a slot's start time is within the configured time range"""
        start_filter = self.config.get('start_time', '').strip()
        end_filter = self.config.get('end_time', '').strip()

        if not start_filter and not end_filter:
            return True

        if not slot_start_time:
            return False

        try:
            def time_to_minutes(time_str):
                parts = time_str.split(':')
                return int(parts[0]) * 60 + int(parts[1])

            slot_minutes = time_to_minutes(slot_start_time)

            if start_filter:
                if slot_minutes < time_to_minutes(start_filter):
                    return False
            if end_filter:
                if slot_minutes > time_to_minutes(end_filter):
                    return False

            return True
        except (ValueError, IndexError):
            return False

    def get_page_content(self, url):
        """Fetch page content with error handling"""
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        except requests.RequestException as e:
            print(f"Error fetching {url}: {e}")
            return None

    def build_venues_url(self, page=1, date_gelora=None):
        """Build gelora venue listing URL"""
        params = ['sport=Tennis']

        lokasi = self.config.get('lokasi', '')
        if lokasi:
            city = lokasi.split(',')[0].replace('+', ' ')
            # Strip "Kota " prefix (AYO format) — gelora uses just city name
            if city.startswith('Kota '):
                city = city[5:]
            params.append(f"city={city}")

        if date_gelora:
            params.append(f"date={date_gelora}")

        if page > 1:
            params.append(f"page={page}")

        query = '&'.join(params)
        return f"{self.base_url}/venue?{query}"

    def get_total_pages(self, soup):
        """Extract total pages from pagination"""
        try:
            pagination = soup.find('div', class_='pagination')
            if not pagination:
                return 1

            last_link = pagination.find('a', class_='pagination__next')
            if last_link and last_link.get('href'):
                href = last_link['href']
                match = re.search(r'page=(\d+)', href)
                if match:
                    return int(match.group(1))

            max_page = 1
            for li in pagination.find_all('li'):
                link = li.find('a')
                if link and link.get('href'):
                    match = re.search(r'page=(\d+)', link['href'])
                    if match:
                        max_page = max(max_page, int(match.group(1)))
                elif li.get('class') and 'pagination__current' in li.get('class', []):
                    try:
                        max_page = max(max_page, int(li.text.strip()))
                    except ValueError:
                        pass

            return max_page
        except Exception as e:
            print(f"Error extracting total pages: {e}")
            return 1

    def extract_venues_info(self, soup):
        """Extract venue names, URLs, and field IDs from listing page.

        Does NOT extract slots — those come from field pages for accurate pricing.
        """
        venues_data = []
        venue_cards = soup.select('div.col-12.col-md-6.col-lg-4.mb-xs-3')

        for card in venue_cards:
            boxed = card.find('div', class_='boxed')
            if not boxed:
                continue

            product = boxed.find('div', class_='product')
            if not product:
                continue

            # Venue name and URL
            name_tag = product.find('h5', class_='text--darkblue')
            if not name_tag:
                name_tag = product.find('h5')
            venue_name = name_tag.text.strip() if name_tag else 'Unknown'

            venue_link = product.find('a', href=re.compile(r'^/v/'))
            venue_slug = venue_link['href'] if venue_link else ''
            venue_url = f"{self.base_url}{venue_slug}" if venue_slug else ''

            print(f"Found venue: {venue_name} -> {venue_url}")

            # Extract field IDs from field links
            field_links = boxed.select('a.feature.good-card-4')
            fields = []

            for field_link in field_links:
                field_h5 = field_link.find('h5', class_='mb-0')
                field_name = field_h5.text.strip() if field_h5 else 'Unknown Field'

                field_href = field_link.get('href', '')
                field_id = None
                match = re.search(r'/field/(\d+)', field_href)
                if match:
                    field_id = int(match.group(1))

                # Sport type
                field_span = field_link.find('span')
                sport_type = 'Tennis'
                if field_span:
                    span_text = field_span.get_text().strip()
                    if '\u25e6' in span_text:
                        sport_type = span_text.split('\u25e6')[0].strip()
                    elif span_text:
                        sport_type = span_text.split()[0] if span_text.split() else 'Tennis'

                # Only tennis fields
                if sport_type.lower() not in ('tenis', 'tennis'):
                    continue

                if field_id:
                    fields.append({
                        'field_id': field_id,
                        'field_name': field_name,
                        'sport_type': sport_type
                    })

            venues_data.append({
                'name': venue_name,
                'url': venue_url,
                'fields': fields
            })

        return venues_data

    def get_field_slots(self, field_id):
        """Fetch /field/{field_id}?Date=... and parse available slots with prices.

        The field page contains ~30 days of slot data with input.timeTableItem
        elements that have data-price, data-starttime, data-endtime, data-date.
        One request per field covers the entire date range.
        """
        date_gelora = self.format_date_gelora(self.config['start_date'])
        url = f"{self.base_url}/field/{field_id}?Date={date_gelora}"

        soup = self.get_page_content(url)
        if not soup:
            return []

        valid_dates = set(self.get_date_range())
        slots = []

        for inp in soup.select('input.timeTableItem'):
            raw_date = inp.get('data-date', '')  # e.g. "30-Jan-2026"
            try:
                dt = datetime.strptime(raw_date, '%d-%b-%Y')
                slot_date = dt.strftime('%Y-%m-%d')
            except ValueError:
                continue

            # Filter by date range
            if slot_date not in valid_dates:
                continue

            start_time = inp.get('data-starttime', '')
            end_time = inp.get('data-endtime', '')
            price = int(inp.get('data-price', 0) or 0)
            field_name = inp.get('data-fieldname', '')

            # Apply time range filter
            if not self.is_slot_within_time_range(start_time):
                continue

            slots.append({
                'slot_id': None,
                'date': slot_date,
                'start_time': start_time,
                'end_time': end_time,
                'price': price,
                'field_name': field_name
            })

        return slots

    def scrape_venues(self, max_pages=None):
        """Scrape venues from gelora.id: discover from listing, fetch field pages for prices"""
        if max_pages is None:
            max_pages = self.config.get('max_pages', 1)

        dates = self.get_date_range()
        print(f"Starting Gelora scraper for {len(dates)} date(s)")
        print(f"Sport: Tennis | Location: {self.config.get('lokasi', 'All')}")

        # Phase 1: Discover venues and field IDs from listing pages
        first_date_gelora = self.format_date_gelora(dates[0])
        first_url = self.build_venues_url(page=1, date_gelora=first_date_gelora)
        print(f"Fetching URL: {first_url}")

        soup = self.get_page_content(first_url)
        if not soup:
            print("Failed to fetch first page")
            return

        total_pages = self.get_total_pages(soup)
        if max_pages == 0:
            pages_to_scrape = total_pages
        else:
            pages_to_scrape = min(max_pages, total_pages)

        print(f"Total pages: {total_pages}, scraping {pages_to_scrape} page(s)")

        # Collect unique venues by URL
        venue_map = {}
        page_venues = self.extract_venues_info(soup)
        for v in page_venues:
            venue_map[v['url']] = v
        print(f"Page 1: {len(page_venues)} venues")

        for page_num in range(2, pages_to_scrape + 1):
            print(f"Scraping page {page_num}...")
            page_url = self.build_venues_url(page=page_num, date_gelora=first_date_gelora)
            page_soup = self.get_page_content(page_url)
            if page_soup:
                pv = self.extract_venues_info(page_soup)
                for v in pv:
                    venue_map[v['url']] = v
                print(f"Page {page_num}: {len(pv)} venues")
            time.sleep(1)

        all_venue_infos = list(venue_map.values())
        max_venues = self.config.get('max_venues_to_test', 0)
        if max_venues > 0:
            all_venue_infos = all_venue_infos[:max_venues]

        # Phase 2: Fetch field pages for priced slots
        total_fields = sum(len(v['fields']) for v in all_venue_infos)
        print(f"\nFetching prices for {total_fields} fields across {len(all_venue_infos)} venues...")

        results = []
        field_count = 0

        for venue_info in all_venue_infos:
            available_fields = []
            all_time_slots = []

            for field in venue_info['fields']:
                field_count += 1
                print(f"  Checking slots: {venue_info['name']} - {field['field_name']} ({field_count}/{total_fields})")

                slots = self.get_field_slots(field['field_id'])
                if slots:
                    available_fields.append({
                        'field_name': field['field_name'],
                        'field_id': field['field_id'],
                        'field_sport_type': field['sport_type'],
                        'slot_status': f'{len(slots)} slots available',
                        'time_slots': slots
                    })
                    all_time_slots.extend(slots)

                print(f"__PROGRESS__:gelora:{field_count}:{total_fields}")
                time.sleep(1)

            venue_data = {
                'name': venue_info['name'],
                'url': venue_info['url'],
                'venue_id': None,
                'available_fields': available_fields,
                'time_slots': all_time_slots,
                'platform': 'gelora'
            }

            if available_fields:
                venue_data['slot_status'] = f"{len(available_fields)} available fields"
                print(f"  ✅ {venue_info['name']} - {len(available_fields)} fields, {len(all_time_slots)} slots")
            else:
                venue_data['slot_status'] = 'No available slots'
                print(f"  ❌ {venue_info['name']} - No available slots")

            results.append(venue_data)

        self.venues = results
        print(f"\nGelora scraping completed! {len(self.venues)} venues")

    def close(self):
        """Clean up resources"""
        pass
