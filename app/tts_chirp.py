"""Google Cloud TTS (Chirp 3 HD) istemcisi + 0 TL koruması.

ANAHTAR: sadece GOOGLE_TTS_API_KEY ortam değişkeni. Asla dosyaya/log'a yazma, yazdırma (repo public).
Koruma: her istekten ÖNCE logs/tts_usage.json'daki aylık ve günlük karakter sayacı kontrol edilir; sınırı aşacaksa
istek atılmaz (ChirpLimit), çağıran edge-tts'e düşer. Sayaç istek başarılı olunca artar.
"""
import base64
import json
import os
import threading
from datetime import datetime

import requests

import config as C

URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
USAGE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "tts_usage.json")
_lock = threading.Lock()
_http = requests.Session()


class ChirpLimit(Exception):
    """Aylık/günlük sınır doldu: Chirp'e istek atılmadı."""


class ChirpError(Exception):
    pass


def _key() -> str:
    return os.getenv("GOOGLE_TTS_API_KEY", C.GOOGLE_TTS_KEY)


def _load(path=USAGE_FILE) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(d: dict, path=USAGE_FILE):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, path)


def usage(path=USAGE_FILE) -> tuple[int, int]:
    """(bu ay, bugün) kullanılan karakter."""
    d = _load(path)
    now = datetime.now()
    return d.get("months", {}).get(now.strftime("%Y-%m"), 0), d.get("days", {}).get(now.strftime("%Y-%m-%d"), 0)


def reserve(chars: int, path=USAGE_FILE):
    """Sınırı aşmayacaksa karakterleri sayaca yazar; aşacaksa ChirpLimit. (İstekten ÖNCE çağrılır: çökme/yarış
    olsa bile sayaç fazla sayar, eksik saymaz -> sınır asla aşılmaz.)"""
    with _lock:
        d = _load(path)
        now = datetime.now()
        m, day = now.strftime("%Y-%m"), now.strftime("%Y-%m-%d")
        months, days = d.setdefault("months", {}), d.setdefault("days", {})
        if months.get(m, 0) + chars > C.CHIRP_MONTHLY_CHARS:
            raise ChirpLimit(f"aylık Chirp sınırı ({months.get(m, 0)}/{C.CHIRP_MONTHLY_CHARS} karakter)")
        if days.get(day, 0) + chars > C.CHIRP_DAILY_CHARS:
            raise ChirpLimit(f"günlük Chirp sınırı ({days.get(day, 0)}/{C.CHIRP_DAILY_CHARS} karakter)")
        months[m] = months.get(m, 0) + chars
        days[day] = days.get(day, 0) + chars
        for k in sorted(days)[:-40]:        # eski günleri temizle
            days.pop(k, None)
        _save(d, path)


def synth(text: str, path: str, profile: dict, usage_path=USAGE_FILE):
    key = _key()
    if not key:
        raise ChirpError("GOOGLE_TTS_API_KEY yok")
    reserve(len(text), usage_path)
    r = _http.post(URL, headers={"x-goog-api-key": key}, timeout=15, json={
        "input": {"text": text},
        "voice": {"languageCode": "tr-TR", "name": profile["voice"]},
        "audioConfig": {"audioEncoding": "MP3", "speakingRate": profile.get("speaking_rate", 1.0)},
    })
    if r.status_code != 200:
        # hata gövdesinde anahtar olmaz ama yine de kısa tut
        raise ChirpError(f"HTTP {r.status_code}: {r.text[:200]}")
    with open(path, "wb") as f:
        f.write(base64.b64decode(r.json()["audioContent"]))
