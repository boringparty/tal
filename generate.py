#!/usr/bin/env python3

import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Read base.xml
with open("base.xml", "r") as f:
    feed = BeautifulSoup(f.read(), "xml")

channel = feed.find("channel")

archive_url = "https://www.thisamericanlife.org/archive"
session = requests.Session()

while archive_url:
    print(f"Fetching {archive_url}")
    r = session.get(archive_url)
    content = r.json()["html"] if "application/json" in r.headers.get("Content-Type", "") else r.content
    archive = BeautifulSoup(content, "html.parser")

    for episode_link in archive.select("header > a.goto-episode"):
        full_url = urljoin("https://www.thisamericanlife.org", episode_link["href"])
        r_episode = session.get(full_url)
        episode = BeautifulSoup(r_episode.content, "html.parser")

        # Grab audio data
        player_data_tag = episode.select_one("script#playlist-data")
        if not player_data_tag:
            continue
        player_data = json.loads(player_data_tag.string)

        if "audio" not in player_data:
            continue

        if "/promos/" in player_data["audio"]:
            player_data["title"] += " (Promo)"

        # Build RSS item
        title_tag = feed.new_tag("title")
        title_tag.string = player_data["title"]

        link_tag = feed.new_tag("link")
        link_tag.string = full_url

        pub_meta = episode.select_one("meta[property='article:published_time']")
        pub_date_tag = feed.new_tag("pubDate")
        pub_date_tag.string = pub_meta["content"] if pub_meta else ""

        desc_meta = episode.select_one("meta[name='description']")
        desc_tag = feed.new_tag("description")
        desc_tag.string = desc_meta["content"] if desc_meta else ""

        enclosure_tag = feed.new_tag("enclosure")
        enclosure_tag["url"] = player_data["audio"]
        enclosure_tag["type"] = "audio/mpeg"

        item_tag = feed.new_tag("item")
        item_tag.append(title_tag)
        item_tag.append(link_tag)
        item_tag.append(enclosure_tag)
        item_tag.append(desc_tag)
        item_tag.append(pub_date_tag)

        channel.append(item_tag)

    next_link = archive.select_one("a.pager")
    archive_url = urljoin("https://www.thisamericanlife.org", next_link["href"]) if next_link else None

# Write updated feed.xml
with open("feed.xml", "w") as out:
    out.write(feed.prettify())
