"""Eklenti ile dosya protokolü (docs/protocol.md)."""
import json
import os
import time

import config as C


class BridgeIO:
    def __init__(self, folder: str | None = None):
        self.dir = folder or C.BRIDGE_DIR
        self.state_path = os.path.join(self.dir, "press_state.json")
        self.question_path = os.path.join(self.dir, "press_question.json")
        self.answer_path = os.path.join(self.dir, "press_answer.json")

    def read_state(self) -> dict | None:
        """Okunamazsa (yok/yarım/kilitli) None."""
        for _ in range(3):
            try:
                with open(self.state_path, encoding="utf-8-sig") as f:
                    return json.load(f)
            except FileNotFoundError:
                return None
            except (PermissionError, json.JSONDecodeError, OSError):
                time.sleep(0.05)
        return None

    def _write_atomic(self, path: str, obj: dict):
        os.makedirs(self.dir, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        for _ in range(20):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:      # eklenti o an okuyor
                time.sleep(0.05)
        raise PermissionError(path)

    def write_question(self, question_id: str, text: str):
        self._write_atomic(self.question_path, {"v": 1, "question_id": question_id, "text": text})

    def write_answer(self, question_id: str, category_index: int, option_index: int,
                     display_text: str, click: bool = True):
        self._write_atomic(self.answer_path, {
            "v": 1, "question_id": question_id, "category_index": category_index,
            "option_index": option_index, "display_text": display_text, "click": click})

    def wait_applied(self, question_id: str, action: str, timeout: float = 3.0, final=None) -> dict | None:
        """Eklentinin last_applied ile onayını bekler. final(la) verilirse o koşul sağlanana kadar bekler;
        süre dolarsa görülen son ara sonucu döndürür."""
        end = time.time() + timeout
        seen = None
        while time.time() < end:
            st = self.read_state() or {}
            la = st.get("last_applied") or {}
            if la.get("question_id") == question_id and la.get("action") == action:
                seen = la
                if final is None or final(la):
                    return la
            time.sleep(0.1)
        return seen
