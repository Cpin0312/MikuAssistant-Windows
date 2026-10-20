"""AI（Google Gemini）。API キーは Windows の資格情報マネージャーに保存する（keyring）"""
import json
import time
from datetime import datetime, timezone, timedelta

import keyring
import requests

SERVICE = "MikuAssistant"
KEY_NAME = "gemini-api-key"
MODELS = ["gemini-flash-latest", "gemini-2.5-flash", "gemini-flash-lite-latest", "gemini-2.5-flash-lite"]
LIGHT = ["gemini-flash-lite-latest", "gemini-2.5-flash-lite", "gemini-flash-latest"]

PERSONA = """あなたは初音ミクのような明るくかわいいデスクトップアシスタント「ミク」です。
日本語で、親しみやすい話し言葉で答えてください。
答えは吹き出しに表示するので、2〜4文の短さにしてください。マークダウンの記号は使わないでください。"""


class QuotaError(Exception):
    pass


def api_key():
    try:
        return keyring.get_password(SERVICE, KEY_NAME)
    except Exception:
        return None


def set_api_key(k: str):
    keyring.set_password(SERVICE, KEY_NAME, k.strip())


def has_key() -> bool:
    return bool(api_key())


# 今日の上限に当たったモデル（太平洋時間の0時に戻る）
_resting: dict[str, float] = {}


def _next_reset() -> float:
    pt = timezone(timedelta(hours=-8))
    now = datetime.now(pt)
    return (now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).timestamp()


def light_quota_left() -> bool:
    """軽いモデルが今日の上限に当たっていなければ True（自習などの裏の作業に使う）"""
    now = time.time()
    return any(_resting.get(m, 0) < now for m in LIGHT[:2])


def generate(body: dict, light: bool = False) -> list[dict]:
    key = api_key()
    if not key:
        raise RuntimeError("AI の API キーがまだ設定されていないよ。右クリック →「設定」→「AI の API キー」から入れてね")
    now = time.time()
    order = [m for m in (LIGHT if light else MODELS) if _resting.get(m, 0) < now] or (LIGHT if light else MODELS)[:1]
    quota = busy = False
    last = None
    for i, model in enumerate(order[:3]):
        if i and busy:
            time.sleep(1.5)
        try:
            r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                              headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                              data=json.dumps(body), timeout=40)
        except requests.RequestException as e:
            last = e
            continue
        if r.status_code in (404, 429, 500, 503):
            busy = r.status_code != 404
            msg = r.text
            if r.status_code == 429:
                if "PerDay" in msg or "quota" in msg:
                    quota = True
                    _resting[model] = _next_reset() if "PerDay" in msg else now + 60
                else:
                    _resting[model] = now + 60
            if r.status_code == 404:
                _resting[model] = now + 86400
            continue
        if r.status_code != 200:
            raise RuntimeError(f"AI に聞けなかった…（{r.status_code}）")
        cands = r.json().get("candidates") or [{}]
        return (cands[0].get("content") or {}).get("parts") or []
    if quota:
        raise QuotaError("今日の AI（Gemini）の無料枠を使い切ったみたい…。しばらくするとまた使えるよ")
    raise RuntimeError("AI が混み合っているみたい。少しあとでもう一度話しかけてね" if busy else f"AI につながらなかった…（{last}）")


def text_of(parts) -> str:
    return "".join(p.get("text", "") for p in parts).replace("**", "").replace("*", "").strip()


# 最近の会話（30分話さなければ忘れる）
_history: list[tuple[str, str]] = []
_last_talk = 0.0


def recent_contents():
    global _history
    if time.time() - _last_talk > 1800:
        _history = []
    return [{"role": r, "parts": [{"text": t}]} for r, t in _history[-10:]]


def remember_talk(user: str, model: str):
    global _last_talk
    _history.extend([("user", user), ("model", model)])
    del _history[:-20]
    _last_talk = time.time()


def ask(question: str, system: str = PERSONA, remember: bool = True, light: bool = False, search: bool = False) -> str:
    contents = (recent_contents() if remember else []) + [{"role": "user", "parts": [{"text": question}]}]
    body = {"system_instruction": {"parts": [{"text": system}]}, "contents": contents,
            "generationConfig": {"maxOutputTokens": 1024, "temperature": 0.7}}
    if search:
        body["tools"] = [{"google_search": {}}]
    out = text_of(generate(body, light=light))
    if not out:
        raise RuntimeError("AI から答えが返ってこなかった…")
    if remember:
        remember_talk(question, out)
    return out


def pick_json(prompt: str, system: str = PERSONA) -> dict:
    body = {"system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.5, "maxOutputTokens": 1024, "responseMimeType": "application/json"}}
    return json.loads(text_of(generate(body, light=True)) or "{}")
