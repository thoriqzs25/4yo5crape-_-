import requests
from bs4 import BeautifulSoup
import time
import json
import os
from urllib.parse import urljoin, urlencode
from single_venue_scraper import SingleVenueScraper

def load_config():
    """Load configuration from config.env file or environment variables"""
    config = {}
    
    # Try to load from config.env file
    if os.path.exists('config.env'):
        with open('config.env', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    config[key.strip()] = value.strip()
    
    # Configuration with defaults
    return {
        'base_url': config.get('BASE_URL', os.getenv('BASE_URL', 'https://ayo.co.id')),
        'venues_path': config.get('VENUES_PATH', os.getenv('VENUES_PATH', '/venues')),
        'sortby': int(config.get('SORTBY', os.getenv('SORTBY', '5'))),
        'tipe': config.get('TIPE', os.getenv('TIPE', 'venue')),
        'lokasi': config.get('LOKASI', os.getenv('LOKASI', '')),  # Leave empty to disable location filter
        'cabor': int(config.get('CABOR', os.getenv('CABOR', '7'))),
        'max_venues_to_test': int(config.get('MAX_VENUES_TO_TEST', os.getenv('MAX_VENUES_TO_TEST', '3'))),  # Number of venues to test with Selenium (set to 0 to test all)
        'use_selenium': config.get('USE_SELENIUM', os.getenv('USE_SELENIUM', 'True')).lower() == 'true',  # Set to False to use static scraping only
        'use_api': config.get('USE_API', os.getenv('USE_API', 'False')).lower() == 'true',  # Set to True to use API for slot data
        'date': config.get('DATE', os.getenv('DATE', '2025-01-15')),  # Date for API slot queries (YYYY-MM-DD format)
        'max_pages': int(config.get('MAX_PAGES', os.getenv('MAX_PAGES', '1'))),  # Maximum number of pages to scrape
    }

class VenueScraper:
    def __init__(self, config=None):
        self.config = config or load_config()
        self.base_url = self.config['base_url']
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
        })
        self.venues = []
        self.single_venue_scraper = None
    
    def get_page_content(self, url):
        """Fetch page content with error handling"""
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        except requests.RequestException as e:
            print(f"Error fetching {url}: {e}")
            return None
    
    def extract_venue_info(self, soup):
        """Extract venue names, URLs, and venue_id from venue-card-item divs"""
        venue_info = []
        venue_cards = soup.find_all('div', class_='venue-card-item')
        
        for card in venue_cards:
            # Get venue name from img alt attribute
            img_tag = card.select_one('div > a > div > img')
            venue_name = img_tag.get('alt').strip() if img_tag and img_tag.get('alt') else "Unknown"
            
            # Get venue URL from href attribute
            link_tag = card.select_one('a')
            venue_url = link_tag.get('href') if link_tag else None
            
            # Extract venue_id from id attribute (format: venue-1006)
            venue_id = None
            card_id = card.get('id')
            if card_id and card_id.startswith('venue-'):
                try:
                    venue_id = int(card_id.replace('venue-', ''))
                except ValueError:
                    pass
            
            if venue_name and venue_url:
                venue_info.append({
                    'name': venue_name,
                    'url': venue_url,
                    'venue_id': venue_id
                })
                if venue_id:
                    print(f"Found venue: {venue_name} (ID: {venue_id}) -> {venue_url}")
                else:
                    print(f"Found venue: {venue_name} -> {venue_url}")
        
        return venue_info
    
    def get_venue_slot_info(self, venue_url):
        """Get slot availability and time slots from venue detail page"""
        try:
            print(f"  Checking slots for: {venue_url}")
            soup = self.get_page_content(venue_url)
            if not soup:
                return "Error loading page", []
            
            # Look for slot buttons directly since field-container might not exist
            slot_buttons = soup.find_all('div', class_='field_slot_btn')
            print(f"    Found {len(slot_buttons)} slot buttons")
            
            available_fields = []
            
            for button in slot_buttons:
                slot_text_elem = button.find('span', class_='slot-available-text')
                if slot_text_elem:
                    slot_status = slot_text_elem.text.strip()
                    field_name = button.get('field-name', 'Unknown Field')
                    field_id = button.get('field-id', '')
                    
                    print(f"    Found field: {field_name} - {slot_status}")
                    
                    # Only include fields that are NOT "Tidak tersedia"
                    if slot_status != "Tidak tersedia":
                        # Get time slots for this field
                        time_slots = self.get_field_time_slots(soup, field_id)
                        
                        available_fields.append({
                            'field_name': field_name,
                            'slot_status': slot_status,
                            'field_id': field_id,
                            'time_slots': time_slots
                        })
                        print(f"    ✅ Available field: {field_name} - {slot_status}")
            
            if available_fields:
                return "Available", available_fields
            else:
                return "No available slots", []
                
        except Exception as e:
            print(f"  Error getting slot info: {e}")
            return "Error", []
    
    def get_venue_slot_info_api(self, venue_id, venue_name):
        """Get slot availability and time slots using API"""
        try:
            print(f"  Checking slots via API for: {venue_name} (ID: {venue_id})")
            
            if not venue_id:
                print(f"    ⚠️  No venue_id found, skipping API call")
                return "No venue_id", []
            
            # Build API URL
            api_url = f"{self.base_url}/venues-ajax/op-times-and-fields?venue_id={venue_id}&date={self.config['date']}"
            print(f"    🔗 API URL: {api_url}")
            
            # Make API request
            response = self.session.get(api_url)
            response.raise_for_status()
            
            # Parse JSON response
            api_data = response.json()
            
            # Extract fields and slots
            available_fields = []
            
            if 'fields' in api_data:
                for field in api_data['fields']:
                    field_id = field.get('field_id')
                    field_name = field.get('field_name', 'Unknown Field')
                    sport_id = field.get('sport_id')
                    total_available_slots = field.get('total_available_slots', 0)
                    slots = field.get('slots', [])
                    
                    print(f"    📊 Field: {field_name} (Sport ID: {sport_id}, Available: {total_available_slots})")
                    
                    # Apply CABOR filtering - only include fields matching the configured sport
                    if sport_id != self.config['cabor']:
                        print(f"    ⏭️  Skipping field (sport_id {sport_id} != {self.config['cabor']})")
                        continue
                    
                    # Find available slots (is_available: 1)
                    available_slots = []
                    for slot in slots:
                        if slot.get('is_available') == 1:
                            slot_data = {
                                'slot_id': slot.get('id'),
                                'date': slot.get('date'),
                                'start_time': slot.get('start_time'),
                                'end_time': slot.get('end_time'),
                                'price': slot.get('price', 0),
                                'field_name': field_name
                            }
                            available_slots.append(slot_data)
                    
                    # Only include fields with available slots
                    if available_slots:
                        available_fields.append({
                            'field_name': field_name,
                            'field_id': field_id,
                            'field_sport_type': 'Tennis' if sport_id == 7 else 'Padel' if sport_id == 12 else f'Sport_{sport_id}',
                            'slot_status': f'{len(available_slots)} slots available',
                            'time_slots': available_slots
                        })
                        print(f"    ✅ Available field: {field_name} - {len(available_slots)} slots")
                    else:
                        print(f"    ❌ No available slots for field: {field_name}")
            
            if available_fields:
                return "Available", available_fields
            else:
                return "No available slots", []
                
        except requests.RequestException as e:
            print(f"  API request error: {e}")
            return "API Error", []
        except Exception as e:
            print(f"  Error processing API data: {e}")
            return "Error", []
    
    def get_field_time_slots(self, soup, field_id):
        """Get available time slots for a specific field"""
        time_slots = []
        
        # Find field-slot-item elements that are not disabled and match the field_id
        slot_items = soup.find_all('div', class_='field-slot-item')
        
        for slot in slot_items:
            # Check if this slot is not disabled and matches the field_id
            if ('field-slot-item-disabled' not in slot.get('class', []) and 
                slot.get('field-id') == field_id):
                slot_data = {
                    'date': slot.get('date', ''),
                    'start_time': slot.get('start-time', ''),
                    'end_time': slot.get('end-time', ''),
                    'price': slot.get('price', ''),
                    'slot_id': slot.get('slot-id', '')
                }
                time_slots.append(slot_data)
        
        return time_slots
    
    def get_total_pages(self, soup):
        """Extract total number of pages from pagination"""
        try:
            pagination_div = soup.find('div', id='venue-pagination')
            if not pagination_div:
                return 1
            
            pagination_ul = pagination_div.find('ul', class_='pagination')
            if not pagination_ul:
                return 1
            
            # Look for the 'next' link to find the last page
            next_link = pagination_ul.find('a', {'rel': 'next'})
            if next_link:
                # Get the li element before the next link
                next_li = next_link.find_parent('li')
                if next_li:
                    prev_li = next_li.find_previous_sibling('li')
                    if prev_li:
                        page_link = prev_li.find('a')
                        if page_link:
                            try:
                                return int(page_link.text.strip())
                            except ValueError:
                                pass
            
            # Fallback: find the highest page number in pagination
            page_links = pagination_ul.find_all('a', href=True)
            max_page = 1
            for link in page_links:
                href = link.get('href', '')
                if '/venues?page=' in href:
                    try:
                        page_num = int(href.split('page=')[1])
                        max_page = max(max_page, page_num)
                    except (ValueError, IndexError):
                        continue
            
            return max_page
            
        except Exception as e:
            print(f"Error extracting total pages: {e}")
            return 1
    
    def get_total_venues_count_with_selenium(self, url):
        """Extract total venue count from count_drop class using Selenium"""
        if not self.single_venue_scraper or not self.single_venue_scraper.driver:
            print("⚠️  Selenium not available for count_drop extraction")
            return None
            
        try:
            print("🔍 Loading page with Selenium to get count_drop value...")
            self.single_venue_scraper.driver.get(url)
            
            # Wait for count_drop to be populated
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.common.by import By
            from selenium.common.exceptions import TimeoutException
            
            wait = WebDriverWait(self.single_venue_scraper.driver, 15)
            
            try:
                # Wait for count_drop element to be present and have content
                wait.until(lambda driver: 
                    driver.find_element(By.CSS_SELECTOR, ".count_drop").get_attribute('innerHTML').strip() != ""
                )
                
                # Now get the element
                count_element = self.single_venue_scraper.driver.find_element(By.CSS_SELECTOR, ".count_drop")
                count_text = count_element.get_attribute('innerHTML').strip()
                print(f"📊 Found count_drop innerHTML with Selenium: '{count_text}'")
                
                # Extract number from text
                import re
                numbers = re.findall(r'\d+', count_text)
                if numbers:
                    total_count = int(numbers[0])
                    print(f"✅ Total venues count: {total_count}")
                    return total_count
                else:
                    print("⚠️  No numbers found in count_drop innerHTML")
                    return None
                    
            except TimeoutException:
                print("⚠️  Timeout waiting for count_drop to be populated")
                # Try to get the element anyway to see what's there
                try:
                    count_element = self.single_venue_scraper.driver.find_element(By.CSS_SELECTOR, ".count_drop")
                    print(f"📊 count_drop element found but empty: '{count_element.text}'")
                    print(f"📊 count_drop innerHTML: '{count_element.get_attribute('innerHTML')}'")
                except:
                    print("📊 count_drop element not found at all")
                return None
                
        except Exception as e:
            print(f"Error extracting total venues count with Selenium: {e}")
            return None

    def get_total_venues_count(self, soup):
        """Extract total venue count from count_drop class"""
        try:
            # Look for count_drop class
            count_element = soup.find(class_='count_drop')
            if not count_element:
                return None
            
            # Extract the number from the text
            count_text = count_element.get_text(strip=True)
            
            # Try to extract number from text (handle various formats)
            import re
            numbers = re.findall(r'\d+', count_text)
            if numbers:
                total_count = int(numbers[0])  # Take the first number found
                print(f"✅ Total venues count: {total_count}")
                return total_count
            else:
                # Element exists but is empty (JavaScript populated)
                return None
                
        except Exception as e:
            print(f"Error extracting total venues count: {e}")
            return None
    
    def build_venues_url(self, page=1):
        """Build URL with search parameters"""
        params = []
        
        # Add parameters in the exact order needed
        params.append(f"sortby={self.config['sortby']}")
        params.append(f"tipe={self.config['tipe']}")
        if self.config['lokasi']:  # Only add location if not empty
            params.append(f"lokasi={self.config['lokasi']}")
        params.append(f"cabor={self.config['cabor']}")
        
        if page > 1:
            params.append(f"page={page}")
        
        base_path = self.config['venues_path']
        query_string = "&".join(params)
        return f"{self.base_url}{base_path}?{query_string}"
    
    def initialize_single_venue_scraper(self):
        """Initialize the single venue scraper if Selenium is enabled"""
        if self.config.get('use_selenium', False) and not self.single_venue_scraper:
            print("Initializing Selenium for venue detail scraping...")
            cabor = self.config.get('cabor', 7)
            self.single_venue_scraper = SingleVenueScraper(use_selenium=True, cabor=cabor)
    
    def dry_run(self):
        """Perform a dry run to show what would be scraped without actually scraping"""
        print("=" * 60)
        print("DRY RUN - Venue Scraping Preview")
        print("=" * 60)
        
        # Build the URL for the first page
        first_page_url = self.build_venues_url(page=1)
        print(f"📋 Venues List URL: {first_page_url}")
        
        # Initialize single venue scraper if needed for count_drop extraction
        self.initialize_single_venue_scraper()
        
        # Fetch first page to get pagination info
        soup = self.get_page_content(first_page_url)
        if not soup:
            print("❌ Failed to fetch first page for dry run")
            return
        
        # Get total pages
        total_pages = self.get_total_pages(soup)
        print(f"📄 Total pages available: {total_pages}")
        
        # Get actual total venue count from count_drop class
        actual_total_venues = self.get_total_venues_count(soup)
        
        # If count_drop is empty (JavaScript populated), try with Selenium
        if actual_total_venues is None and self.single_venue_scraper and self.single_venue_scraper.driver:
            print("🔄 Trying to get count_drop with Selenium...")
            actual_total_venues = self.get_total_venues_count_with_selenium(first_page_url)
        
        # Get venues from first page to estimate per page
        venues_page_1 = self.extract_venue_info(soup)
        venues_per_page = len(venues_page_1)
        print(f"🏟️  Venues per page: {venues_per_page}")
        
        # Calculate what will be scraped
        max_pages_config = self.config.get('max_pages', 1)
        if max_pages_config == 0:
            pages_to_scrape = total_pages
            print(f"📊 Pages to scrape: ALL ({total_pages} pages)")
        else:
            pages_to_scrape = min(max_pages_config, total_pages)
            print(f"📊 Pages to scrape: {pages_to_scrape} (limited by MAX_PAGES={max_pages_config})")
        
        # Use actual total if available, otherwise estimate
        if actual_total_venues:
            venues_to_scrape = min(actual_total_venues, pages_to_scrape * venues_per_page)
            print(f"🎯 Total venues available: {actual_total_venues}")
            print(f"🎯 Venues to scrape: {venues_to_scrape}")
        else:
            estimated_total_venues = pages_to_scrape * venues_per_page
            print(f"🎯 Estimated total venues: {estimated_total_venues}")
            venues_to_scrape = estimated_total_venues
        
        # Show venue processing limits
        max_venues_to_test = self.config.get('max_venues_to_test', 0)
        if max_venues_to_test == 0:
            print(f"🔍 Venues to process: ALL ({venues_to_scrape})")
        else:
            print(f"🔍 Venues to process: {max_venues_to_test} (limited by MAX_VENUES_TO_TEST={max_venues_to_test})")
        
        # Show configuration summary
        print(f"\n⚙️  Configuration Summary:")
        print(f"   • Sport Category (CABOR): {self.config['cabor']} ({'Tennis' if self.config['cabor'] == 7 else 'Padel' if self.config['cabor'] == 12 else 'Other'})")
        print(f"   • Location Filter: {self.config['lokasi'] or 'None'}")
        print(f"   • Sort By: {self.config['sortby']}")
        
        # Show data source configuration
        if self.config.get('use_api', False):
            print(f"   • Slot Data Source: API (date: {self.config.get('date', 'N/A')})")
        elif self.config.get('use_selenium', True):
            print(f"   • Slot Data Source: Selenium (browser automation)")
        else:
            print(f"   • Slot Data Source: Static HTML parsing")
        
        print("=" * 60)
        return {
            'total_pages': total_pages,
            'pages_to_scrape': pages_to_scrape,
            'venues_per_page': venues_per_page,
            'actual_total_venues': actual_total_venues,
            'venues_to_scrape': venues_to_scrape,
            'venues_to_process': min(max_venues_to_test, venues_to_scrape) if max_venues_to_test > 0 else venues_to_scrape,
            'url': first_page_url
        }

    def scrape_venues(self, max_pages=5):
        """Scrape venues from multiple pages"""
        print(f"Starting to scrape venues from {self.base_url}")
        print(f"Using search parameters: sortby={self.config['sortby']}, tipe={self.config['tipe']}, lokasi={self.config['lokasi']}, cabor={self.config['cabor']}")
        
        # Initialize single venue scraper if needed
        self.initialize_single_venue_scraper()
        
        # Start with first page
        first_page_url = self.build_venues_url(page=1)
        print(f"Fetching URL: {first_page_url}")
        soup = self.get_page_content(first_page_url)
        
        if not soup:
            print("Failed to fetch first page")
            return
        
        # Get total pages
        total_pages = self.get_total_pages(soup)
        print(f"Total pages found: {total_pages}")
        
        # Extract venues from first page
        venues_page_1 = self.extract_venue_info(soup)
        self.venues.extend(venues_page_1)
        print(f"Page 1: Found {len(venues_page_1)} venues")
        
        # Scrape additional pages (up to max_pages or total_pages)
        # If max_pages is 0, scrape all pages
        if max_pages == 0:
            pages_to_scrape = total_pages
        else:
            pages_to_scrape = min(max_pages, total_pages)
        
        print(f"Will scrape {pages_to_scrape} pages total")
        
        for page_num in range(2, pages_to_scrape + 1):
            print(f"\nScraping page {page_num}...")
            page_url = self.build_venues_url(page=page_num)
            soup = self.get_page_content(page_url)
            
            if soup:
                venues_page = self.extract_venue_info(soup)
                self.venues.extend(venues_page)
                print(f"Page {page_num}: Found {len(venues_page)} venues")
            else:
                print(f"Failed to fetch page {page_num}")
            
            # Be respectful - add a small delay between requests
            time.sleep(1)
        
        print(f"\nScraping completed!")
        print(f"Total venues found: {len(self.venues)}")
        print(f"Pages scraped: {pages_to_scrape}")
        print(f"Total pages available: {total_pages}")
        
        # Now get slot information for each venue
        print(f"\nChecking slot availability for {len(self.venues)} venues...")
        self.process_venue_slots()
    
    def process_venue_slots(self):
        """Process each venue to get slot information using single venue scraper"""
        # Determine how many venues to process
        max_venues = self.config.get('max_venues_to_test', 0)
        if max_venues > 0:
            venues_to_process = self.venues[:max_venues]
            print(f"Processing {len(venues_to_process)} venues (limited by config)")
        else:
            venues_to_process = self.venues
            print(f"Processing all {len(venues_to_process)} venues")
        
        for i, venue in enumerate(venues_to_process, 1):
            print(f"\n[{i}/{len(venues_to_process)}] Processing: {venue['name']}")
            
            if self.config.get('use_api', False):
                # Use API-based slot retrieval
                slot_status, available_fields = self.get_venue_slot_info_api(venue.get('venue_id'), venue['name'])
                if slot_status == "Available" and available_fields:
                    venue['slot_status'] = f"{len(available_fields)} available fields"
                    venue['available_fields'] = available_fields
                    
                    # Format the output as requested
                    print(f"  ✅ {venue['name']} | url -> {venue['url']} | slot available -> {venue['slot_status']}")
                    for field in available_fields:
                        field_sport = field.get('field_sport_type', 'Unknown')
                        print(f"    Field: {field['field_name']} ({field_sport}) - {field['slot_status']}")
                    
                    # Show available time slots
                    if field.get('time_slots'):
                        print(f"    Available time slots:")
                        slot_count = 0
                        for field in available_fields:
                            for slot in field.get('time_slots', [])[:3]:  # Show first 3 slots per field
                                if slot_count < 5:  # Limit total to 5 slots
                                    print(f"      {slot['field_name']}: {slot['date']} {slot['start_time']}-{slot['end_time']} - Rp{slot['price']}")
                                    slot_count += 1
                else:
                    venue['slot_status'] = slot_status
                    print(f"  ❌ {venue['name']} | url -> {venue['url']} | slot available -> {slot_status}")
                    
            elif self.single_venue_scraper:
                # Use Selenium-based scraping
                result = self.single_venue_scraper.scrape_venue(venue['url'], venue['name'])
                if result:
                    venue['slot_status'] = f"{result['available_fields']} available fields"
                    venue['available_fields'] = result['fields']
                    venue['time_slots'] = result['time_slots']
                    venue['total_fields'] = result['total_fields']
                    venue['total_time_slots'] = result['total_time_slots']
                    
                    # Format the output as requested
                    if result['available_fields'] > 0:
                        print(f"  ✅ {venue['name']} | url -> {venue['url']} | slot available -> {venue['slot_status']}")
                        for field in result['fields']:
                            field_sport = field.get('field_sport_type', field.get('sport', 'Unknown'))
                            print(f"    Field: {field['field_name']} ({field_sport}) - {field['slot_status']}")
                        
                        # Show available time slots
                        if result['time_slots']:
                            print(f"    Available time slots:")
                            for slot in result['time_slots'][:5]:  # Show first 5 slots
                                print(f"      {slot['field_name']}: {slot['date']} {slot['start_time']}-{slot['end_time']} - Rp{slot['price']}")
                    else:
                        print(f"  ❌ {venue['name']} | url -> {venue['url']} | slot available -> {venue['slot_status']}")
                else:
                    print(f"  ❌ Failed to scrape {venue['name']}")
            else:
                # Fallback to static scraping
                slot_status, available_fields = self.get_venue_slot_info(venue['url'])
                venue['slot_status'] = slot_status
                venue['available_fields'] = available_fields
                
                # Format the output as requested
                if available_fields:
                    print(f"  ✅ {venue['name']} | url -> {venue['url']} | slot available -> {slot_status}")
                    for field in available_fields:
                        print(f"    Field: {field['field_name']} - {field['slot_status']}")
                        if field['time_slots']:
                            print(f"    Time slots:")
                            for slot in field['time_slots'][:3]:  # Show first 3 slots
                                print(f"      {slot['date']} {slot['start_time']}-{slot['end_time']} - Rp{slot['price']}")
                else:
                    print(f"  ❌ {venue['name']} | url -> {venue['url']} | slot available -> {slot_status}")
            
            # Be respectful - add delay between venue requests
            time.sleep(2)
    
    def save_results(self, filename='venues_output.txt'):
        """Save results to file - only venues with available slots"""
        # Filter venues that have available slots
        venues_with_slots = [
            v for v in self.venues 
            if v.get('available_fields') or v.get('time_slots')
        ]
        
        with open(filename, 'w', encoding='utf-8') as f:
            # Format location for display
            location_display = self.config.get('lokasi', 'All Locations')
            if location_display == 'Kota+Jakarta+Selatan':
                location_display = 'Kota Jakarta Selatan'
            elif location_display.startswith('Kota+'):
                location_display = location_display.replace('Kota+', 'Kota ').replace('+', ' ')
            
            # Create dynamic title with date and location
            title = f"VENUE SCRAPING RESULTS FOR DATE {self.config.get('date', 'N/A')}"
            if location_display != 'All Locations':
                title += f" IN {location_display.upper()}"
            
            f.write(f"{title}\n")
            f.write(f"=" * len(title) + "\n\n")
            f.write(f"Total venues found: {len(self.venues)}\n")
            f.write(f"Venues with available slots: {len(venues_with_slots)}\n")
            f.write(f"Total pages available: {self.get_total_pages(self.get_page_content(self.build_venues_url()))}\n\n")
            f.write(f"VENUES WITH AVAILABLE SLOT:\n")
            f.write(f"=" * 42 + "\n")
            
            if not venues_with_slots:
                f.write("No venues found with available slots for the specified criteria.\n")
            else:
                for i, venue in enumerate(venues_with_slots, 1):
                    f.write(f"{i}. {venue['name']}\n")
                    f.write(f"   URL: {venue['url']}\n")
                    
                    if venue.get('available_fields'):
                        for field in venue['available_fields']:
                            field_sport = field.get('field_sport_type', field.get('sport', 'Unknown'))
                            f.write(f"   • {field['field_name']} ({field_sport}):\n")
                            
                            # Show available time slots for this field
                            if field.get('time_slots'):
                                for slot in field['time_slots'][:12]:  # Show first 12 slots per field
                                    start_time = slot.get('start_time', 'N/A')
                                    end_time = slot.get('end_time', 'N/A')
                                    date = slot.get('date', 'N/A')
                                    price = slot.get('price', 'N/A')
                                    if isinstance(price, (int, float)) and price > 0:
                                        price_str = f"Rp{price:,}"
                                    else:
                                        price_str = str(price)
                                    f.write(f"     {date} {start_time}-{end_time} ({price_str})\n")
                    
                    # Also show venue-level time slots (for backwards compatibility with Selenium mode)
                    if venue.get('time_slots'):
                        for slot in venue['time_slots'][:10]:  # Show first 10 slots
                            start_time = slot.get('start_time', 'N/A')
                            end_time = slot.get('end_time', 'N/A')
                            date = slot.get('date', 'N/A')
                            price = slot.get('price', 'N/A')
                            field_name = slot.get('field_name', 'Unknown Field')
                            if isinstance(price, (int, float)) and price > 0:
                                price_str = f"Rp{price:,}"
                            else:
                                price_str = str(price)
                            f.write(f"   {field_name}: {date} {start_time}-{end_time} ({price_str})\n")
                    f.write(f"\n")
        
        print(f"Results saved to {filename} (showing only venues with available slots)")
    
    def close(self):
        """Clean up resources"""
        if self.single_venue_scraper:
            self.single_venue_scraper.close()

