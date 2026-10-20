"""ミクの声（Windows の読み上げ。日本語の声 Haruka などを使う）。設定 [声] の「読み上げ オン／オフ」"""
import queue
import re
import threading

from .settings import settings

_q: "queue.Queue[str | None]" = queue.Queue()
_engine = None
_started = False


def enabled() -> bool:
    return settings.on("声", "読み上げ", True)


def set_enabled(on: bool):
    settings.set_value("声", "読み上げ", "オン" if on else "オフ")
    if not on:
        stop()


def _worker():
    global _engine
    try:
        import pyttsx3
        _engine = pyttsx3.init()
        for v in _engine.getProperty("voices"):
            if "ja" in (str(v.languages) + v.id + v.name).lower() or "japan" in v.name.lower() or "haruka" in v.name.lower():
                _engine.setProperty("voice", v.id)
                break
        _engine.setProperty("rate", 190)
    except Exception:
        _engine = None
    while True:
        text = _q.get()
        if text is None or _engine is None:
            continue
        try:
            _engine.say(text)
            _engine.runAndWait()
        except Exception:
            pass


def say(text: str):
    global _started
    if not enabled():
        return
    if not _started:
        threading.Thread(target=_worker, daemon=True).start()
        _started = True
    # 絵文字・URL・記号は読まない。長い文は最初の3行まで
    t = re.sub(r"https?://\S+", "", "\n".join(text.split("\n")[:3]))
    t = re.sub(r"[^\w\s、。！？!?ー〜・：:（）()％%℃]", "", t)
    if t.strip():
        _q.put(t)


def stop():
    while not _q.empty():
        try:
            _q.get_nowait()
        except queue.Empty:
            break
    try:
        if _engine:
            _engine.stop()
    except Exception:
        pass
