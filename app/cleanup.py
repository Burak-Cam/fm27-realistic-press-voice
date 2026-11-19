"""Otomatik temizlik: uygulama her açıldığında arka planda çalışır, gereksiz dosyalar birikmesin.

- Maç kayıtları (BepInEx\\fm27pressvoice\\matches): son KEEP_MATCHES kalır.
- Toplantı / uygulama kayıtları (app\\logs): son KEEP_PRESS / KEEP_LIVE kalır.
- Eski UI keşif dökümleri (BepInEx\\fm27pressvoice\\<tarih>_<saat>\\): DUMP_MAX_AGE_H saatten eski klasörler silinir
  (keşif özelliği varsayılan kapalı; açıksa yenileri yine yaşar).
- Ses önbelleği (app\\logs\\tts_cache): artık kullanılmayan sesler (hız/ses değişince eskiyen) silinir.
- Geçici ses dosyaları (%TEMP%\\fm_tts_*, fm_warm_*): 1 günden eskiler silinir (çökme artığı).
"""
import glob
import os
import re
import shutil
import tempfile
import time

import config as C

KEEP_MATCHES = int(os.getenv("FM_KEEP_MATCHES", "30"))
KEEP_PRESS = int(os.getenv("FM_KEEP_PRESS_LOGS", "50"))
KEEP_LIVE = int(os.getenv("FM_KEEP_LIVE_LOGS", "15"))
DUMP_MAX_AGE_H = float(os.getenv("FM_DUMP_MAX_AGE_H", "24"))

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
_DUMP_DIR = re.compile(r"^\d{8}_\d{4,6}")


def _remove(path: str) -> int:
    """Siler, kazanılan baytı döndürür."""
    try:
        if os.path.isdir(path):
            size = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(path) for f in fs)
            shutil.rmtree(path, ignore_errors=True)
            return size
        size = os.path.getsize(path)
        os.remove(path)
        return size
    except OSError:
        return 0


def _keep_newest(pattern: str, keep: int) -> int:
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    return sum(_remove(f) for f in files[keep:])


def _old_dumps() -> int:
    if not os.path.isdir(C.BRIDGE_DIR):
        return 0
    freed, limit = 0, time.time() - DUMP_MAX_AGE_H * 3600
    for name in os.listdir(C.BRIDGE_DIR):
        p = os.path.join(C.BRIDGE_DIR, name)
        if os.path.isdir(p) and _DUMP_DIR.match(name) and os.path.getmtime(p) < limit:
            freed += _remove(p)
    return freed


def _stale_tts_cache() -> int:
    """Önbellekte sadece şu anki ayarlarla (hız, açık sesler) kullanılacak sabit cümleler kalsın."""
    import closing
    import voice
    import voices
    if not os.path.isdir(voice.CACHE_DIR):
        return 0
    wanted = set()
    profiles = [voices.moderator()] + [p for p in voices.PROFILES if p.get("provider") != "chirp"]
    for screen in closing.OPENINGS:
        for line in closing.OPENINGS[screen] + closing.CLOSINGS.get(screen, []) + \
                ["Kusura bakmayın, sizi duyamadım. Tekrar eder misiniz?"]:
            for p in profiles:
                wanted.add(os.path.basename(voice._cache_path(line, p)))
    return sum(_remove(os.path.join(voice.CACHE_DIR, f)) for f in os.listdir(voice.CACHE_DIR) if f not in wanted)


def _temp_leftovers() -> int:
    limit = time.time() - 86400
    freed = 0
    for pat in ("fm_tts_*", "fm_warm_*"):
        for f in glob.glob(os.path.join(tempfile.gettempdir(), pat)):
            if os.path.getmtime(f) < limit:
                freed += _remove(f)
    return freed


def run_all(verbose: bool = True) -> int:
    freed = 0
    steps = [
        ("maç kayıtları", lambda: _keep_newest(os.path.join(C.BRIDGE_DIR, "matches", "match_*.jsonl"), KEEP_MATCHES)),
        ("toplantı kayıtları", lambda: _keep_newest(os.path.join(LOG_DIR, "press_*.json"), KEEP_PRESS)),
        ("uygulama kayıtları", lambda: _keep_newest(os.path.join(LOG_DIR, "live_*.log"), KEEP_LIVE)),
        ("eski UI dökümleri", _old_dumps),
        ("eskimiş ses önbelleği", _stale_tts_cache),
        ("geçici ses dosyaları", _temp_leftovers),
    ]
    parts = []
    for name, fn in steps:
        try:
            n = fn()
        except Exception as e:                    # temizlik asla uygulamayı durdurmasın
            print(f"  [temizlik] {name}: {e!r}")
            continue
        if n:
            parts.append(f"{name} {n / 1e6:.1f} MB")
            freed += n
    if verbose and parts:
        print(f"  [temizlik] silindi: {', '.join(parts)}")
    return freed
