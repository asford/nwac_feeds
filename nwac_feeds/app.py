import attr
import typing

from flask import Flask, render_template, Response, request

import requests
from bs4 import BeautifulSoup
import dateparser

from functools import wraps, lru_cache
from inspect import signature

import logging
import structlog

log = structlog.get_logger()


def logf(f, log=log):
    lname = f.__qualname__
    sig = signature(f)

    @wraps(f)
    def wrapper(*args, **kwargs):
        log.info(lname, **sig.bind(*args, **kwargs).arguments)
        try:
            return f(*args, **kwargs)
        except BaseException:
            log.exception(lname)
            raise

    return wrapper


app = Flask(__name__)


@attr.s(auto_attribs=True)
class Entry:
    id: str
    title: str
    updated: str

    summary: str
    content: str
    link: str


@attr.s(auto_attribs=True)
class Feed:
    id: str
    title: str
    link: str

    updated: str
    entry_urls: typing.Tuple[str, ...]
    entries: typing.Tuple[Entry, ...]


def norm(string):
    return " ".join(string.split())


base_url = "http://nwac.us/"


@logf
def get_mw_feed(url):
    toplevel_req = requests.get(url)

    toplevel_req.raise_for_status()

    toplevel = BeautifulSoup(toplevel_req.text)

    links = [
        base_url + a.attrs["href"]
        for a in toplevel.find(id="main-content").find_all("a")
        if "mountain-weather-forecast" in a.attrs["href"]
    ]

    log.info("get_mw_feed.get_archive_links", links=links)

    entries = [get_mw_entry(l) for l in links]

    last_entry_updated = max([dateparser.parse(e.updated) for e in entries]).isoformat()

    return Feed(
        id=url,
        link=url,
        title="NWAC Mountain Weather Forecast",
        updated=last_entry_updated,
        entry_urls=links,
        entries=entries,
    )


@logf
def fetch_mw_forecast(url):
    req = requests.get(url)
    req.raise_for_status()
    return req.text


def decompose(e):
    if e:
        e.decompose()


def tidy_mw_content(content):
    decompose(content.find("aside"))
    jump_bar = [p for p in content.find_all("p") if "Jump to" in p.text][0]
    synopsis = content.find(class_="synopsis")
    synopsis.insert_after(jump_bar)
    return content


@logf
@lru_cache(maxsize=128)
def get_mw_entry(url):
    forecast = BeautifulSoup(fetch_mw_forecast(url)).find(id="main-content")
    log.info("main-content", pretty=forecast.prettify())

    updated = dateparser.parse(
        norm(forecast.find("div", class_="forecast-date").text.replace("Issued:", ""))
    ).isoformat()

    title = norm(forecast.find("div", class_="forecast-date").text)
    summary = forecast.find("div", class_="synopsis").prettify()
    content = tidy_mw_content(forecast).prettify()

    return Entry(
        id=url, link=url, title=title, updated=updated, summary=summary, content=content
    )


@app.route("/mountain-weather-forecast/atom.xml")
def mountain_weather_forecast_feed():
    feed = get_mw_feed(base_url + "mountain-weather-forecast/archives/")

    return Response(
        render_template("atom.xml", feed=feed, feed_url=request.base_url),
        mimetype="application/xml",
    )


if __name__ == "__main__":
    logging.basicConfig()
    structlog.configure(logger_factory=structlog.stdlib.LoggerFactory())
    app.run()
