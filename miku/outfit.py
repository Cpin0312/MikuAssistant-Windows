"""ミクの服（Mac 版と同じ決まり）
  先生（教えている間）→ ねむい（何もしていない・おやすみの時刻から朝まで）→ 手で選んだ服 → 仕事の時間（社畜・勉強）→ 季節×時間
  追加の服：%APPDATA%\\MikuAssistant_Win\\ミクの服\\ に「winter-night-2.png」のように番号付きで置く
"""
import random
import re
import time
from datetime import datetime
from pathlib import Path

from .settings import data_dir, resource_dir, settings, state

SEASONS = {"spring": "春", "summer": "夏", "autumn": "秋", "winter": "冬"}
TIMES = {"morning": "朝", "day": "昼", "night": "夜"}
CHAR = resource_dir() / "character"


def user_dir() -> Path:
    d = data_dir() / "ミクの服"
    d.mkdir(parents=True, exist_ok=True)
    return d


def season(d: datetime) -> str:
    m = d.month
    return "spring" if 3 <= m <= 5 else "summer" if 6 <= m <= 8 else "autumn" if 9 <= m <= 11 else "winter"


def starts():
    return (settings.minute("朝昼夜の時間", "朝", 5 * 60), settings.minute("朝昼夜の時間", "昼", 11 * 60),
            settings.minute("朝昼夜の時間", "夜", 17 * 60))


def time_of_day(d: datetime) -> str:
    now = d.hour * 60 + d.minute
    m, dy, n = starts()
    if m <= dy <= n:
        return "morning" if m <= now < dy else "day" if dy <= now < n else "night"
    return "morning" if 5 <= d.hour <= 10 else "day" if 11 <= d.hour <= 16 else "night"


def is_bedtime(d: datetime) -> bool:
    now = d.hour * 60 + d.minute
    bed = settings.minute("朝昼夜の時間", "おやすみ", 23 * 60)
    morning = starts()[0]
    return (now >= bed or now < morning) if bed > morning else (bed <= now < morning)


def is_work_time(d: datetime) -> bool:
    rules = settings.lines("仕事の時間") or ["平日 09:00-18:00"]
    days_map = {"平日": {0, 1, 2, 3, 4}, "毎日": set(range(7)), "土日": {5, 6}, "休日": {5, 6}}
    names = "月火水木金土日"
    now = d.hour * 60 + d.minute
    for l in rules:
        p = l.replace("　", " ").split()
        if len(p) < 2:
            continue
        days = days_map.get(p[0]) or {names.index(c) for c in p[0] if c in names}
        r = re.split(r"[-〜~]", p[1])
        from .settings import to_minute
        if len(r) == 2 and d.weekday() in days:
            a, b = to_minute(r[0]), to_minute(r[1])
            if a is not None and b is not None and a <= now < b:
                return True
    return False


def variants(name: str) -> list[Path]:
    pat = re.compile(r"^" + re.escape(name) + r"(?:[-_ ]?\d+)?\.png$", re.I)
    out = []
    for d in (CHAR / "seasons", user_dir()):
        if d.exists():
            out += [f for f in d.iterdir() if pat.match(f.name)]
    return sorted(out)


_picked: dict[str, Path] = {}
_work = {"pick": random.choice(["work", "study"]), "until": 0.0}


def pick(name: str, candidates: list[Path]):
    key = name + "|" + datetime.now().strftime("%Y-%m-%d")
    if key in _picked and _picked[key] in candidates:
        return _picked[key]
    if not candidates:
        return None
    _picked[key] = random.choice(candidates)
    return _picked[key]


def current(sleeping: bool = False, teaching: bool = False) -> Path:
    d = datetime.now()
    if teaching:
        return CHAR / "modes" / "teacher.png"
    if sleeping or is_bedtime(d):
        return CHAR / "modes" / "sleepy.png"
    override = state.get("outfit")
    default_mode = (settings.lines("ミクの服")[:1] == ["いつもの"] and not override) or override == "default"
    if not override and is_work_time(d):
        if time.time() >= _work["until"]:
            _work["pick"] = random.choice(["work", "study"])
            _work["until"] = time.time() + random.uniform(20, 40) * 60
        return CHAR / "modes" / f"{_work['pick']}.png"
    t = time_of_day(d)
    if default_mode:
        return pick("default-" + t, variants("default-" + t) + [CHAR / "miku.png"]) or CHAR / "miku.png"
    name = override or f"{season(d)}-{t}"
    return pick(name, variants(name)) or pick("default-" + t, variants("default-" + t) + [CHAR / "miku.png"]) or CHAR / "miku.png"


def handle(text: str):
    """「冬の夜の服にして」「季節の服に戻して」「いつもの服にして」→ 返事（服の話でなければ None）"""
    if not re.search(r"服|衣装|着替え|コーデ", text):
        return None
    if re.search(r"戻して|もどして|自動|季節に合わせ", text):
        state.set("outfit", None)
        d = datetime.now()
        return f"👗 季節と時間に合わせた服に戻したよ（今は{SEASONS[season(d)]}・{TIMES[time_of_day(d)]}の服）"
    if "いつもの" in text or "元の" in text:
        state.set("outfit", "default")
        return "👗 いつもの服にしたよ（「季節の服に戻して」で着替えるよ）"
    s = next((k for k, v in SEASONS.items() if v in text), None)
    if not s:
        return None
    t = next((k for k, v in TIMES.items() if v in text), time_of_day(datetime.now()))
    state.set("outfit", f"{s}-{t}")
    return f"👗 {SEASONS[s]}・{TIMES[t]}の服に着替えたよ！（「季節の服に戻して」で元に戻るよ）"
