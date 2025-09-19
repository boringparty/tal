import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET
import time
from datetime import datetime
import sys
import re

# --- Constants ---
BASE_URL = "https://www.thisamericanlife.org"
ARCHIVE_URL = f"{BASE_URL}/archive"
OUTPUT_FILE = "claudeTal.xml"
REPEAT_FILE = "episodes.txt"
SLEEP_TIME = 1  # 1 second to be polite

# --- Helper Functions ---
def get_repeat_episodes():
    """Reads episode numbers from episodes.txt."""
    try:
        with open(REPEAT_FILE, 'r') as f:
            return set(line.strip() for line in f if line.strip().isdigit())
    except FileNotFoundError:
        return set()

def get_page_content(url):
    """Fetches and returns the BeautifulSoup object for a given URL."""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return BeautifulSoup(response.content, 'html.parser')
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None

def get_episode_details(soup):
    """Scrapes episode page for all required details."""
    details = {}
    
    # Get main description
    body_div = soup.find('div', class_='field-name-body')
    if body_div:
        details['summary'] = body_div.get_text(strip=True).replace('\xa0', ' ')
    
    # Get audio URLs
    audio_links = soup.find_all('a', class_=['links-processed', 'internal'])
    download_link = soup.find('a', attrs={'download': True})
    
    if download_link:
        details['standard_audio_url'] = download_link['href']
    
    for link in audio_links:
        if 'clean' in link.get('href', ''):
            details['clean_audio_url'] = link['href']
            break

    # Get original air date
    date_span = soup.find('span', class_='date-display-single')
    if date_span:
        date_str = date_span.text
        try:
            date_obj = datetime.strptime(date_str, '%B %d, %Y')
            details['original_air_date'] = date_obj.strftime('%Y-%m-%d')
        except ValueError:
            details['original_air_date'] = date_str

    # Get acts
    acts_list = []
    act_headers = soup.find_all(class_=re.compile(r'act-header'))
    
    for header in act_headers:
        act_title_div = header.find('div', class_='field-item even')
        if act_title_div:
            act_title = act_title_div.get_text(strip=True).replace('\xa0', ' ')
            act_body_div = header.find_next_sibling('div', class_='field-name-body')
            if act_body_div:
                act_body = act_body_div.get_text(strip=True).replace('\xa0', ' ')
                acts_list.append(f"{act_title}\n{act_body}")
    
    details['acts'] = '\n\n'.join(acts_list)
    
    return details

def create_item(episode_num, title, slug, details, is_clean=False, is_repeat=False):
    """Creates a single XML <item> element."""
    item = ET.Element("item")

    # Title
    full_title = f"{episode_num}: {title}"
    if is_repeat:
        full_title += " - Repeat"
    if is_clean:
        full_title += " (Clean)"
    ET.SubElement(item, "title").text = full_title
    
    # Link
    ET.SubElement(item, "link").text = f"{BASE_URL}/{episode_num}/{slug}"
    
    # iTunes elements
    ET.SubElement(item, "itunes:episode").text = str(episode_num)
    ET.SubElement(item, "itunes:episodeType").text = "full"
    ET.SubElement(item, "itunes:explicit").text = "no" if is_clean else "yes"

    # Description
    description_text = f"{details.get('summary', '')}\n\n{details.get('acts', '')}\n\nOriginally aired: {details.get('original_air_date', 'N/A')}"
    ET.SubElement(item, "description").text = description_text
    
    # Pub Date (current scrape date)
    now = datetime.now()
    pub_date_str = now.strftime('%a, %d %b %Y %H:%M:%S +0000')
    ET.SubElement(item, "pubDate").text = pub_date_str
    
    # Enclosure URL
    enclosure_url = details.get('clean_audio_url') if is_clean else details.get('standard_audio_url')
    if enclosure_url:
        enclosure = ET.SubElement(item, "enclosure", url=enclosure_url, type="audio/mpeg")
    
    return item

# --- Main Logic ---
def main(mode):
    """Main function to run the scraper and generate the RSS feed."""
    print(f"Starting scraper in '{mode}' mode...")

    # Load repeat episodes from file
    repeat_episodes = get_repeat_episodes()
    print(f"Loaded {len(repeat_episodes)} episode numbers to mark as repeats.")

    # Fetch and parse the archive page
    archive_soup = get_page_content(ARCHIVE_URL)
    if not archive_soup:
        return
    
    episode_links = archive_soup.find_all('a', class_='goto-episode')
    
    # Select links based on mode
    if mode == 'latest':
        episodes_to_scrape = episode_links[:1]
    elif mode == 'test':
        episodes_to_scrape = episode_links[:5]
    elif mode == 'all':
        episodes_to_scrape = episode_links
    else:
        print("Invalid mode. Use 'latest', 'test', or 'all'.")
        return

    # XML setup
    rss = ET.Element("rss", version="2.0", attrib={"xmlns:itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"})
    channel = ET.SubElement(rss, "channel")
    
    ET.SubElement(channel, "title").text = "This American Archive"
    ET.SubElement(channel, "link").text = BASE_URL
    ET.SubElement(channel, "description").text = "Autogenerated feed of the This American Life archive."
    ET.SubElement(channel, "language").text = "en"
    ET.SubElement(channel, "copyright").text = "Copyright © Ira Glass / This American Life"
    ET.SubElement(channel, "itunes:image", href="https://i.imgur.com/pTMCfn9.png")

    for link in episodes_to_scrape:
        href = link['href']
        title = link.text.strip()
        
        # Extract episode number and slug from the href
        match = re.search(r'/(\d+)/(.+)', href)
        if not match:
            continue
            
        episode_num = match.group(1)
        slug = match.group(2)
        
        print(f"Scraping episode {episode_num}: {title}")
        
        episode_url = f"{BASE_URL}{href}"
        episode_soup = get_page_content(episode_url)
        
        if not episode_soup:
            continue
        
        details = get_episode_details(episode_soup)
        
        is_repeat = episode_num in repeat_episodes
        
        # Create standard item
        if 'standard_audio_url' in details:
            item = create_item(episode_num, title, slug, details, is_clean=False, is_repeat=is_repeat)
            channel.append(item)
            
        # Create clean item if available
        if 'clean_audio_url' in details:
            item = create_item(episode_num, title, slug, details, is_clean=True, is_repeat=is_repeat)
            channel.append(item)

        time.sleep(SLEEP_TIME)

    # Write the XML to file
    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ", level=0)  # For pretty printing
    
    try:
        tree.write(OUTPUT_FILE, encoding='utf-8', xml_declaration=True)
        print(f"Successfully wrote feed to {OUTPUT_FILE}")
    except Exception as e:
        print(f"Error writing XML file: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tal_scraper.py [mode]")
        print("Modes: latest, test, all")
    else:
        main(sys.argv[1].lower())