def main():
    import sys
    
    # Check for dry run mode
    dry_run_mode = '--dry-run' in sys.argv or '-d' in sys.argv
    
    scraper = VenueScraper()  # Uses CONFIG from environment variables or defaults
    
    try:
        if dry_run_mode:
            # Perform dry run
            dry_run_info = scraper.dry_run()
            if dry_run_info:
                print(f"\n✅ Dry run completed successfully!")
                if dry_run_info['actual_total_venues']:
                    print(f"📊 Summary: {dry_run_info['pages_to_scrape']} pages, {dry_run_info['venues_to_scrape']} venues (total available: {dry_run_info['actual_total_venues']})")
                else:
                    print(f"📊 Summary: {dry_run_info['pages_to_scrape']} pages, ~{dry_run_info['venues_to_scrape']} venues")
        else:
            # Normal scraping
            max_pages = scraper.config.get('max_pages', 1)
            scraper.scrape_venues(max_pages=max_pages)
            
            # Save results
            scraper.save_results()
            
            # Also save as JSON for structured data
            with open('venues_data.json', 'w', encoding='utf-8') as f:
                json.dump({
                    'total_venues': len(scraper.venues),
                    'venues': scraper.venues,
                    'config_used': scraper.config
                }, f, indent=2, ensure_ascii=False)
            
            print("Data also saved as JSON in venues_data.json")
            print(f"Configuration used: {scraper.config}")
    finally:
        # Clean up resources
        scraper.close()

if __name__ == "__main__":
    main()
