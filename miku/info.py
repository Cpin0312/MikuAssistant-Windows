"""ネットから読む情報：天気（tenki.jp）・ニュース（Google ニュース）・電車（Yahoo!路線情報）・イベント（いこうよ）・今いる場所"""
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

import requests

from .settings import data_dir, settings

AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_cache_file = data_dir() / "cache.json"


def _cache() -> dict:
    try:
        return json.loads(_cache_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _remember(key: str, value: str):
    c = _cache()
    c[key] = value
    _cache_file.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")


def get(url: str, timeout: int = 20) -> str:
    r = requests.get(url, headers={"User-Agent": AGENT, "Accept-Language": "ja,en;q=0.8"}, timeout=timeout)
    r.encoding = r.apparent_encoding if not r.encoding or r.encoding.lower() == "iso-8859-1" else r.encoding
    return r.text


def first(pattern: str, s: str):
    m = re.search(pattern, s, re.S)
    return m.group(1) if m else None


def strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s).replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", s).strip()


# ---------- 今いる場所（IP から市区町村。設定 [天気の場所] に書けばそちらを使う） ----------

def place_name():
    v = settings.lines("天気の場所")
    if v and v[0] != "自動":
        return v[0]
    # ネットの住所から市区町村（日本語で返すサービスを先に）。覚えておいて、毎回は聞かない
    c = _cache()
    if c.get("place"):
        return c["place"]
    for url, keys in [("http://ip-api.com/json/?lang=ja&fields=city,regionName", ("city", "regionName")),
                      ("https://ipinfo.io/json", ("city", "region")), ("https://ipapi.co/json/", ("city", "region"))]:
        try:
            j = requests.get(url, headers={"User-Agent": AGENT}, timeout=10).json()
        except Exception:
            continue
        place = j.get(keys[0]) or j.get(keys[1])
        if place:
            _remember("place", place)
            return place
    return None


# ---------- 天気 ----------

def _forecast_url(place: str) -> str:
    key = "tenki." + place
    c = _cache()
    if key in c:
        return c[key]
    html = get("https://tenki.jp/search/?keyword=" + urllib.parse.quote(place))
    path = first(r'href="(/forecast/[0-9]+/[0-9]+/[0-9]+/[0-9]+/)"', html)
    if not path:
        raise RuntimeError(f"tenki.jp で「{place}」が見つからなかったよ")
    url = "https://tenki.jp" + path
    _remember(key, url)
    return url


def _day(html: str, cls: str, label: str):
    i = html.find(f'class="{cls}')
    if i < 0:
        return None
    seg = html[i:i + 6000]
    telop = first(r'<p class="weather-telop">([^<]*)</p>', seg)
    if not telop:
        return None
    high = first(r'class="high-temp temp">\s*<span class="value">([^<]*)</span>', seg) or "-"
    low = first(r'class="low-temp temp">\s*<span class="value">([^<]*)</span>', seg) or "-"
    rain = []
    row = first(r'<tr class="rain-probability">(.*?)</tr>', seg)
    if row:
        rain = [strip_tags("<td" + p) for p in row.split("<td")[1:]]
    nums = [int(re.sub(r"\D", "", r)) for r in rain if re.sub(r"\D", "", r)]
    return {"label": label, "telop": telop, "high": high, "low": low, "rain": rain, "max_rain": max(nums) if nums else 0}


def weather():
    place = place_name()
    if not place:
        raise RuntimeError("今いる場所がわからなかったよ。設定ファイルの[天気の場所]に「福岡市西区」のように書いてね")
    url = _forecast_url(place)
    html = get(url)
    name = first(r"<title>(.+?)の今日明日の天気", html) or place
    return {"place": name, "today": _day(html, "today-weather", "今日"), "tomorrow": _day(html, "tomorrow-weather", "明日"), "url": url}


def weather_text(day_offset: int = 0) -> str:
    r = weather()
    d = r["tomorrow"] if day_offset else r["today"]
    if not d:
        return f"{r['place']}の天気が読めなかった…"
    periods = ["0-6時", "6-12時", "12-18時", "18-24時"]
    rain = [f"　{p}：{v.replace(' ', '')}" for p, v in zip(periods, d["rain"])]
    out = [f"☀️ {r['place']}の{d['label']}の天気", d["telop"], f"最高：{d['high']}℃", f"最低：{d['low']}℃", "降水確率"] + rain
    if d["max_rain"] >= 50:
        out.append("☂️ 傘を持っていってね")
    return "\n".join(out)


# ---------- ニュース ----------

WORLD = "https://news.google.com/rss/headlines/section/topic/WORLD?hl=ja&gl=JP&ceid=JP:ja"
NATION = "https://news.google.com/rss/headlines/section/topic/NATION?hl=ja&gl=JP&ceid=JP:ja"


