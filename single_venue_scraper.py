import requests
from bs4 import BeautifulSoup
import json
import time
import os
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

class SingleVenueScraper:
    def __init__(self, use_selenium=True, cabor=7):
        self.use_selenium = use_selenium
        self.cabor = cabor
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        if use_selenium:
            self.driver = self._init_selenium()
        else:
            self.driver = None
    
    def _init_selenium(self):
        """Initialize Selenium WebDriver"""
        try:
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')
            chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')
            
            driver = webdriver.Chrome(options=chrome_options)
            return driver
        except Exception as e:
            print(f"Error initializing Selenium: {e}")
            return None
    
    def get_page_content(self, url):
        """Fetch page content with error handling"""
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        except requests.RequestException as e:
            print(f"Error fetching {url}: {e}")
            return None
    
    def should_include_field(self, field_sport_type):
        """Check if field should be included based on CABOR"""
        # CABOR 7 = Tennis, CABOR 12 = Padel
        if self.cabor == 7:  # Tennis only
            return field_sport_type.lower() == 'tennis'
        elif self.cabor == 12:  # Padel only
            return field_sport_type.lower() == 'padel'
        else:  # Other CABOR values - include all fields
            return True
    
    def scrape_venue_with_selenium(self, venue_url, venue_name="Unknown Venue"):
        """Scrape venue using Selenium to handle JavaScript"""
        if not self.driver:
            print("Selenium driver not available, falling back to static scraping")
            return self.scrape_venue_static(venue_url, venue_name)
        
        print(f"\n{'='*60}")
        print(f"SELENIUM SCRAPING: {venue_name}")
        print(f"URL: {venue_url}")
        print(f"{'='*60}")
        
        try:
            # Load the page
            print("Loading page with Selenium...")
            self.driver.get(venue_url)
            
            # Wait for page to load and field-list-container to be populated
            print("Waiting for field-list-container to be populated...")
            wait = WebDriverWait(self.driver, 15)
            
            try:
                # Wait for field-list-container to have content
                wait.until(lambda driver: driver.find_element(By.ID, "field-list-container").text.strip() != "")
                print("✅ Field-list-container populated!")
            except TimeoutException:
                print("⚠️ Timeout waiting for field-list-container to populate")
            
            # Additional wait for field containers to render
            time.sleep(3)
            
            # Look for field containers
            field_containers = self.driver.find_elements(By.CSS_SELECTOR, "div.field-container")
            print(f"Found {len(field_containers)} field containers")
            
            # Look for slot buttons
            slot_buttons = self.driver.find_elements(By.CSS_SELECTOR, "div.field_slot_btn")
            print(f"Found {len(slot_buttons)} slot buttons")
            
            # Extract field information
            fields = []
            for i, container in enumerate(field_containers):
                try:
                    # Get field name from s18-500 div
                    field_name_div = container.find_element(By.CSS_SELECTOR, "div.s18-500")
                    field_name = field_name_div.text.strip()
                    
                    # Get sport type from container attribute
                    sport = container.get_attribute('sport') or 'Unknown'
                    
                    # Check field_desc_point to determine sport type
                    field_sport_type = 'Unknown'
                    try:
                        field_desc_point = container.find_element(By.CSS_SELECTOR, "div.field_desc_point")
                        field_desc_content = field_desc_point.text.strip()
                        
                        # Check if it's tennis or padel based on content
                        if 'tennis' in field_desc_content.lower():
                            field_sport_type = 'Tennis'
                        elif 'padel' in field_desc_content.lower():
                            field_sport_type = 'Padel'
                        else:
                            # Fallback to checking the sport attribute
                            field_sport_type = sport
                            
                    except Exception as e:
                        print(f"    Could not determine field sport type: {e}")
                        field_sport_type = sport
                    
                    # Find slot button in this container
                    slot_button = container.find_element(By.CSS_SELECTOR, "div.field_slot_btn")
                    field_name_attr = slot_button.get_attribute('field-name') or field_name
                    field_id = slot_button.get_attribute('field-id') or ''
                    
                    # Get slot status
                    slot_text_elem = slot_button.find_element(By.CSS_SELECTOR, "span.slot-available-text")
                    slot_status = slot_text_elem.text.strip()
                    
                    # Check if field should be included based on CABOR
                    if self.should_include_field(field_sport_type):
                        field_info = {
                            'field_name': field_name,
                            'field_name_attr': field_name_attr,
                            'field_id': field_id,
                            'sport': sport,
                            'field_sport_type': field_sport_type,
                            'slot_status': slot_status
                        }
                        fields.append(field_info)
                        print(f"  Field {i+1}: {field_name} ({field_sport_type}) - {slot_status}")
                    else:
                        print(f"  Field {i+1}: {field_name} ({field_sport_type}) - EXCLUDED (CABOR {self.cabor})")
                    
                except Exception as e:
                    print(f"  Error extracting field {i+1}: {e}")
            
            # Extract time slots from within field containers (only for included fields)
            time_slots = []
            print(f"Looking for time slots within field containers...")
            
            for i, container in enumerate(field_containers):
                try:
                    # Get field sport type to check if it should be included
                    field_sport_type = 'Unknown'
                    try:
                        field_desc_point = container.find_element(By.CSS_SELECTOR, "div.field_desc_point")
                        field_desc_content = field_desc_point.text.strip()
                        
                        if 'tennis' in field_desc_content.lower():
                            field_sport_type = 'Tennis'
                        elif 'padel' in field_desc_content.lower():
                            field_sport_type = 'Padel'
                        else:
                            field_sport_type = container.get_attribute('sport') or 'Unknown'
                    except:
                        field_sport_type = container.get_attribute('sport') or 'Unknown'
                    
                    # Only process time slots for included fields
                    if self.should_include_field(field_sport_type):
                        # Find slot items within this field container
                        slot_items = container.find_elements(By.CSS_SELECTOR, "div.field-slot-item")
                        print(f"  Field {i+1}: Found {len(slot_items)} slot items")
                        
                        for slot in slot_items:
                            try:
                                # Check is-disabled attribute (not class)
                                is_disabled_attr = slot.get_attribute('is-disabled')
                                is_disabled = is_disabled_attr == 'true' if is_disabled_attr else True
                                
                                if not is_disabled:
                                    slot_data = {
                                        'slot_id': slot.get_attribute('slot-id') or '',
                                        'field_id': slot.get_attribute('field-id') or '',
                                        'date': slot.get_attribute('date') or '',
                                        'start_time': slot.get_attribute('start-time') or '',
                                        'end_time': slot.get_attribute('end-time') or '',
                                        'price': slot.get_attribute('price') or '',
                                        'is_disabled': is_disabled,
                                        'field_name': container.find_element(By.CSS_SELECTOR, "div.s18-500").text.strip()
                                    }
                                    time_slots.append(slot_data)
                                    print(f"    Available slot: {slot_data['date']} {slot_data['start_time']}-{slot_data['end_time']} - Rp{slot_data['price']}")
                            except Exception as e:
                                print(f"    Error extracting slot from field {i+1}: {e}")
                    else:
                        print(f"  Field {i+1}: Skipping time slots (EXCLUDED - CABOR {self.cabor})")
                            
                except Exception as e:
                    print(f"  Error processing field container {i+1}: {e}")
            
            print(f"Total available time slots found: {len(time_slots)}")
            
            result = {
                'venue_name': venue_name,
                'venue_url': venue_url,
                'fields': fields,
                'time_slots': time_slots,
                'total_fields': len(fields),
                'available_fields': len([f for f in fields if f['slot_status'] != 'Tidak tersedia']),
                'total_time_slots': len(time_slots),
                'scraping_method': 'selenium'
            }
            
            return result
            
        except Exception as e:
            print(f"Error during Selenium scraping: {e}")
            return None
    
    def scrape_venue_static(self, venue_url, venue_name="Unknown Venue"):
        """Fallback static scraping method"""
        print(f"\n{'='*60}")
        print(f"STATIC SCRAPING: {venue_name}")
        print(f"URL: {venue_url}")
        print(f"{'='*60}")
        
        soup = self.get_page_content(venue_url)
        if not soup:
            return None
        
        # Extract basic info
        title = soup.find('title')
        page_title = title.get_text().strip() if title else "No title found"
        
        result = {
            'venue_name': venue_name,
            'venue_url': venue_url,
            'page_title': page_title,
            'fields': [],
            'time_slots': [],
            'total_fields': 0,
            'available_fields': 0,
            'total_time_slots': 0,
            'scraping_method': 'static'
        }
        
        return result
    
    def scrape_venue(self, venue_url, venue_name="Unknown Venue"):
        """Main scraping method - uses Selenium if available"""
        if self.use_selenium and self.driver:
            return self.scrape_venue_with_selenium(venue_url, venue_name)
        else:
            return self.scrape_venue_static(venue_url, venue_name)
    
    def close(self):
        """Close the browser"""
        if self.driver:
            self.driver.quit()

