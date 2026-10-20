"""設定ファイル（設定.txt）とセリフ（セリフ.txt）を読む。

設定.txt の場所：Windows は %APPDATA%\\MikuAssistant\\設定.txt（Mac 版と同じ書き方）
保存すると、次に使うときに読み直す（アプリの作り直しは不要）。
"""
import os
import random
import shutil
import sys
from pathlib import Path


def resource_dir() -> Path:
    """アプリに入っている画像・ひな形の場所（exe にまとめたときも動く）"""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "resources"


def data_dir() -> Path:
    """設定・記録を置く場所"""
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path.home() / ".config"
    d = root / "MikuAssistant_Win"
    d.mkdir(parents=True, exist_ok=True)
    return d


def parse_book(text: str) -> dict[str, list[str]]:
    """[グループ] の下に1行ずつ。# で始まる行と空行は飛ばす"""
    groups: dict[str, list[str]] = {}
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].replace("　", " ").strip()
            groups.setdefault(current, [])
            continue
        if current is not None:
            groups[current].append(line)
    return groups


def to_minute(s: str):
    """「08:30」「0830」→ 0時からの分"""
    digits = "".join(c for c in s if c.isdigit() or c == ":")
    parts = digits.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        if len(digits) == 4:
            return int(digits[:2]) * 60 + int(digits[2:])
    except ValueError:
        pass
    return None


class Settings:
    def __init__(self):
        self.path = data_dir() / "設定.txt"
        if not self.path.exists():
            shutil.copy(resource_dir() / "設定.txt", self.path)
        self._mtime = None
        self._groups: dict[str, list[str]] = {}

    @property
    def groups(self):
        m = self.path.stat().st_mtime if self.path.exists() else None
        if m != self._mtime:
            self._groups = parse_book(self.path.read_text(encoding="utf-8")) if m else {}
            self._mtime = m
        return self._groups

    def lines(self, group: str) -> list[str]:
        return self.groups.get(group, [])

    def value(self, group: str, key: str):
        for l in self.lines(group):
            parts = l.replace("　", " ").split()
            if len(parts) >= 2 and parts[0] == key:
                return " ".join(parts[1:])
        return None

    def int(self, group: str, key: str, fallback: int) -> int:
        v = self.value(group, key)
        try:
            return int("".join(c for c in (v or "") if c.isdigit() or c == "-"))
        except ValueError:
            return fallback

    def on(self, group: str, key: str, default: bool) -> bool:
        v = self.value(group, key)
        if v is None:
            return default
        return v.lower() not in ("オフ", "off", "なし", "しない")

    def minute(self, group: str, key: str, default: int) -> int:
        v = self.value(group, key)
        m = to_minute(v) if v else None
        return default if m is None else m

    def set_value(self, group: str, key: str, value: str):
        """「キー 値」の行を書きかえる（なければ見出しの下に足す）"""
        lines = self.path.read_text(encoding="utf-8").split("\n")
        header = f"[{group}]"
        if header in [l.strip() for l in lines]:
            h = [l.strip() for l in lines].index(header)
            i = h + 1
            while i < len(lines) and not lines[i].startswith("["):
                if lines[i].replace("　", " ").split()[:1] == [key]:
                    lines[i] = f"{key} {value}"
                    break
                i += 1
            else:
                lines.insert(h + 1, f"{key} {value}")
        else:
            lines += ["", header, f"{key} {value}"]
        self.path.write_text("\n".join(lines), encoding="utf-8")


class Lines:
    """セリフ.txt（アプリに入っているもの）"""

    def __init__(self):
        p = resource_dir() / "セリフ.txt"
        self.book = parse_book(p.read_text(encoding="utf-8")) if p.exists() else {}

    def pick(self, group: str, fallback: str, **vars) -> str:
        line = random.choice(self.book[group]) if self.book.get(group) else fallback
        for k, v in vars.items():
            line = line.replace("{" + k + "}", str(v))
        return line

    @staticmethod
    def time_word(h: int) -> str:
        return "おはよう" if 5 <= h < 10 else "こんにちは" if 10 <= h < 18 else "こんばんは"

    def greeting(self, h: int) -> str:
        for name, lines in self.book.items():
            if not name.startswith("あいさつ") or not lines:
                continue
            rng = name[len("あいさつ"):].strip().replace("〜", "-").replace("~", "-").split("-")
            try:
                a, b = int(rng[0]), int(rng[1])
            except (ValueError, IndexError):
                continue
            if (a <= h < b) if a <= b else (h >= a or h < b):
                return random.choice(lines)
        return self.time_word(h) + "！"

    def startup(self, h: int) -> str:
        late = not (5 <= h < 23)
        g = "起動・深夜" if late and self.book.get("起動・深夜") else "起動"
        return self.pick(g, "{時間}！ミクだよ♪ 今日もよろしくね！").replace("{時間}", self.time_word(h))

    def idle(self) -> str:
        return self.pick("ひとこと", "なにかあったら話しかけてね♪")


class State:
    """アプリが自分で覚えておく小さな値（state.json）。設定ファイルとは別"""

    def __init__(self):
        self.path = data_dir() / "state.json"

    def _load(self) -> dict:
        import json
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def get(self, key, default=None):
        return self._load().get(key, default)

    def set(self, key, value):
        import json
        d = self._load()
        d[key] = value
        self.path.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


settings = Settings()
state = State()
lines = Lines()
