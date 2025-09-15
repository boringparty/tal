#!/usr/bin/env python3

import os
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urlunparse
from datetime import datetime, timedelta

# --- CONFIGURATION ---
MODE = os.getenv("SCRAPER_MODE", "test5")  # "test5" | "all" | "new_only"
MAX_EPISODES = 5 if MODE == "test5" else None
pull_everything = MODE == "all"
pull_new_only = MODE == "new_only"

# --- LOAD FEED ---
if pull_new_only and os.path.exists("feed.xml"):
    with open("feed.xml", "r") as f:
        feed = BeautifulSoup(f.read(), "xml")
else:
    with open("base.xml", "r") as f:
        feed = BeautifulSoup(f.read(), "xml")

channel = feed.find("channel")

# Track existing episodes to avoid duplicates
existing_episodes = set()
for item in channel.find_all("item"):
    ep_tag = item.find("itunes:episode")
    if ep_tag:
        existing_episodes.add(ep_tag.text.strip())

# --- SETUP ---
archive_url = "https://www.thisamericanlife.org/archive"
session = requests.Session()
today = datetime.utcnow()
yesterday = today - timedelta(days=1)

# --- SCRAPING LOOP ---
while archive_url:
    print(f"Fetching {archive_url}")
    r = session.get(archive_url)
    content = r.json()["html"] if "application/json" in r.headers.get("Content-Type", "") else r.content
    archive = BeautifulSoup(content, "html.parser")

    count = 0
    for episode_link in archive.select("header > a.goto-episode"):
        if MAX_EPISODES and count >= MAX_EPISODES:
            break

        full_url = urljoin("https://www.thisamericanlife.org", episode_link["href"])
        episode_slug = full_url.rstrip("/").split("/")[-1]
        print(f"Scraping episode {episode_slug}")

        r_episode = session.get(full_url)
        episode = BeautifulSoup(r_episode.content, "html.parser")

        # --- Episode date ---
        date_span = episode.select_one("span.date-display-single")
        episode_date = None
        if date_span:
            try:
                episode_date = datetime.strptime(date_span.text.strip(), "%B %d, %Y")
            except Exception:
                pass

        # Skip old episodes if mode is new_only
        title_meta = episode.select_one("script#playlist-data")
        if not title_meta:
            continue
        player_data = json.loads(title_meta.string)
        if "audio" not in player_data:
            continue
        ep_num = player_data["title"].split(":", 1)[0].strip()
        if pull_new_only:
            if ep_num in existing_episodes:
                continue
            if episode_date and episode_date.date() < yesterday.date():
                continue

        # --- Audio ---
        audio_url = player_data["audio"]
        final_url = session.head(audio_url, allow_redirects=True).url
        parsed = urlparse(final_url)
        clean_url = urlunparse(parsed._replace(query=""))

        if "/promos/" in clean_url:
            player_data["title"] += " (Promo)"

        # --- Build item function ---
        def make_item(title_text, explicit_val, audio_link):
            item_tag = feed.new_tag("item")

            title_tag = feed.new_tag("title")
            title_tag.string = title_text.strip()
            item_tag.append(title_tag)

            link_tag = feed.new_tag("link")
            link_tag.string = full_url.strip()
            item_tag.append(link_tag)

            itunes_tag = feed.new_tag("itunes:episode")
            itunes_tag.string = ep_num.strip()
            item_tag.append(itunes_tag)

            ep_type_tag = feed.new_tag("itunes:episodeType")
            ep_type_tag.string = "full"
            item_tag.append(ep_type_tag)

            explicit_tag = feed.new_tag("itunes:explicit")
            explicit_tag.string = explicit_val
            item_tag.append(explicit_tag)

            desc_meta = episode.select_one("meta[name='description']")
            desc_tag = feed.new_tag("description")
            desc_tag.string = desc_meta["content"].strip() if desc_meta else ""
            item_tag.append(desc_tag)

            pub_date_tag = feed.new_tag("pubDate")
            pub_date_tag.string = episode_date.strftime("%a, %d %b %Y 00:00:00 +0000") if episode_date else ""
            item_tag.append(pub_date_tag)

            enclosure_tag = feed.new_tag("enclosure")
            enclosure_tag["url"] = audio_link
            enclosure_tag["type"] = "audio/mpeg"
            item_tag.append(enclosure_tag)

            return item_tag

        # Append main episode
        channel.append(make_item(player_data["title"], "yes", clean_url))
        existing_episodes.add(ep_num)
        count += 1

        # --- Check for clean version ---
        clean_link_tag = episode.select_one('a[href*="clean"]')
        if clean_link_tag:
            clean_audio_url = urljoin("https://www.thisamericanlife.org", clean_link_tag["href"])
            channel.append(make_item(player_data["title"] + " (Clean)", "no", clean_audio_url))

    # --- Next page ---
    next_link = archive.select_one("a.pager")
    if pull_everything and next_link:
        archive_url = urljoin("https://www.thisamericanlife.org", next_link["href"])
    else:
        archive_url = None

# --- Sort items numerically ---
items = channel.find_all("item")
items_sorted = sorted(items, key=lambda x: int(x.find("itunes:episode").text.strip()))
for item in items:
    item.extract()
for item in items_sorted:
    channel.append(item)

# --- Write feed.xml with compact formatting ---
with open("feed.xml", "w") as out:
    xml_str = feed.prettify()
    compact_xml = "\n".join([line.strip() for line in xml_str.splitlines() if line.strip()])
    out.write(compact_xml)
