import requests
from bs4 import BeautifulSoup
import time
import re
from datetime import datetime, timedelta


class GeloraScraper:
    """Scraper for gelora.id venue listing and slot availability"""

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
            # Take first city if multiple (comma-separated)
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

            # Find last page link (» arrow)
            last_link = pagination.find('a', class_='pagination__next')
            if last_link and last_link.get('href'):
                href = last_link['href']
                match = re.search(r'page=(\d+)', href)
                if match:
                    return int(match.group(1))

            # Fallback: find highest page number in pagination items
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

    def extract_venues_and_slots(self, soup, date_str):
        """Extract venues, fields, and slot availability from listing page.

        The gelora listing page embeds field + time slot data inline per venue card,
        so we can extract everything in one pass without fetching individual venue pages.

        Args:
            soup: BeautifulSoup of the listing page
            date_str: Date in YYYY-MM-DD format for slot tagging
        """
        venues_data = []

        # Each venue card is in div.col-12.col-md-6.col-lg-4
        venue_cards = soup.select('div.col-12.col-md-6.col-lg-4.mb-xs-3')

        for card in venue_cards:
            boxed = card.find('div', class_='boxed')
            if not boxed:
                continue

            product = boxed.find('div', class_='product')
            if not product:
                continue

            # Extract venue name and URL
            name_tag = product.find('h5', class_='text--darkblue')
            if not name_tag:
                name_tag = product.find('h5')
            venue_name = name_tag.text.strip() if name_tag else 'Unknown'

            venue_link = product.find('a', href=re.compile(r'^/v/'))
            venue_slug = venue_link['href'] if venue_link else ''
            venue_url = f"{self.base_url}{venue_slug}" if venue_slug else ''

            # Extract location
            location_div = product.find('a', class_='block')
            location = ''
            if location_div:
                loc_divs = location_div.find_all('div')
                for div in loc_divs:
                    text = div.get_text()
                    if '\u25e6' in text:  # ◦ character
                        location = text.split('\u25e6')[0].strip()
                        break

            # Extract price range
            price_span = product.find('span', class_='text--green')
            price_range = price_span.text.strip() if price_span else ''

            print(f"Found venue: {venue_name} ({location}) -> {venue_url}")

            # Extract fields and their time slots
            field_links = boxed.select('a.feature.good-card-4')
            available_fields = []

            for field_link in field_links:
                # Field name
                field_h5 = field_link.find('h5', class_='mb-0')
                field_name = field_h5.text.strip() if field_h5 else 'Unknown Field'

                # Field ID from href
                field_href = field_link.get('href', '')
                field_id = None
                match = re.search(r'/field/(\d+)', field_href)
                if match:
                    field_id = int(match.group(1))

                # Sport type from span text
                field_span = field_link.find('span')
                sport_type = 'Tennis'
                if field_span:
                    span_text = field_span.get_text().strip()
                    # Sport is before the ◦ character
                    if '\u25e6' in span_text:
                        sport_type = span_text.split('\u25e6')[0].strip()
                    elif span_text:
                        sport_type = span_text.split()[0] if span_text.split() else 'Tennis'

                # Only include tennis fields
                sport_lower = sport_type.lower()
                if sport_lower not in ('tenis', 'tennis'):
                    continue

                # Extract time slots
                slot_buttons = field_link.select('div.btn.btn--sm')
                available_slots = []

                for btn in slot_buttons:
                    tooltip = btn.get('data-tooltip', '')
                    time_text = btn.text.strip()

                    # Only include available slots (Tersedia)
                    if tooltip == 'Tersedia' and time_text:
                        start_time = time_text  # e.g., "06:00"

                        # Apply time range filter
                        if not self.is_slot_within_time_range(start_time):
                            continue

                        # Calculate end time (assume 1-hour slots)
                        try:
                            h, m = map(int, start_time.split(':'))
                            end_h = h + 1
                            end_time = f"{end_h:02d}:00"
                        except (ValueError, IndexError):
                            end_time = ''

                        slot_data = {
                            'slot_id': None,
                            'date': date_str,
                            'start_time': start_time,
                            'end_time': end_time,
                            'price': 0,  # Per-slot price not available on listing page
                            'field_name': field_name
                        }
                        available_slots.append(slot_data)

                if available_slots:
                    available_fields.append({
                        'field_name': field_name,
                        'field_id': field_id,
                        'field_sport_type': sport_type,
                        'slot_status': f'{len(available_slots)} slots available',
                        'time_slots': available_slots
                    })

            venues_data.append({
                'name': venue_name,
                'url': venue_url,
                'venue_id': None,
                'location': location,
                'price_range': price_range,
                'available_fields': available_fields,
                'time_slots': [],  # Will be populated below
                'platform': 'gelora'
            })

        return venues_data

    def scrape_venues(self, max_pages=None):
        """Scrape venues from gelora.id listing pages"""
        if max_pages is None:
            max_pages = self.config.get('max_pages', 1)

        dates = self.get_date_range()
        print(f"Starting Gelora scraper for {len(dates)} date(s)")
        print(f"Sport: Tennis | Location: {self.config.get('lokasi', 'All')}")

        # Use first date for venue discovery (pagination), then scrape all dates
        first_date_gelora = self.format_date_gelora(dates[0])
        first_url = self.build_venues_url(page=1, date_gelora=first_date_gelora)
        print(f"Fetching URL: {first_url}")

        soup = self.get_page_content(first_url)
        if not soup:
            print("Failed to fetch first page")
            return

        total_pages = self.get_total_pages(soup)
        print(f"Total pages found: {total_pages}")

        if max_pages == 0:
            pages_to_scrape = total_pages
        else:
            pages_to_scrape = min(max_pages, total_pages)

        print(f"Will scrape {pages_to_scrape} page(s)")

        # Collect venue slugs from all pages first, then process slots per date
        # Extract venues from first page (first date)
        page_venues = self.extract_venues_and_slots(soup, dates[0])
        # Track unique venues by URL to avoid duplicates across dates
        venue_map = {}
        for v in page_venues:
            venue_map[v['url']] = v

        print(f"Page 1: Found {len(page_venues)} venues")

        # Additional pages
        for page_num in range(2, pages_to_scrape + 1):
            print(f"\nScraping page {page_num}...")
            page_url = self.build_venues_url(page=page_num, date_gelora=first_date_gelora)
            page_soup = self.get_page_content(page_url)

            if page_soup:
                pv = self.extract_venues_and_slots(page_soup, dates[0])
                for v in pv:
                    venue_map[v['url']] = v
                print(f"Page {page_num}: Found {len(pv)} venues")
            else:
                print(f"Failed to fetch page {page_num}")

            time.sleep(1)

        # Apply max venues limit
        max_venues = self.config.get('max_venues_to_test', 0)
        all_venues = list(venue_map.values())
        if max_venues > 0:
            all_venues = all_venues[:max_venues]

        # If multiple dates, fetch additional date pages for each venue
        if len(dates) > 1:
            print(f"\nFetching slot data for {len(dates) - 1} additional date(s)...")

            for date_str in dates[1:]:
                date_gelora = self.format_date_gelora(date_str)
                print(f"  Fetching date: {date_str} ({date_gelora})")

                for page_num in range(1, pages_to_scrape + 1):
                    page_url = self.build_venues_url(page=page_num, date_gelora=date_gelora)
                    page_soup = self.get_page_content(page_url)

                    if page_soup:
                        date_venues = self.extract_venues_and_slots(page_soup, date_str)
                        # Merge slots into existing venues
                        for dv in date_venues:
                            if dv['url'] in venue_map:
                                existing = venue_map[dv['url']]
                                # Merge available_fields: add slots to matching fields or append new fields
                                existing_field_ids = {f['field_id']: f for f in existing.get('available_fields', [])}
                                for new_field in dv.get('available_fields', []):
                                    if new_field['field_id'] in existing_field_ids:
                                        existing_field_ids[new_field['field_id']]['time_slots'].extend(new_field['time_slots'])
                                        # Update slot count
                                        total = len(existing_field_ids[new_field['field_id']]['time_slots'])
                                        existing_field_ids[new_field['field_id']]['slot_status'] = f'{total} slots available'
                                    else:
                                        existing['available_fields'].append(new_field)

                    time.sleep(1)

        # Finalize venues
        print(f"\nProcessing {len(all_venues)} venues...")
        for i, venue in enumerate(all_venues, 1):
            # Flatten time_slots from all fields
            all_time_slots = []
            for field in venue.get('available_fields', []):
                all_time_slots.extend(field.get('time_slots', []))
            venue['time_slots'] = all_time_slots

            if venue.get('available_fields'):
                venue['slot_status'] = f"{len(venue['available_fields'])} available fields"
                print(f"  [{i}/{len(all_venues)}] {venue['name']} - {venue['slot_status']} ({len(all_time_slots)} total slots)")
            else:
                venue['slot_status'] = 'No available slots'
                print(f"  [{i}/{len(all_venues)}] {venue['name']} - No available slots")

            # Emit progress
            print(f"__PROGRESS__:{i}:{len(all_venues)}")

        self.venues = all_venues
        print(f"\nGelora scraping completed! Total venues: {len(self.venues)}")

    def close(self):
        """Clean up resources"""
        pass
