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
    with open("feed.xml", "r", encoding="utf-8") as f:
        feed = BeautifulSoup(f.read(), "xml")
else:
    with open("base.xml", "r", encoding="utf-8") as f:
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
        ep_slug = full_url.rstrip("/").split("/")[-1]
        print(f"Scraping episode {ep_slug}")

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

        # --- Playlist / audio ---
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

        # --- Audio URLs ---
        audio_url = player_data["audio"]
        final_url = session.head(audio_url, allow_redirects=True).url
        parsed = urlparse(final_url)
        clean_url = urlunparse(parsed._replace(query=""))

        if "/promos/" in clean_url:
            player_data["title"] += " (Promo)"

        # --- Build full description ---
        desc_parts = []
        meta_desc = episode.select_one("meta[name='description']")
        if meta_desc:
            desc_parts.append(meta_desc["content"].strip())

        # Loop through acts, skipping related section
        for act in episode.select("article.node-act"):
            if act.find_parent("section", class_="related"):
                continue  # skip related acts

            act_label_tag = act.select_one(".field-name-field-act-label .field-item")
            act_title_tag = act.select_one(".act-header a.goto-act")
            act_desc_tag = act.select_one(".field-name-body .field-item p")

            act_label = act_label_tag.text.strip() if act_label_tag else ""
            act_title = act_title_tag.text.strip() if act_title_tag else ""
            act_desc = act_desc_tag.text.strip() if act_desc_tag else ""

            # Avoid "Prologue: Prologue"
            if act_label.lower() == "prologue":
                act_label_text = act_label
                if act_title and act_title.lower() != "prologue":
                    act_label_text += f": {act_title}"
            else:
                act_label_text = f"{act_label}: {act_title}" if act_label and act_title else act_label or act_title

            if act_label_text:
                desc_parts.append(act_label_text)
            if act_desc:
                desc_parts.append(act_desc)

        full_description = "\n\n".join(desc_parts)

        # --- Function to make item ---
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

            desc_tag = feed.new_tag("description")
            desc_tag.string = full_description
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

        # Append clean version if present
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

# --- Sort items: latest first ---
items = channel.find_all("item")
items_sorted = sorted(items, key=lambda x: int(x.find("itunes:episode").text.strip()), reverse=True)
for item in items:
    item.extract()
for item in items_sorted:
    channel.append(item)

# --- Pretty write function ---
def write_pretty_feed(feed, filename="feed.xml"):
    with open(filename, "w", encoding="utf-8") as out:
        out.write('<?xml version="1.0" encoding="utf-8"?>\n')
        rss_tag = feed.find("rss")
        attrs = " ".join([f'{k}="{v}"' for k, v in rss_tag.attrs.items()])
        out.write(f'<rss {attrs}>\n')

        channel = rss_tag.find("channel")
        for tag in channel.find_all(recursive=False):
            if tag.name == "item":
                continue
            out.write(f'\t<{tag.name}>{tag.text.strip()}</{tag.name}>\n')

        for item in channel.find_all("item"):
            out.write('\t<item>\n')
            for child in item.find_all(recursive=False):
                if child.name == "enclosure":
                    attrs = " ".join([f'{k}="{v}"' for k, v in child.attrs.items()])
                    out.write(f'\t\t<enclosure {attrs}/>\n')
                else:
                    out.write(f'\t\t<{child.name}>{child.text.strip()}</{child.name}>\n')
            out.write('\t</item>\n')

        out.write('</rss>\n')

# --- Write feed ---
write_pretty_feed(feed, "feed.xml")
