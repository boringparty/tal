#!/usr/bin/env python3

import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from datetime import datetime, timedelta
import time
import random
from lxml import etree

BASE_XML = "base.xml"
FEED_XML = "feed.xml"
SCRAPER_MODE = "latest"  # Change or override via env: "test5", "all", "latest"

session = requests.Session()

def parse_episode_number(title):
    if ":" in title:
        return title.split(":")[0].strip()
    return title.strip()

def clean_audio_url(url):
    return url.split("?")[0]

def build_description(episode_soup):
    desc_parts = []
    # main description
    main_desc = episode_soup.select_one("meta[name='description']")
    if main_desc:
        desc_parts.append(main_desc["content"].strip())

    # acts
    for act in episode_soup.select("div.field-items > div.field-item > article.node-act"):
        act_label = act.select_one(".field-name-field-act-label .field-item")
        act_title = act.select_one("h2.act-header a")
        act_body = act.select_one(".field-name-body .field-item")
        if act_label and act_title and act_body:
            label_text = act_label.get_text(strip=True)
            title_text = act_title.get_text(strip=True)
            if label_text.lower() == "prologue":
                label_text = "Prologue"
                desc_parts.append(f"{label_text}\n{act_body.get_text(strip=True)}")
            else:
                desc_parts.append(f"{label_text}: {title_text}\n{act_body.get_text(strip=True)}")
    return "\n\n".join(desc_parts)

def episode_explicit(episode_soup):
    for clean_link in episode_soup.select('a[href*="clean"]'):
        return False
    return True

def fetch_archive_pages(limit=None):
    archive_url = "https://www.thisamericanlife.org/archive"
    pages = []
    while archive_url:
        print(f"Fetching archive page {archive_url}")
        r = session.get(archive_url)
        content = r.json()["html"] if "application/json" in r.headers.get("Content-Type", "") else r.content
        archive = BeautifulSoup(content, "html.parser")
        pages.append(archive)
        next_link = archive.select_one("a.pager")
        archive_url = urljoin("https://www.thisamericanlife.org", next_link["href"]) if next_link else None
        if limit and len(pages) >= limit:
            break
        time.sleep(random.uniform(0.5, 1.5))  # polite pause
    return pages

def fetch_episodes(limit=None):
    pages = fetch_archive_pages(limit if SCRAPER_MODE=="test5" else None)
    episodes = []
    for page in pages:
        for link in page.select("header > a.goto-episode"):
            url = urljoin("https://www.thisamericanlife.org", link["href"])
            r = session.get(url)
            episode = BeautifulSoup(r.content, "html.parser")
            title = episode.select_one("h1#page-title").get_text(strip=True)
            number = parse_episode_number(title)
            desc = build_description(episode)
            pub_date_span = episode.select_one("span.date-display-single")
            pub_date = datetime.strptime(pub_date_span.get_text(strip=True), "%B %d, %Y") if pub_date_span else datetime.utcnow()
            audio_script = episode.select_one("script#playlist-data")
            if not audio_script:
                continue
            audio_data = json.loads(audio_script.string)
            if "audio" not in audio_data:
                continue
            audio_url = clean_audio_url(audio_data["audio"])
            episodes.append({
                "title": title,
                "url": url,
                "number": number,
                "description": desc,
                "pubDate": pub_date,
                "audio": audio_url,
                "explicit": episode_explicit(episode),
                "episode_soup": episode
            })
            time.sleep(random.uniform(0.5, 1.5))  # polite pause
    return episodes

def write_feed(episodes):
    parser = etree.XMLParser(remove_blank_text=True)
    with open(BASE_XML, "r", encoding="utf-8") as f:
        tree = etree.parse(f, parser)
    channel = tree.find("channel")

    # Remove duplicates: keep unique episode numbers
    existing_numbers = set()
    for item in channel.findall("item"):
        ep = item.find("itunes:episode", namespaces={"itunes":"http://www.itunes.com/dtds/podcast-1.0.dtd"})
        if ep is not None:
            existing_numbers.add(ep.text)

    # Sort episodes latest first
    episodes.sort(key=lambda e: e["pubDate"], reverse=True)

    for ep in episodes:
        if ep["number"] in existing_numbers and SCRAPER_MODE=="latest":
            continue
        # explicit version
        item = etree.SubElement(channel, "item")
        etree.SubElement(item, "title").text = ep["title"]
        etree.SubElement(item, "link").text = ep["url"]
        itunes_ns = {"itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd"}
        etree.SubElement(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}episode").text = ep["number"]
        etree.SubElement(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}episodeType").text = "full"
        etree.SubElement(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}explicit").text = "yes" if ep["explicit"] else "no"
        etree.SubElement(item, "description").text = ep["description"]
        etree.SubElement(item, "pubDate").text = ep["pubDate"].strftime("%a, %d %b %Y %H:%M:%S +0000")
        etree.SubElement(item, "enclosure", url=ep["audio"], type="audio/mpeg")
        # clean version if exists
        if not ep["explicit"]:
            clean_item = etree.SubElement(channel, "item")
            etree.SubElement(clean_item, "title").text = ep["title"] + " (Clean)"
            etree.SubElement(clean_item, "link").text = ep["url"]
            etree.SubElement(clean_item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}episode").text = ep["number"]
            etree.SubElement(clean_item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}episodeType").text = "full"
            etree.SubElement(clean_item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}explicit").text = "no"
            etree.SubElement(clean_item, "description").text = ep["description"]
            etree.SubElement(clean_item, "pubDate").text = ep["pubDate"].strftime("%a, %d %b %Y %H:%M:%S +0000")
            etree.SubElement(clean_item, "enclosure", url=ep["audio"], type="audio/mpeg")

    tree.write(FEED_XML, pretty_print=True, xml_declaration=True, encoding="utf-8")

def main():
    episodes = fetch_episodes(limit=5 if SCRAPER_MODE=="test5" else None)
    write_feed(episodes)
    print(f"Wrote {FEED_XML} with {len(episodes)} episodes")

if __name__ == "__main__":
    main()
