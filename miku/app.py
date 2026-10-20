"""ミクの画面（Windows）：いつも前にいる透明な窓に、ミクと吹き出し。クリックで話しかける・右クリックでメニュー

遠隔操作（スマホや他のアプリからの指示で PC を動かすこと）は入れていない。
"""
import math
import sys
import threading
import time
import traceback
import webbrowser
from datetime import datetime

from PySide6.QtCore import QObject, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox, QSystemTrayIcon,
                               QVBoxLayout, QWidget)

from . import ai, brain, commands, outfit, secretary, voice
from .settings import data_dir, lines, resource_dir, settings, state

W, H = 300, 620          # 窓の大きさ
CHAR_H = 230             # ミクの高さ


class Bridge(QObject):
    """別のスレッドから画面へ（Qt のシグナルはスレッドをまたいでも安全）"""
    reply = Signal(str, float, bool)     # 文・表示秒・先生モード
    status = Signal(str)


class MikuWindow(QWidget):
    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(W, H)
        self.bridge = Bridge()
        self.bridge.reply.connect(self.show_bubble)
        self.bridge.status.connect(lambda s: self.show_bubble(s, 60, False))
        self.busy = False
        self.last_activity = time.time()
        self.teach_until = 0.0
        self.sleeping = False
        self.t0 = time.time()
        self.drag = None
        self.pix_path = None
        self.pix = QPixmap()

        # 吹き出し
        self.bubble = QLabel(self)
        self.bubble.setWordWrap(True)
        self.bubble.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.bubble.setStyleSheet("QLabel{background:rgba(255,255,255,240);color:#262626;border:2px solid #39c5bb;"
                                  "border-radius:14px;padding:10px 12px;font-size:13px;}")
        self.bubble.setFont(QFont("Yu Gothic UI", 10))
        self.bubble.setMaximumWidth(W - 20)
        self.bubble.hide()
        self.bubble_timer = QTimer(self, singleShot=True, timeout=self.hide_bubble)

        # 入力欄（クリックで出る）
        self.input = QLineEdit(self)
        self.input.setPlaceholderText("ミクに話しかけてね（Enter）")
        self.input.setStyleSheet("QLineEdit{background:white;border:2px solid #39c5bb;border-radius:12px;padding:6px 10px;font-size:13px;}")
        self.input.setGeometry(10, H - CHAR_H - 48, W - 20, 36)
        self.input.returnPressed.connect(self.send_input)
        self.input.hide()

        # 動き（1秒に15回。寝ているときは4回）
        self.anim = QTimer(self, timeout=self.update)
        self.anim.start(66)
        # 決まった時刻の仕事（20秒ごと）
        QTimer(self, timeout=self.tick, interval=20000).start()
        self.update_outfit()

        g = QApplication.primaryScreen().availableGeometry()
        self.move(g.right() - W - 20, g.bottom() - H)
        self.setup_tray()
        QTimer.singleShot(800, lambda: self.show_bubble(lines.startup(datetime.now().hour), 8))
        QTimer.singleShot(60000, self.tick)

    # ---------- 絵 ----------

    def update_outfit(self):
        teaching = time.time() < self.teach_until
        p = outfit.current(sleeping=self.sleeping, teaching=teaching)
        if p != self.pix_path:
            self.pix_path = p
            self.pix = QPixmap(str(p)).scaledToHeight(CHAR_H * 2, Qt.SmoothTransformation)
            self.pix.setDevicePixelRatio(2)

    def paintEvent(self, _):
        if self.pix.isNull():
            return
        t = time.time() - self.t0
        bob = math.sin(t * (1.2 if self.sleeping else 2.2)) * (1.5 if self.sleeping else 3)
        breath = 1 + math.sin(t * 2.2) * 0.012
        pw, ph = self.pix.width() / 2, self.pix.height() / 2
        w, h = pw, ph * breath
        x = (W - w) / 2
        y = H - h - 6 + bob
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if self.sleeping:
            p.setOpacity(0.9)
        p.drawPixmap(QRect(int(x), int(y), int(w), int(h)), self.pix)
        if self.sleeping:
            p.setPen(QColor(100, 130, 230))
            for i in range(3):
                ph_ = (t * 0.5 + i / 3) % 1
                p.setOpacity(1 - ph_)
                f = QFont("Arial", int(11 + ph_ * 9), QFont.Black)
                p.setFont(f)
                p.drawText(QPoint(int(W - 90 + ph_ * 22), int(H - CHAR_H + 20 - ph_ * 40)), "Z")
        p.end()

    # ---------- 吹き出し ----------

    def show_bubble(self, text: str, seconds: float = 10, teach: bool = False):
        self.wake()
        if teach:
            self.teach_until = time.time() + seconds
            self.update_outfit()
        self.bubble.setText(text)
        self.bubble.adjustSize()
        h = min(self.bubble.sizeHint().height(), H - CHAR_H - 60)
        self.bubble.setGeometry(10, H - CHAR_H - 20 - h, W - 20, h)
        self.bubble.show()
        self.bubble_timer.start(int(seconds * 1000))
        if seconds < 50:
            voice.say(text)

    def hide_bubble(self):
        self.bubble.hide()
        voice.stop()
        if self.teach_until:
            self.teach_until = 0
            self.update_outfit()

    # ---------- 話しかける ----------

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.drag = (e.globalPosition().toPoint(), self.pos(), time.time())

    def mouseMoveEvent(self, e):
        if self.drag:
            self.move(self.drag[1] + e.globalPosition().toPoint() - self.drag[0])

    def mouseReleaseEvent(self, e):
        if not self.drag:
            return
        moved = (e.globalPosition().toPoint() - self.drag[0]).manhattanLength()
        self.drag = None
        if moved < 5 and e.position().y() > H - CHAR_H - 10:
            if self.bubble.isVisible():
                self.hide_bubble()
            self.input.show()
            self.input.setFocus()
            self.activateWindow()

    def send_input(self):
        text = self.input.text().strip()
        self.input.clear()
        self.input.hide()
        if text:
            self.run(text)

    def run(self, text: str):
        if self.busy:
            self.show_bubble("ちょっと待ってね、今ほかのことをしてるよ", 4)
            return
        self.busy = True
        self.last_activity = time.time()

        def work():
            try:
                r = commands.handle(text, progress=self.bridge.status.emit)
                self.bridge.reply.emit(r.text, min(45, 8 + len(r.text) * 0.12), r.teach)
            except Exception as e:
                traceback.print_exc()
                self.bridge.reply.emit(str(e) or "うまくいかなかった…", 10, False)
            finally:
                self.busy = False
        threading.Thread(target=work, daemon=True).start()

    def background(self, fn, *, show=True, feishu=False):
        """裏で動かして、結果を吹き出し（と飛書）に"""
        def work():
            try:
                text = fn()
                if text:
                    if show:
                        self.bridge.reply.emit(text, 30, False)
                    if feishu:
                        secretary.feishu_send(text)
            except Exception:
                traceback.print_exc()
        threading.Thread(target=work, daemon=True).start()

    # ---------- 眠る・起きる ----------

    def wake(self):
        self.last_activity = time.time()
        if self.sleeping:
            self.sleeping = False
            self.anim.start(66)
            self.update_outfit()

    def enterEvent(self, _):
        if self.sleeping:
            self.wake()
            self.show_bubble(lines.pick("おきた", "はっ…ちょっと寝ちゃってた！"), 4)

    # ---------- 決まった時刻の仕事 ----------

    def tick(self):
        now = datetime.now()
        hm = now.hour * 60 + now.minute
        stamp = now.strftime("%Y-%m-%d")
        if not self.sleeping and time.time() - self.last_activity > 15 * 60 and not self.bubble.isVisible():
            self.sleeping = True
            self.anim.start(250)
        self.update_outfit()
        for a in secretary.due_alarms():
            self.show_bubble(f"⏰ 時間だよ！{a['label']}", 30)
            secretary.feishu_send(f"⏰ {a['label']}")

        def once(key: str, at: int, days: str | None = None) -> bool:
            if hm != at or state.get(key) == stamp:
                return False
            if days == "平日" and now.weekday() >= 5:
                return False
            state.set(key, stamp)
            return True
        if once("briefing", settings.minute("朝のまとめ", "時刻", 8 * 60), settings.value("朝のまとめ", "曜日")):
            self.background(lambda: secretary.briefing_text(now.hour), feishu=True)
        if once("evening", settings.minute("夕方の報告", "時刻", 18 * 60), settings.value("夕方の報告", "曜日")):
            self.background(secretary.evening_text, feishu=True)
        if ai.has_key() and once("reflect", 23 * 60 + 30):
            self.background(lambda: ("📔 今日のふりかえり\n" + s) if (s := brain.reflect()) else None, show=False, feishu=True)
        # 自習（設定 [AI]「自習 60」分ごと。0 でしない。AI の回数が少ないときはお休み）
        every = settings.int("AI", "自習", 60)
        if ai.has_key() and every > 0 and time.time() - state.get("last_study", 0) > every * 60 and ai.light_quota_left():
            state.set("last_study", time.time())
            self.background(lambda: f"📚 「{t}」を勉強したよ" if (t := brain.study()) else None)

    # ---------- メニュー ----------

    def contextMenuEvent(self, e):
        self.menu().exec(e.globalPos())

    def menu(self) -> QMenu:
        m = QMenu()
        ask = lambda text: (lambda: self.run(text))
        info = m.addMenu("情報")
        for label, text in [("🌅 朝のまとめ", "朝のまとめ"), ("☀️ 今日の天気", "今日の天気"), ("☀️ 明日の天気", "明日の天気"),
                            ("📰 ニュース", "ニュース"), ("🚃 電車", "電車の運行情報"), ("🖥 PC の状態", "PCの状態"),
                            ("✉️ Gmail の未読", "メールをチェックして"), ("🌇 今日の報告", "今日の報告")]:
            info.addAction(label, ask(text))
        sec = m.addMenu("秘書")
        sec.addAction("✅ ToDo の一覧", ask("ToDoを教えて"))
        sec.addAction("⏰ アラームの一覧", ask("アラームの一覧を見せて"))
        brainm = m.addMenu("頭脳")
        for label, text in [("📏 教わったルール", "ルールを教えて"), ("🧠 覚えていること", "何を覚えてる？"), ("📚 勉強したこと", "何を勉強した？"),
                            ("💡 アイデア帳", "アイデア帳を見せて"), ("📔 ふりかえり", "ふりかえりをして")]:
            brainm.addAction(label, ask(text))
        brainm.addAction("📂 ミクのノートを開く", lambda: webbrowser.open(brain.notebook_dir().as_uri()))
        st = m.addMenu("設定")
        st.addAction("📝 設定ファイルを開く", lambda: webbrowser.open(settings.path.as_uri()))
        st.addAction("🔑 AI の API キー…", self.set_ai_key)
        st.addAction("✉️ Gmail を登録…", self.set_gmail)
        st.addAction("👗 季節の服に戻す", ask("季節の服に戻して"))
        v = QAction("🔊 声を出す", st, checkable=True, checked=voice.enabled())
        v.toggled.connect(voice.set_enabled)
        st.addAction(v)
        m.addSeparator()
        m.addAction("💬 話しかける", lambda: (self.input.show(), self.input.setFocus(), self.activateWindow()))
        m.addAction("🎵 何ができる？", ask("何ができる？"))
        m.addAction("隠す", self.hide)
        m.addAction("終了", QApplication.quit)
        return m

    def set_ai_key(self):
        k, ok = QInputDialog.getText(self, "AI（Gemini）の API キー",
                                     "Google AI Studio（aistudio.google.com/apikey）で作ったキーを貼り付けてね", QLineEdit.Password)
        if ok and k.strip():
            ai.set_api_key(k)
            self.show_bubble("AI の API キーを保存したよ！", 5)

    def set_gmail(self):
        acc, ok = QInputDialog.getText(self, "Gmail を登録", "メールアドレス")
        if not ok or not acc.strip():
            return
        pw, ok = QInputDialog.getText(self, "Gmail を登録",
                                      "アプリパスワード（16文字。Google アカウント → セキュリティ → アプリパスワード で作る）", QLineEdit.Password)
        if ok and pw.strip():
            import keyring
            keyring.set_password("MikuAssistant.Gmail", acc.strip(), pw.replace(" ", ""))
            settings.set_value("Gmail", "アドレス", acc.strip())
            self.show_bubble("Gmail を登録したよ！", 5)

    def setup_tray(self):
        icon = QIcon(str(resource_dir() / "icon.png"))
        self.setWindowIcon(icon)
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip("ミクちゃん")
        self.tray_menu = QMenu()
        self.tray_menu.addAction("ミクを出す", lambda: (self.show(), self.raise_()))
        self.tray_menu.addAction("終了", QApplication.quit)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(lambda r: (self.show(), self.raise_()) if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("MikuAssistant")
    w = MikuWindow()
    w.show()
    sys.exit(app.exec())
