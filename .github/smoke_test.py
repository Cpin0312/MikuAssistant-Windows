"""Windows での起動テスト（GitHub Actions 用）：窓・メニュー・話しかけ・読み上げの準備"""
import os
import sys

sys.path.insert(0, os.getcwd())
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from miku import app, commands, voice

a = QApplication(sys.argv)
w = app.MikuWindow()
w.show()
assert not w.pix.isNull(), "ミクの絵が読めない"
for t in ["何ができる？", "資料作りをToDoに追加", "ToDoを教えて", "資料作り終わった", "10分後にアラーム",
          "PCの状態", "冬の夜の服にして", "季節の服に戻して", "テストって覚えて", "何を覚えてる？", "こんにちは"]:
    print(">>", t, "->", commands.handle(t).text.replace("\n", " / ")[:100])
w.tick()
w.menu()
import pyttsx3
e = pyttsx3.init()
print("voices:", [v.name for v in e.getProperty("voices")])
voice.say("テスト")
QTimer.singleShot(2000, a.quit)
a.exec()
print("APP OK")