def news(url: str, count: int):
    root = ET.fromstring(get(url).encode("utf-8"))
    items = []
    for it in root.iter("item"):
        title = it.findtext("title") or ""
        source = it.findtext("source") or ""
        if " - " in title:
            title, src = title.rsplit(" - ", 1)
            source = source or src
        items.append({"title": title, "source": source, "link": it.findtext("link") or ""})
        if len(items) >= count:
            break
    return items


def news_text() -> str:
    w = news(WORLD, settings.int("ニュース", "国際", 3))
    n = news(NATION, settings.int("ニュース", "国内", 3))
    out = ["📰 最新のニュース", "【国際】"] + [f"・{i['title']}（{i['source']}）" for i in w]
    out += ["【国内】"] + [f"・{i['title']}（{i['source']}）" for i in n]
    return "\n".join(out)


# ---------- 電車 ----------

def _train_url(line: str):
    key = "train." + line
    c = _cache()
    if key in c:
        return c[key]
    if line.startswith("http"):
        return line
    partial = None
    for area in range(1, 9):
        try:
            html = get(f"https://transit.yahoo.co.jp/diainfo/area/{area}")
        except Exception:
            continue
        for path, name in re.findall(r'href="(?:https://transit.yahoo.co.jp)?(/diainfo/[0-9]+/[0-9]+)"[^>]*>([^<]+)<', html):
            name = name.strip()
            url = "https://transit.yahoo.co.jp" + path
            if name == line:
                _remember(key, url)
                return url
            if partial is None and line in name:
                partial = url
    if partial:
        _remember(key, partial)
    return partial


def train(line: str):
    url = _train_url(line)
    if not url:
        return None
    html = get(url)
    status = first(r'"status":"([^"]+)"', html) or ""
    message = ""
    i = html.find('mdServiceStatus">')
    if i >= 0:
        text = strip_tags(html[i + len('mdServiceStatus">'):i + 3000])
        if not status:
            status = text.split(" ")[0] if text else ""
        if status and status in text:
            message = text.split(status, 1)[1].split("（")[0].split(" 迂回ルート")[0].strip()[:90]
    name = first(r'<h1 class="title">([^<]+)</h1>', html) or line
    return {"line": name, "status": status or "不明", "message": message, "url": url}


def trains_text() -> str:
    lines = settings.lines("電車")
    if not lines:
        return "設定ファイルの[電車]に路線名を書いてね"
    out = []
    for l in lines:
        t = train(l)
        out.append(f"🚃 {t['line']}：{t['status']}" + (f"\n　{t['message']}" if t and t["message"] else "") if t else f"🚃 {l}：見つからなかったよ")
    return "\n".join(out)


# ---------- イベント（いこうよ） ----------

def events(text: str):
    data = requests.get("https://ikouyo.vercel.app/events_data.json", headers={"User-Agent": AGENT}, timeout=20).json()
    area = settings.value("イベント", "地域") or "福岡県"
    for p in ["北海道", "東京都", "大阪府", "京都府"] + [x + "県" for x in "青森 岩手 宮城 秋田 山形 福島 茨城 栃木 群馬 埼玉 千葉 神奈川 新潟 富山 石川 福井 山梨 長野 岐阜 静岡 愛知 三重 滋賀 兵庫 奈良 和歌山 鳥取 島根 岡山 広島 山口 徳島 香川 愛媛 高知 福岡 佐賀 長崎 熊本 大分 宮崎 鹿児島 沖縄".split()]:
        if p in text or (p != "北海道" and p[:-1] in text):
            area = p
            break
    today = date.today()
    start, end, label = today, today + timedelta(days=14), "これから2週間"
    if "今日" in text:
        end, label = today, "今日"
    elif "明日" in text:
        start = end = today + timedelta(days=1); label = "明日"
    elif "週末" in text or "土日" in text:
        sat = today + timedelta(days=(5 - today.weekday()) % 7)
        start, end, label = sat, sat + timedelta(days=1), "今週末"
    hits = []
    for e in data.get("events", []):
        try:
            s = datetime.strptime(e["date"], "%Y-%m-%d").date()
            en = datetime.strptime(e.get("endDate") or e["date"], "%Y-%m-%d").date()
        except Exception:
            continue
        if e.get("prefecture") == area and s <= end and en >= start:
            hits.append({**e, "_s": s, "_e": max(s, en)})
    hits.sort(key=lambda e: ((e["_e"] - e["_s"]).days > 60, e["_s"]))
    return area, label, hits, start


def events_text(text: str) -> str:
    area, label, hits, start = events(text)
    if not hits:
        return f"🎪 {area}の{label}のイベントは見つからなかったよ"
    out = [f"🎪 {area}・{label}のイベント（いこうよ）"]
    for e in hits[:6]:
        s, en = e["_s"], e["_e"]
        when = (f"開催中（〜{en.month}/{en.day}）" if s < start else f"{s.month}/{s.day}" + (f"〜{en.month}/{en.day}" if en > s else ""))
        out.append(f"・{e['title']}（{when}・{e.get('place', '')}）")
    return "\n".join(out)
