"""話しかけた言葉（入力欄に書いた文）を読んで、ミクの機能を選ぶ。決まった言い方でなければ AI と会話

ここは画面の外（別のスレッド）で動く。返事の文を返すだけで、画面は app.py が描く。
"""
import re
from datetime import datetime

from . import ai, brain, info, outfit, secretary

ABILITIES = {
    "情報": ["天気（今日・明日）", "ニュース", "電車の運行情報", "イベント探し（いこうよ）", "ネットで調べて答える"],
    "PC（見るだけ）": ["電池・ディスク・CPU・メモリ・IP・起動時間（PC の状態は？）"],
    "秘書": ["朝のまとめ・夕方の報告（決まった時刻にも）", "ToDo（追加・一覧・完了）", "アラーム（10分後に〜、15時に〜）", "Gmail の未読"],
    "頭脳": ["覚えて・忘れて・何を覚えてる？", "教わったルール（次からは〜して）", "ふりかえり・日記", "何を勉強した？・今すぐ勉強して・アイデア帳"],
    "ミク自身": ["服の着替え（冬の夜の服にして・季節の服に戻して・いつもの服にして）", "何ができる？"],
}


def abilities_text() -> str:
    return "\n".join(f"【{k}】" + "／".join(v) for k, v in ABILITIES.items())


class Reply:
    def __init__(self, text: str, teach: bool = False, interim: str | None = None):
        self.text, self.teach, self.interim = text, teach, interim


def has(text: str, pattern: str) -> bool:
    return re.search(pattern, text, re.I) is not None