def main():
    scraper = SingleVenueScraper(use_selenium=True)
    
    try:
        # Test with a specific venue URL
        test_venue_url = "https://ayo.co.id/v/ambassador-tennis"
        test_venue_name = "Ambassador Tennis"
        
        result = scraper.scrape_venue(test_venue_url, test_venue_name)
        
        if result:
            print(f"\n{'='*60}")
            print("FINAL RESULTS:")
            print(f"{'='*60}")
            print(f"Venue: {result['venue_name']}")
            print(f"Method: {result['scraping_method']}")
            print(f"Total Fields: {result['total_fields']}")
            print(f"Available Fields: {result['available_fields']}")
            print(f"Total Time Slots: {result['total_time_slots']}")
            
            print(f"\nFields Found:")
            for i, field in enumerate(result['fields'], 1):
                print(f"  {i}. {field['field_name']} - {field['slot_status']}")
            
            print(f"\nTime Slots Found:")
            for i, slot in enumerate(result['time_slots'][:5], 1):  # Show first 5
                print(f"  {i}. {slot['date']} {slot['start_time']}-{slot['end_time']} - Rp{slot['price']}")
            
            # Save results
            with open('single_venue_result.json', 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2, ensure_ascii=False)
            print(f"\nResults saved to single_venue_result.json")
        else:
            print("Failed to scrape venue")
    
    finally:
        scraper.close()

if __name__ == "__main__":
    main()