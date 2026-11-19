"""Oyun içi gösterge için durum dosyası (app_status.json). Eklenti okur, ekranda gösterir (docs/protocol.md).
start() çağrılmadıysa (testler, sim) hiçbir şey yazmaz."""
import json
import os
import threading
import time

import config as C

_lock = threading.Lock()
_path = None
_phase, _text = "idle", ""


def key() -> str:
    return C.HOTKEY.upper()


def texts() -> dict:
    k = key()
    return {
        "idle": "Hazır, basın ekranı bekleniyor",
        "generating": "Gazeteci soruyu hazırlıyor...",
        "speaking": "Gazeteci soruyor...",
        "waiting_key": f"Cevap için {k}'e bas",
        "recording": f"Kayıt: konuş, bitirince {k}",
        "transcribing": "Cevabın yazıya dökülüyor...",
        "classifying": "Cevabın değerlendiriliyor...",
        "applying": "Cevap oyuna işleniyor...",
        "manual": "Elle cevaplandı",
    }


def set(phase: str, text: str | None = None):
    global _phase, _text
    with _lock:
        _phase, _text = phase, text if text is not None else texts().get(phase, phase)
    _write()


def _write():
    if not _path:
        return
    with _lock:
        body = {"v": 1, "time_ms": int(time.time() * 1000), "phase": _phase, "text": _text, "hotkey": key()}
    tmp = _path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(body, f, ensure_ascii=False)
        for _ in range(10):
            try:
                os.replace(tmp, _path)
                return
            except PermissionError:   # eklenti o an okuyor
                time.sleep(0.03)
    except OSError:
        pass


def start(folder: str):
    """Canlı modda: dosyayı yazmaya başla, her saniye yenile (eklenti 'uygulama çalışıyor' anlasın)."""
    global _path
    os.makedirs(folder, exist_ok=True)
    _path = os.path.join(folder, "app_status.json")
    set("idle")

    def beat():
        while _path:
            time.sleep(1.0)
            _write()
    threading.Thread(target=beat, daemon=True).start()


def stop():
    """Çıkışta: dosyayı sil (gösterge hemen 'uygulama kapalı' desin)."""
    global _path
    p, _path = _path, None
    if p:
        try:
            os.remove(p)
        except OSError:
            pass
