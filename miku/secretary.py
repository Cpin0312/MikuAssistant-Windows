"""秘書の仕事：ToDo・アラーム・Gmail の未読・PC の状態・朝のまとめ・夕方の報告・飛書へのお知らせ（送るだけ）"""
import email.header
import imaplib
import json
import re
import socket
from datetime import datetime, timedelta

import keyring
import psutil
import requests

from . import info
from .settings import data_dir, settings

# ---------- ToDo（このパソコンの中：todo.json） ----------

_todo = data_dir() / "todo.json"


def todos() -> list[dict]:
    try:
        return json.loads(_todo.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_todos(t):
    _todo.write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")


def todo_add(title: str, due: str | None = None):
    t = todos()
    t.append({"title": title, "due": due, "done": None, "created": datetime.now().isoformat(timespec="minutes")})
    _save_todos(t)


def todo_done(word: str) -> list[str]:
    t, hit = todos(), []
    for x in t:
        if not x["done"] and (word in x["title"] or x["title"] in word):
            x["done"] = datetime.now().isoformat(timespec="minutes")
            hit.append(x["title"])
    _save_todos(t)
    return hit


def todo_text() -> str:
    open_ = [x for x in todos() if not x["done"]]
    if not open_:
        return "ToDo は空っぽだよ。えらい！"
    return "\n".join([f"✅ ToDo（{len(open_)}件）"] + [f"・{x['title']}" + (f"（{x['due']}まで）" if x["due"] else "") for x in open_[:10]])


# ---------- アラーム（alarms.json） ----------

_alarms = data_dir() / "alarms.json"


def alarms() -> list[dict]:
    try:
        return json.loads(_alarms.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_alarms(a):
    _alarms.write_text(json.dumps(a, ensure_ascii=False, indent=1), encoding="utf-8")


def parse_time(text: str, now: datetime | None = None):
    """「10分後」「1時間後」「15時」「明日7時半」「午後3時」→ 日時"""
    now = now or datetime.now()
    t = text.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    m = re.search(r"(?:(\d+)\s*時間)?\s*(?:(\d+)\s*分)?\s*(?:(\d+)\s*秒)?後", t)
    if m and any(m.groups()):
        h, mi, s = (int(x) if x else 0 for x in m.groups())
        return now + timedelta(hours=h, minutes=mi, seconds=s)
    m = re.search(r"(午前|午後|朝|夜|夕方)?\s*(\d{1,2})\s*(?:時|:)\s*(\d{1,2}|半)?", t)
    if not m:
        return None
    h = int(m.group(2))
    mi = 30 if m.group(3) == "半" else int(m.group(3) or 0)
    if m.group(1) in ("午後", "夜", "夕方") and h < 12:
        h += 12
    day = now.date() + timedelta(days=2 if "明後日" in t else 1 if "明日" in t else 0)
    when = datetime(day.year, day.month, day.day, h % 24, mi)
    if when <= now and "明日" not in t and "明後日" not in t:
        when += timedelta(hours=12) if (h < 12 and not m.group(1)) else timedelta(days=1)
    return when


def alarm_add(when: datetime, label: str):
    a = alarms()
    a.append({"at": when.isoformat(timespec="seconds"), "label": label})
    a.sort(key=lambda x: x["at"])
    _save_alarms(a)


def due_alarms() -> list[dict]:
    now = datetime.now()
    a = alarms()
    due = [x for x in a if datetime.fromisoformat(x["at"]) <= now]
    if due:
        _save_alarms([x for x in a if x not in due])
    return due


def alarms_text() -> str:
    a = alarms()
    if not a:
        return "アラームは入っていないよ"
    return "\n".join([f"⏰ アラーム（{len(a)}件）"] + [f"・{datetime.fromisoformat(x['at']):%m/%d %H:%M} {x['label']}" for x in a[:8]])


# ---------- Gmail の未読（IMAP。アプリパスワードは資格情報マネージャーに） ----------

def gmail_account():
    return settings.value("Gmail", "アドレス")


def gmail_password(account):
    try:
        return keyring.get_password("MikuAssistant.Gmail", account)
    except Exception:
        return None


def _dec(s: str) -> str:
    out = ""
    for part, enc in email.header.decode_header(s or ""):
        out += part.decode(enc or "utf-8", "replace") if isinstance(part, bytes) else part
    return out


def gmail_unread(limit: int = 3):
    acc = gmail_account()
    pw = gmail_password(acc) if acc else None
    if not acc or not pw:
        return None
    m = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=30)
    try:
        m.login(acc, pw)
        m.select("INBOX", readonly=True)
        _, data = m.uid("search", None, "UNSEEN")
        uids = data[0].split()
        latest = []
        for uid in reversed(uids[-limit:]):
            _, d = m.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
            raw = d[0][1].decode("utf-8", "replace") if d and d[0] else ""
            msg = email.message_from_string(raw)
            frm = re.sub(r"\s*<.*?>", "", _dec(msg.get("From", ""))).strip('" ')
            latest.append((frm, _dec(msg.get("Subject", "（件名なし）"))))
        return len(uids), latest
    finally:
        try:
            m.logout()
        except Exception:
            pass


def gmail_text() -> str:
    r = gmail_unread()
    if r is None:
        return "Gmail がまだ登録されていないよ（右クリック →「設定」→「Gmail を登録」）"
    n, latest = r
    if n == 0:
        return "✉️ 未読メールはないよ♪"
    return "\n".join([f"📩 Gmail に未読メールが{n}件あるよ！"] + [f"・{f}：{s[:24]}" for f, s in latest])


# ---------- PC の状態（見るだけ） ----------

def pc_text() -> str:
    out = ["🖥 PC の状態"]
    b = psutil.sensors_battery()
    if b:
        out.append(f"🔋 電池 {int(b.percent)}%" + ("（電源につないでいる）" if b.power_plugged else ""))
    du = psutil.disk_usage("C:\\" if psutil.WINDOWS else "/")
    out.append(f"💽 ディスクの空き {du.free // (1024 ** 3)}GB")
    out.append(f"🧠 CPU {psutil.cpu_percent(interval=0.5):.0f}%・メモリ {psutil.virtual_memory().percent:.0f}%")
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        out.append(f"🌐 この PC の IP：{s.getsockname()[0]}")
        s.close()
    except OSError:
        out.append("🌐 インターネット：つながっていない")
    boot = datetime.fromtimestamp(psutil.boot_time())
    d = datetime.now() - boot
    out.append(f"⏱ 起動してから {d.days}日{d.seconds // 3600}時間")
    return "\n".join(out)


# ---------- 朝のまとめ・夕方の報告 ----------

def _safe(f, *a):
    try:
        return f(*a)
    except Exception as e:
        return f"（読めなかった：{e}）"


def briefing_text(h: int) -> str:
    from .settings import lines
    out = [f"🌅 {lines.time_word(h)}！今日のまとめだよ", _safe(info.weather_text, 0), todo_text(), _safe(gmail_text), _safe(info.trains_text)]
    try:
        w = info.news(info.WORLD, 1)
        n = info.news(info.NATION, 1)
        out += [f"📰 国際：{w[0]['title']}" if w else "", f"📰 国内：{n[0]['title']}" if n else ""]
    except Exception:
        pass
    return "\n".join(x for x in out if x)


def evening_text() -> str:
    today = datetime.now().date().isoformat()
    done = [x["title"] for x in todos() if x["done"] and x["done"].startswith(today)]
    out = ["🌇 今日もおつかれさま！夕方の報告だよ",
           f"✅ 今日終わった ToDo：{len(done)}件" + "".join(f"\n・{d}" for d in done[:5]), todo_text(), _safe(info.weather_text, 1), _safe(gmail_text)]
    return "\n".join(out)


# ---------- 飛書（Feishu）へのお知らせ：送るだけ（飛書から PC は操作しない） ----------

def feishu_send(text: str) -> bool:
    url = settings.value("飛書", "Webhook")
    if not url or not url.startswith("https://"):
        return False
    try:
        r = requests.post(url, json={"msg_type": "text", "content": {"text": "🎵 " + text}}, timeout=15)
        return r.ok
    except requests.RequestException:
        return False