def handle(text: str, progress=lambda s: None) -> Reply:
    t = text.strip()
    brain.log_talk("ユーザー", t)
    brain.learn_from_correction(t)

    # 服
    r = outfit.handle(t)
    if r:
        return Reply(r)
    # 何ができる
    if has(t, r"何ができる|なにができる|できること|使い方を教えて|機能一覧"):
        return Reply("🎵 ミクができること\n" + "\n".join(f"【{k}】\n" + "\n".join("・" + x for x in v) for k, v in ABILITIES.items()))
    # 頭脳
    if has(t, r"(何|なに)を(勉強|学習|調べ)|ミクの知識"):
        tp = brain.topics()[:8]
        return Reply("まだ勉強していないよ。1時間ごとに自分で勉強するね" if not tp else "📚 最近勉強したこと\n" + "\n".join("・" + x for x in tp))
    if has(t, r"(今すぐ|いま)?(勉強|自習)して"):
        progress("📚 勉強してくるね…")
        topic = brain.study()
        return Reply(f"📚 「{topic}」を勉強したよ！" if topic else "うまく勉強できなかった…")
    if has(t, r"アイデア帳"):
        f = brain.ideas_file()
        ls = [l[2:] for l in (f.read_text(encoding="utf-8") if f.exists() else "").split("\n") if l.startswith("- ")][-6:]
        return Reply("アイデア帳はまだ空っぽだよ" if not ls else "💡 アイデア帳（最近のもの）\n" + "\n".join(ls))
    if has(t, r"ふりかえ|振り返"):
        progress("📔 今日の会話をふりかえってくるね…")
        s = brain.reflect()
        return Reply("📔 今日のふりかえり\n" + s if s else "ふりかえるほどの会話がまだないみたい")
    if has(t, r"日記") and has(t, r"見せて|読んで|教えて"):
        d = brain.diary_text()
        return Reply("📖 ミクの日記\n" + d[:800] if d else "日記はまだないよ")
    if has(t, r"ルール") and has(t, r"教えて|見せて|一覧"):
        r_ = brain.items(brain.RULES)
        return Reply("教わったルールはまだないよ" if not r_ else f"📏 教わったルール（{len(r_)}件）\n" + "\n".join("・" + x for x in r_[-12:]))
    m = re.search(r"(.+?)(?:って|と|を)?\s*覚えて", t)
    if m and not has(t, r"何を覚え"):
        n = brain.remember([m.group(1)])
        return Reply("🧠 覚えたよ！" if n else "それはもう覚えているよ")
    m = re.search(r"(.+?)(?:って|と|を|の(?:こと)?)?\s*忘れて", t)
    if m:
        n = brain.forget(m.group(1))
        return Reply(f"🧠 {n}件忘れたよ" if n else "それは覚えていなかったみたい")
    if has(t, r"何を覚えて|なにを覚えて"):
        f = brain.items(brain.FACTS)
        return Reply("まだ何も覚えていないよ" if not f else f"🧠 覚えていること（{len(f)}件）\n" + "\n".join("・" + x for x in f[-10:]))

    # 秘書
    if has(t, r"ToDo|TODO|todo|タスク|やること"):
        m = re.search(r"(.+?)\s*(?:を|も)?\s*(?:ToDo|TODO|todo|タスク|やること)(?:リスト)?\s*(?:に|へ)\s*(?:追加|入れ|登録)", t)
        if m:
            secretary.todo_add(m.group(1).strip())
            return Reply(f"✅ ToDo に「{m.group(1).strip()}」を入れたよ")
        return Reply(secretary.todo_text())
    m = re.search(r"(.+?)\s*(?:を|は|が)?\s*(?:完了|終わった|済んだ|できた)", t)
    if m:
        done = secretary.todo_done(m.group(1).strip())
        if done:
            return Reply("🎉 おつかれさま！「" + "」「".join(done) + "」を完了にしたよ")
    if has(t, r"アラーム|タイマー|起こして|知らせて|教えて") and secretary.parse_time(t):
        if has(t, r"一覧|見せて"):
            return Reply(secretary.alarms_text())
        when = secretary.parse_time(t)
        label = re.sub(r"(\d+\s*(時間|分|秒)\s*)+後|(明日|明後日|今日)?の?(午前|午後|朝|夜|夕方)?\s*\d{1,2}\s*(時|:)\s*(\d{1,2}分?|半)?|に|で|アラーム|タイマー|をセット|して|起こして|知らせて|教えて", "", t).strip()
        secretary.alarm_add(when, label or "アラーム")
        return Reply(f"⏰ {when:%m/%d %H:%M} にアラームをセットしたよ" + (f"（{label}）" if label else ""))
    if has(t, r"アラーム") and has(t, r"一覧|見せて|ある"):
        return Reply(secretary.alarms_text())
    if has(t, r"朝のまとめ|今日のまとめ"):
        progress("🌅 今日のまとめを集めてるね…")
        return Reply(secretary.briefing_text(datetime.now().hour))
    if has(t, r"夕方の報告|今日の報告"):
        progress("🌇 今日の報告をまとめてるね…")
        return Reply(secretary.evening_text())
    if has(t, r"メール|gmail") and has(t, r"チェック|確認|ある|未読|来て"):
        progress("✉️ Gmail を見てくるね…")
        return Reply(secretary.gmail_text())

    # 情報
    if has(t, r"天気"):
        progress("☀️ tenki.jp で天気を見てくるね…")
        return Reply(info.weather_text(1 if has(t, r"明日|あした") else 0))
    if has(t, r"ニュース"):
        progress("📰 ニュースを集めてくるね…")
        return Reply(info.news_text())
    if has(t, r"電車|運行"):
        progress("🚃 運行情報を見てくるね…")
        return Reply(info.trains_text())
    if has(t, r"イベント|祭り|まつり|フェス|花火|お出かけ|どこ行こう"):
        progress("🔎 いこうよでイベントを探してくるね…")
        return Reply(info.events_text(t))
    if has(t, r"電池|バッテリー|ディスク|CPU|メモリ|IPアドレス|\bIP\b|起動して(から|る)|PCの状態|パソコンの状態"):
        return Reply(secretary.pc_text())

    # AI と会話（最新の情報は Google 検索も使う）
    if not ai.has_key():
        return Reply("おしゃべりするには AI の API キーが必要だよ（右クリック →「設定」→「AI の API キー」）")
    progress("🤔 考え中…")
    system = (ai.PERSONA + "\n最新の情報が必要なときや自信がないときは、Google 検索で調べてから答えてください。"
              + "\n\nミクができること（これ以外の操作はできません）：\n" + abilities_text() + brain.prompt_addition())
    answer = ai.ask(t, system=system, search=True)
    brain.log_talk("ミク", answer)
    alt = brain.think_again(t, answer, abilities_text())
    if alt:
        answer += "\n\n💡 " + alt
    return Reply(answer, teach=True)
