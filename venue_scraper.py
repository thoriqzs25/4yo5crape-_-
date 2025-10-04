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
        'max_pages': int(config.get('MAX_PAGES', os.getenv('MAX_PAGES', '1'))),  # Maximum number of pages to scrape
    }

CONFIG = load_config()

class VenueScraper:
    def __init__(self, config=None):
        self.config = config or CONFIG
        self.base_url = self.config['base_url']
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
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
        """Extract venue names and URLs from venue-card-item divs"""
        venue_info = []
        venue_cards = soup.find_all('div', class_='venue-card-item')
        
        for card in venue_cards:
            # Get venue name from img alt attribute
            img_tag = card.select_one('div > a > div > img')
            venue_name = img_tag.get('alt').strip() if img_tag and img_tag.get('alt') else "Unknown"
            
            # Get venue URL from href attribute
            link_tag = card.select_one('a')
            venue_url = link_tag.get('href') if link_tag else None
            
            if venue_name and venue_url:
                venue_info.append({
                    'name': venue_name,
                    'url': venue_url
                })
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
            self.single_venue_scraper = SingleVenueScraper(use_selenium=True)
    
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
        pages_to_scrape = min(max_pages, total_pages)
        
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
            
            if self.single_venue_scraper:
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
                            print(f"    Field: {field['field_name']} - {field['slot_status']}")
                        
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
        """Save results to file"""
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"VENUE SCRAPING RESULTS\n")
            f.write(f"=" * 50 + "\n\n")
            f.write(f"Total venues found: {len(self.venues)}\n")
            f.write(f"Total pages available: {self.get_total_pages(self.get_page_content(self.build_venues_url()))}\n\n")
            f.write(f"VENUE LIST WITH SLOT INFO:\n")
            f.write(f"-" * 30 + "\n")
            
            for i, venue in enumerate(self.venues, 1):
                f.write(f"{i}. {venue['name']} | url -> {venue['url']} | slot available -> {venue.get('slot_status', 'Not checked')}\n")
                
                if venue.get('available_fields'):
                    for field in venue['available_fields']:
                        f.write(f"   Field: {field['field_name']} - {field['slot_status']}\n")
                
                # Show available time slots
                if venue.get('time_slots'):
                    f.write(f"   Available time slots:\n")
                    for slot in venue['time_slots'][:10]:  # Show first 10 slots
                        f.write(f"     {slot['field_name']}: {slot['date']} {slot['start_time']}-{slot['end_time']} - Rp{slot['price']}\n")
                f.write(f"\n")
        
        print(f"Results saved to {filename}")
    
    def close(self):
        """Clean up resources"""
        if self.single_venue_scraper:
            self.single_venue_scraper.close()

def main():
    # You can modify the CONFIG dictionary at the top of the file to change settings
    # Or set environment variables in .env file
    # Or create a custom config here:
    # custom_config = {
    #     'base_url': 'https://ayo.co.id',
    #     'venues_path': '/venues',
    #     'sortby': 5,  # Change this number as needed
    #     'tipe': 'venue',  # Type filter
    #     'lokasi': 'Kota+Jakarta+Selatan',  # Change location as needed
    #     'cabor': 7   # Change this number as needed
    # }
    # scraper = VenueScraper(custom_config)
    
    scraper = VenueScraper()  # Uses CONFIG from environment variables or defaults
    
    try:
        # Scrape venues from configured number of pages
        max_pages = scraper.config.get('max_pages', 1)
        scraper.scrape_venues(max_pages=max_pages)
        
        # Save results
        scraper.save_results()
    finally:
        # Clean up resources
        scraper.close()
    
    # Also save as JSON for structured data
    with open('venues_data.json', 'w', encoding='utf-8') as f:
        json.dump({
            'total_venues': len(scraper.venues),
            'venues': scraper.venues,
            'config_used': scraper.config
        }, f, indent=2, ensure_ascii=False)
    
    print("Data also saved as JSON in venues_data.json")
    print(f"Configuration used: {scraper.config}")

if __name__ == "__main__":
    main()
