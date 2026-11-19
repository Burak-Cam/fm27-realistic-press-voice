"""Kullanıcı ayarları: app/settings.ini (kişiye özel, repoya girmez; örnek: settings.example.ini).

config.py'den önce yüklenir ve ayarları ortam değişkeni varsayılanı olarak koyar. Ortam değişkeni varsa o kazanır.
API ANAHTARLARI BURAYA YAZILMAZ: sadece ortam değişkeninde (setx) durur; ini'de anahtar bulunursa yok sayılır.
"""
import configparser
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.ini")

# ini anahtarı -> ortam değişkeni
KEYS = {
    "oyun_klasoru": "FM_GAME_DIR",
    "bas_konus_tusu": "FM_HOTKEY",
    "mikrofon": "FM_MIC",
    "hoparlor": "FM_SPEAKER",
    "okuma_hizi": "FM_TTS_SPEED",
    "takip_sorusu_olasiligi": "FM_FOLLOW_UP_PROB",
    "kapali_sesler": "FM_VOICES_OFF",
    "moderator_sesi": "FM_MODERATOR_VOICE",
    "soru_sure_siniri": "FM_QUESTION_BUDGET",
    "sakla_mac": "FM_KEEP_MATCHES",
    "sakla_toplanti": "FM_KEEP_PRESS_LOGS",
    "chirp_aylik_karakter": "FM_CHIRP_MONTHLY_CHARS",
    "chirp_gunluk_karakter": "FM_CHIRP_DAILY_CHARS",
}
_SECRET_HINTS = ("key", "anahtar", "token", "secret", "sifre", "şifre", "password")


def load(path: str = PATH) -> list[str]:
    """Ayarları ortam varsayılanı yap; uyarıları döndür."""
    warnings = []
    if not os.path.exists(path):
        return warnings
    cp = configparser.ConfigParser()
    try:
        cp.read(path, encoding="utf-8")
    except configparser.Error as e:
        return [f"settings.ini okunamadı: {e}"]
    for section in cp.sections():
        for k, v in cp.items(section):
            v = v.strip()
            if any(h in k.lower() for h in _SECRET_HINTS):
                warnings.append(f"settings.ini: '{k}' yok sayıldı (anahtarlar sadece ortam değişkeninde durur: setx)")
                continue
            env = KEYS.get(k.lower())
            if not env:
                warnings.append(f"settings.ini: bilinmeyen ayar '{k}'")
                continue
            if v and env not in os.environ:
                os.environ[env] = v
    return warnings


WARNINGS = load()
