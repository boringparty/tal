#!/usr/bin/env python3

import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

...

archive_url = "https://www.thisamericanlife.org/archive"
session = requests.Session()

while archive_url:
    print(f"Fetching {archive_url}")
    r = session.get(archive_url)
    content = r.json()["html"] if "application/json" in r.headers.get("Content-Type", "") else r.content
    archive = BeautifulSoup(content, "html.parser")

    for episode_link in archive.select("header > a.goto-episode"):
        full_url = urljoin("https://www.thisamericanlife.org", episode_link["href"])
        ...
    
    next_link = archive.select_one("a.pager")
    archive_url = urljoin("https://www.thisamericanlife.org", next_link["href"]) if next_link else None
