#!/usr/bin/env python3

import os
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse
from datetime import datetime, timedelta
from lxml import etree

# --- CONFIG ---
MODE = os.getenv("SCRAPER_MODE", "test5")  # "test5" | "all" | "new_only"
MAX_EPISODES = 5 if MODE == "test5" else None
pull_everything = MODE == "all"
pull_new_only = MODE == "new_only"

BASE_XML_FILE = "base.xml"
FEED_FILE = "feed.xml"
ARCHIVE_URL = "https://www.thisamericanlife.org/archive"

# --- LOAD FEED ---
if pull_new_only and os.path.exists(FEED_FILE):
    with open(FEED_FILE, "r", encoding="utf-8") as f:
        feed_soup = BeautifulSoup(f.read(), "xml")
else:
    with open(BASE_XML_FILE, "r", encoding="utf-8") as f:
        feed_soup = BeautifulSoup(f.read(), "xml")

channel = feed_soup.find("channel")

# --- TRACK EXISTING EPISODES ---
existing_episodes = {item.find("itunes:episode").text.strip()
                     for item in channel.find_all("item") if item.find("itunes:episode")}

# --- SETUP ---
session = requests.Session()
today = datetime.utcnow()
yesterday = today - timedelta(days=1)

def get_clean_url(url):
    parsed = urlparse(url)
    return urlunparse(parsed._replace(query=""))

def clean_text(text):
    return text.strip() if text else ""

def build_description(episode_soup):
    parts = []
    meta_desc = episode_soup.select_one("meta[name='description']")
    if meta_desc:
        parts.append(clean_text(meta_desc.get("content")))

    # Acts
    for act in episode_soup.select("article.node-act"):
        if act.find_parent("section", class_="related"):
            continue

        act_label_tag = act.select_one(".field-name-field-act-label .field-item")
        act_title_tag = act.select_one(".act-header a.goto-act")
        act_desc_tag = act.select_one(".field-name-body .field-item p")

        act_label = clean_text(act_label_tag.text if act_label_tag else "")
        act_title = clean_text(act_title_tag.text if act_title_tag else "")
        act_desc = clean_text(act_desc_tag.text if act_desc_tag else "")

        # Avoid "Prologue: Prologue"
        if act_label.lower() == "prologue":
            act_label_text = act_label
            if act_title.lower() != "prologue" and act_title:
                act_label_text += f": {act_title}"
        else:
            act_label_text = f"{act_label}: {act_title}" if act_label and act_title else act_label or act_title

        if act_label_text:
            parts.append(act_label_text)
        if act_desc:
            parts.append(act_desc)

    return "\n\n".join(parts)

def make_item(feed_soup, title, ep_num, explicit, audio_url, link, pub_date, description):
    item_tag = feed_soup.new_tag("item")

    for tag_name, text in [
        ("title", title),
        ("link", link),
        ("itunes:episode", ep_num),
        ("itunes:episodeType", "full"),
        ("itunes:explicit", explicit),
        ("description", description),
        ("pubDate", pub_date)
    ]:
        t = feed_soup.new_tag(tag_name)
        t.string = text
        item_tag.append(t)

    enclosure_tag = feed_soup.new_tag("enclosure")
    enclosure_tag["url"] = audio_url
    enclosure_tag["type"] = "audio/mpeg"
    item_tag.append(enclosure_tag)

    return item_tag

# --- SCRAPE ARCHIVE ---
archive_url = ARCHIVE_URL
episode_count = 0

while archive_url:
    print(f"Fetching {archive_url}")
    r = session.get(archive_url)
    content = r.json()["html"] if "application/json" in r.headers.get("Content-Type", "") else r.content
    archive_soup = BeautifulSoup(content, "html.parser")

    for link_tag in archive_soup.select("header > a.goto-episode"):
        if MAX_EPISODES and episode_count >= MAX_EPISODES:
            break

        full_url = urljoin("https://www.thisamericanlife.org", link_tag["href"])
        ep_slug = full_url.rstrip("/").split("/")[-1]
        print(f"Scraping episode {ep_slug}")

        r_episode = session.get(full_url)
        episode_soup = BeautifulSoup(r_episode.content, "html.parser")

        # --- Episode date ---
        date_span = episode_soup.select_one("span.date-display-single")
        try:
            ep_date = datetime.strptime(date_span.text.strip(), "%B %d, %Y") if date_span else None
        except Exception:
            ep_date = None
        pub_date_str = ep_date.strftime("%a, %d %b %Y 00:00:00 +0000") if ep_date else ""

        # --- Playlist / audio ---
        script_tag = episode_soup.select_one("script#playlist-data")
        if not script_tag:
            continue
        player_data = json.loads(script_tag.string)
        if "audio" not in player_data:
            continue

        title_full = clean_text(player_data["title"])
        ep_num = title_full.split(":", 1)[0].strip()

        if pull_new_only:
            if ep_num in existing_episodes:
                continue
            if ep_date and ep_date.date() < yesterday.date():
                continue

        existing_episodes.add(ep_num)
        episode_count += 1

        audio_url = get_clean_url(player_data["audio"])
        description = build_description(episode_soup)

        # --- Add main episode ---
        channel.append(make_item(feed_soup, title_full, ep_num, "yes", audio_url, full_url, pub_date_str, description))

        # --- Add clean version if exists ---
        clean_tag = episode_soup.select_one('a[href*="clean"]')
        if clean_tag:
            clean_audio_url = urljoin("https://www.thisamericanlife.org", clean_tag["href"])
            channel.append(make_item(feed_soup, f"{title_full} (Clean)", ep_num, "no",
                                     clean_audio_url, full_url, pub_date_str, description))

    next_link = archive_soup.select_one("a.pager")
    archive_url = urljoin("https://www.thisamericanlife.org", next_link["href"]) if pull_everything and next_link else None

# --- SORT ITEMS: latest first ---
items = channel.find_all("item")
items_sorted = sorted(items, key=lambda x: int(x.find("itunes:episode").text.strip()), reverse=True)
for item in items:
    item.extract()
for item in items_sorted:
    channel.append(item)

# --- WRITE PRETTY XML ---
def write_feed_lxml(feed_soup, filename=FEED_FILE):
    # Convert BeautifulSoup to string and parse with lxml
    xml_str = str(feed_soup)
    parser = etree.XMLParser(remove_blank_text=True)
    root = etree.fromstring(xml_str.encode("utf-8"), parser)
    tree = etree.ElementTree(root)
    tree.write(filename, pretty_print=True, encoding="utf-8", xml_declaration=True)

write_feed_lxml(feed_soup)
