"""Sahte eklenti: gerçek dökümlerden üretilmiş durumları (sample_states/) sırayla press_state.json'a yazar,
press_question/press_answer komutlarını eklenti gibi tüketir. Oyunsuz uçtan uca test için.

    py sim_plugin.py <köprü klasörü> [durum.json ...]
"""
import glob
import json
import os
import sys
import threading
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))


def _now():
    return datetime.now().isoformat(timespec="seconds")


class SimPlugin:
    def __init__(self, folder: str, states: list[dict], linger: float = 0.4):
        self.dir = folder
        self.states = states
        self.linger = linger
        self.seq = 0
        self.last_applied = None
        self.override_qid = None
        self.log: list[dict] = []      # alınan komutlar
        self.done = threading.Event()
        os.makedirs(folder, exist_ok=True)

    def _write(self, st: dict):
        self.seq += 1
        st = dict(st, seq=self.seq, time=_now(), last_applied=self.last_applied,
                  override_question_id=self.override_qid if st.get("active") else None)
        p = os.path.join(self.dir, "press_state.json")
        with open(p + ".tmp", "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
        for _ in range(100):          # app o an okuyorsa Windows yeniden adlandırmaya izin vermez
            try:
                os.replace(p + ".tmp", p)
                return
            except PermissionError:
                time.sleep(0.02)
        raise PermissionError(p)

    def _take(self, name: str):
        p = os.path.join(self.dir, name)
        if not os.path.exists(p):
            return None
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            os.remove(p)
            return d
        except (OSError, json.JSONDecodeError):
            return None

    def run(self, timeout_per_state: float = 120):
        try:
            self._run(timeout_per_state)
        finally:
            self.done.set()           # hata olsa bile bekleyenler takılmasın

    def _run(self, timeout_per_state: float):
        for st in self.states:
            st = dict(st, active=True)
            self.override_qid = None
            self._write(st)
            end = time.time() + timeout_per_state
            answered = False
            while time.time() < end and not answered:
                q = self._take("press_question.json")
                if q:
                    ok = q.get("question_id") == st["question_id"]
                    self.override_qid = q["question_id"] if ok else self.override_qid
                    self.last_applied = {"question_id": q.get("question_id"), "ok": ok, "action": "question",
                                         "detail": "sim: soru değiştirildi" if ok else "sim: bayat", "time": _now()}
                    self.log.append({"type": "question", **q})
                    self._write(st)
                a = self._take("press_answer.json")
                if a:
                    cats = st.get("categories", [])
                    ok = (a.get("question_id") == st["question_id"]
                          and 0 <= a.get("category_index", -1) < len(cats)
                          and 0 <= a.get("option_index", -1) < len(cats[a["category_index"]]["options"]))
                    self.last_applied = {"question_id": a.get("question_id"), "ok": ok, "action": "answer",
                                         "detail": "sim: tıklandı" if ok else "sim: geçersiz", "time": _now()}
                    self.log.append({"type": "answer", **a})
                    self._write(st)
                    answered = True
                time.sleep(0.05)
            time.sleep(self.linger)
        self._write({"v": 1, "active": False})


def load_states(paths: list[str] | None = None) -> list[dict]:
    paths = paths or sorted(glob.glob(os.path.join(HERE, "sample_states", "*.json")))
    out = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if d.get("ready"):
            out.append(d)
    return out


if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "sim_bridge")
    sim = SimPlugin(folder, load_states(sys.argv[2:] or None))
    print(f"Sahte eklenti: {folder}, {len(sim.states)} soru")
    sim.run()
    print(json.dumps(sim.log, ensure_ascii=False, indent=1))
