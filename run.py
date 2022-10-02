import os
from typing import Dict
import requests
import logging
from enum import Enum
import urllib.parse
from pprint import pprint
import json
import re

from pydantic import BaseModel
import coloredlogs
import typer
from typer import Argument, Option
from bs4 import BeautifulSoup as bs
import IPython
from torrentp import TorrentDownloader

logger = logging.getLogger(__name__)
coloredlogs.install(level="INFO")

app = typer.Typer()

base = "https://nyaa.si/"

class Filter(str, Enum):
    no_filter = "no-filter"
    no_remakes = "no-remakes"
    trusted_only = "trusted-only"

    def __int__(self):
        if self is Filter.no_filter:
            return 0
        elif self is Filter.no_remakes:
            return 1
        elif self is Filter.trusted_only:
            return 2

        raise TypeError()

class Category(str, Enum):
    all = "all"
    anime = "anime"
    amv = "amv"
    anime_eng = "anime-eng"
    anime_non_eng = "anime-non-eng"
    anime_raw = "anime-raw"
    audio = "audio"
    audio_lossless = "audio-lossless"
    audio_lossy = "audio-lossy"
    lit = "literature"
    lit_eng = "literature-eng"
    lit_non_eng = "literature-non-eng"
    lit_raw = "literature-raw"
    live_action = "live-action"
    live_action_eng = "live-action-eng"
    live_action_idol_pv = "live-action-idol-pv"
    live_action_non_eng = "live-action-non_eng"
    live_action_raw = "live-action-raw"
    pictures = "pictures"
    graphics = "graphics"
    photos = "photos"
    software = "software"
    apps = "apps"
    games = "games"

    def __str__(self):
        if self is Category.all:
            return "0_0"
        elif self is Category.anime:
            return "1_0"
        elif self is Category.amv:
            return "1_1"
        elif self is Category.anime_eng:
            return "1_2"
        elif self is Category.anime_non_eng:
            return "1_3"
        elif self is Category.anime_raw:
            return "1_4"
        elif self is Category.audio:
            return "2_0"
        elif self is Category.audio_lossless:
            return "2_1"
        elif self is Category.audio_lossy:
            return "2_2"
        elif self is Category.lit:
            return "3_0"
        elif self is Category.lit_eng:
            return "3_1"
        elif self is Category.lit_non_eng:
            return "3_2"
        elif self is Category.lit_raw:
            return "3_3"
        elif self is Category.live_action:
            return "4_0"
        elif self is Category.live_action_eng:
            return "4_1"
        elif self is Category.live_action_idol_pv:
            return "4_2"
        elif self is Category.live_action_non_eng:
            return "4_3"
        elif self is Category.live_action_raw:
            return "4_4"
        elif self is Category.pictures:
            return "5_0"
        elif self is Category.graphics:
            return "5_1"
        elif self is Category.photos:
            return "5_2"
        elif self is Category.software:
            return "6_0"
        elif self is Category.apps:
            return "6_1"
        elif self is Category.games:
            return "6_2"

        raise TypeError

class Sort(str, Enum):
    comments = 'comments'
    size = 'size'
    id = 'id' # default
    seeders = 'seeders'
    leechers = 'leechers'
    downloads = 'downloads'

class Result(BaseModel):
    name:str
    link:str
    magnet:str
    size:str
    date:str
    seeders:int
    leechers:int
    dls:int

@app.command()
def search(
    query:str = Argument(..., help="String to search for"),
    filter:Filter = Argument(Filter.no_filter),
    category:Category = Argument(Category.all),
    sort:Sort = Argument(Sort.id),
    order:bool = Option(False, "--asc"),
    page:int = Option(1),
):
    count = 0
    for result in _search(query, filter, category, sort, order, page):
        pprint(result.dict())
        count += 1

def _search(query, filter=Filter.no_filter, category=Category.all, sort=Sort.id, order=False, page=1):
    query = urllib.parse.quote_plus(query)
    if order:
        order = "asc"
    else:
        order = "desc"

    url = f"{base}?f={int(filter)}&c={str(category)}&q={query}&s={sort}&o={order}&p={page}"

    results = []
    r = requests.get(url)
    if r.status_code == 200:
        soup = bs(r.text, 'html.parser')

        if not (soup.h3 is None):
            logger.info('No results found')
            return results
        
        pagination = soup.find_all('ul')[-1]
        max_page = pagination.find_all('li')[-2].text

        try:
            max_page = int(max_page)
        except ValueError:
            max_page = 1
        
        if page > max_page:
            raise ValueError(f"page {page} exceeds max page")

        for row in soup.find_all('tr')[1:]:
            cols = row.find_all('td')

            res = Result(
                name=cols[1].find_all('a')[-1].text,
                link=cols[2].a['href'],
                magnet=cols[2].find_all('a')[1]['href'],
                size=cols[3].text,
                date=cols[4].text,
                seeders=int(cols[5].text),
                leechers=int(cols[6].text),
                dls=int(cols[7].text)
            )
            results.append(res)
    else:
        raise ConnectionError(f"Could not reach {url}")
        
    return results  

@app.command()
def subscribe(config_file:str=Argument(..., help="JSON file containing the data to subscribe for")):
    return check_for_latest()

@app.command()
def poll(config_file:str=Argument(..., help="JSON file containing the data to subscribe for"), dryrun:bool=Option(False)):
    if not os.path.exists(config_file):
        logger.warn(f"config file does not exist: {config_file}")
        return

    with open(config_file, 'r') as f:
        config = json.load(f)

    output_dir = config['output_dir']
    watchers = config['watchers']

    for entry in watchers:
        res = check_for_latest(entry, output_dir, dryrun)

def check_for_latest(config_entry:Dict, output_dir, dryrun):
    query = config_entry['query']
    pattern = re.compile(config_entry['pattern'])
    category = Category(config_entry['category'])
    
    page = 0
    while True:
        try:
            results = _search(query, category=category, page=page, sort=Sort.id)
        except ValueError:
            break

        for res in results:
            m = re.match(pattern, res.name)
            if m:
                torrent_file = os.path.join(output_dir, "torrents", config_entry['name'], res.name + ".torrent")
                target_dir = os.path.join(output_dir, "Media", "videos", "shows", config_entry['name'])
                os.makedirs(target_dir)
                if not os.path.exists(torrent_file):
                    url = urllib.parse.urljoin(base, res.link)
                    r = requests.get(url)
                    logger.info(f"Saving: {torrent_file}")
                    if not dryrun:
                        with open(torrent_file, 'wb') as f:
                            f.write(r.content)

                    logger.info(f"Starting torrent!")
                    if not dryrun:
                        torrent = TorrentDownloader(torrent_file, target_dir)
                        torrent.start_download()
                else:
                    logger.info(f"Torrent File {res.name}.torrent already downloaded. Assuming its been torrented too")

        page += 1


if __name__ == "__main__":
    app()