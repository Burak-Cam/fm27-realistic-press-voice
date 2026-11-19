"""Gazeteci sesleri: her gazeteciye adına göre sabit, toplantıda başkasıyla çakışmayan bir ses profili.

İki sağlayıcı: Google Chirp 3 HD (GOOGLE_TTS_API_KEY varsa; 30 Türkçe ses, aylık/günlük karakter sınırıyla 0 TL) ve
edge-tts (anahtarsız; Ahmet/Emel + varyasyonlar). Chirp sınıra gelince ya da hata verince edge'e düşülür.
Beğenilmeyen profiller FM_VOICES_OFF ile kapatılır (virgülle id listesi). Dinlemek için: start.bat voices
"""
import hashlib
import json
import os

import config as C

# id, edge-tts sesi, cinsiyet, perde, hız, açıklama
PROFILES = [
    {"id": "ahmet", "voice": "tr-TR-AhmetNeural", "gender": "m", "pitch": "+0Hz", "rate": "+0%", "label": "Ahmet (doğal)"},
    {"id": "ahmet-tok", "voice": "tr-TR-AhmetNeural", "gender": "m", "pitch": "-12Hz", "rate": "-6%", "label": "Ahmet, tok ve yavaş"},
    {"id": "ahmet-genc", "voice": "tr-TR-AhmetNeural", "gender": "m", "pitch": "+10Hz", "rate": "+8%", "label": "Ahmet, genç ve hızlı"},
    {"id": "brian", "voice": "en-US-BrianMultilingualNeural", "gender": "m", "pitch": "+0Hz", "rate": "+0%", "label": "Brian (çok dilli)"},
    {"id": "william", "voice": "en-AU-WilliamMultilingualNeural", "gender": "m", "pitch": "+0Hz", "rate": "+0%", "label": "William (çok dilli)"},
    {"id": "andrew", "voice": "en-US-AndrewMultilingualNeural", "gender": "m", "pitch": "+0Hz", "rate": "+0%", "label": "Andrew (çok dilli)"},
    {"id": "remy", "voice": "fr-FR-RemyMultilingualNeural", "gender": "m", "pitch": "+0Hz", "rate": "+0%", "label": "Remy (çok dilli)"},
    {"id": "giuseppe", "voice": "it-IT-GiuseppeMultilingualNeural", "gender": "m", "pitch": "+0Hz", "rate": "+0%", "label": "Giuseppe (çok dilli)"},
    {"id": "emel", "voice": "tr-TR-EmelNeural", "gender": "f", "pitch": "+0Hz", "rate": "+0%", "label": "Emel (doğal)"},
    {"id": "emel-tok", "voice": "tr-TR-EmelNeural", "gender": "f", "pitch": "-10Hz", "rate": "-5%", "label": "Emel, tok ve yavaş"},
    {"id": "emel-genc", "voice": "tr-TR-EmelNeural", "gender": "f", "pitch": "+8Hz", "rate": "+7%", "label": "Emel, genç ve hızlı"},
    {"id": "emma", "voice": "en-US-EmmaMultilingualNeural", "gender": "f", "pitch": "+0Hz", "rate": "+0%", "label": "Emma (çok dilli)"},
    {"id": "ava", "voice": "en-US-AvaMultilingualNeural", "gender": "f", "pitch": "+0Hz", "rate": "+0%", "label": "Ava (çok dilli)"},
    {"id": "thalita", "voice": "pt-BR-ThalitaMultilingualNeural", "gender": "f", "pitch": "+0Hz", "rate": "+0%", "label": "Thalita (çok dilli)"},
]
# Google Chirp 3 HD Türkçe sesleri (sakin/ciddi karakterliler; enerjik olanlar -Kore, Puck- alınmadı).
# Kullanıcı Gemini örneklerini dinledi (aynı ses ailesi): Charon, Schedar, Iapetus, Erinome, Vindemiatrix, Gacrux beğenildi.
CHIRP_VOICES = [("Charon", "m"), ("Schedar", "m"), ("Iapetus", "m"), ("Rasalgethi", "m"), ("Sadaltager", "m"),
                ("Alnilam", "m"), ("Orus", "m"), ("Algieba", "m"),
                ("Erinome", "f"), ("Vindemiatrix", "f"), ("Gacrux", "f"), ("Sulafat", "f"), ("Achernar", "f"), ("Despina", "f")]
PROFILES += [{"id": f"chirp-{n.lower()}", "provider": "chirp", "voice": f"tr-TR-Chirp3-HD-{n}", "gender": g,
              "speaking_rate": 1.0, "label": f"{n} (Chirp 3 HD)"} for n, g in CHIRP_VOICES]

BY_ID = {p["id"]: p for p in PROFILES}
NATIVE = {"m": BY_ID["ahmet"], "f": BY_ID["emel"]}   # sentez hatasında / Chirp sınırında yedek

# Sık Türkçe kadın adları (gazeteci cinsiyetini tahmin etmek için; listede yoksa erkek sayılır)
FEMALE_NAMES = set("""
ayşe fatma emine hatice zeynep elif meryem şerife zehra sultan hanife merve özlem yasemin esra ebru büşra
gamze tuğba derya seda sevgi sibel songül gül gülşen gülay hülya filiz nurcan nur nuray nermin nesrin neslihan
pınar burcu didem dilek ece eda ebru esin ezgi gizem ilknur ipek irem kader leyla melek melike melis meltem
nazlı nihan oya özge selin sena serap sevda sinem tuba tülay yeliz yeşim zerrin aslı aylin ayten aysel aynur
banu başak betül beyza bilge buse cansu ceren damla defne dilara duygu elçin elvan esma feride gonca gökçe hande
havva hilal ilayda işıl kübra lale mine müge nalan nilüfer nilay nisa pelin rabia sanem selda sevil şule tansu
tülin ümran yağmur yıldız zuhal begüm ela azra ecrin eylül nehir asya mira lara
""".split())

_MAP_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "voices_map.json")


def chirp_available() -> bool:
    return bool(os.getenv("GOOGLE_TTS_API_KEY", C.GOOGLE_TTS_KEY))


def enabled() -> list[dict]:
    """Chirp anahtarı varsa sadece Chirp sesleri (edge ile karışık olmasın), yoksa edge-tts sesleri."""
    off = {x.strip() for x in os.getenv("FM_VOICES_OFF", C.VOICES_OFF).split(",") if x.strip()}
    want = "chirp" if chirp_available() else "edge"
    return [p for p in PROFILES if p["id"] not in off and p.get("provider", "edge") == want]


def guess_gender(name: str | None) -> str:
    first = (name or "").strip().split(" ")[0].lower().replace("i̇", "i")
    return "f" if first in FEMALE_NAMES else "m"


def moderator() -> dict:
    if C.MODERATOR_VOICE in BY_ID:
        return BY_ID[C.MODERATOR_VOICE]
    return BY_ID["chirp-sadaltager"] if chirp_available() else BY_ID["ahmet"]


class VoiceBook:
    """Gazeteci adı -> profil. Kalıcı (aynı gazeteci hep aynı ses), toplantı içinde çakışmasız."""

    def __init__(self, path: str | None = _MAP_FILE):
        self.path = path
        self.saved: dict[str, str] = self._load()
        self.in_use: dict[str, str] = {}   # bu toplantı: ad -> profil id

    def new_conference(self):
        self.in_use = {}

    def for_journalist(self, journalist: dict | None) -> dict:
        name = (journalist or {}).get("name") or "?"
        if name in self.in_use:
            return BY_ID[self.in_use[name]]
        gender = guess_gender(name)
        pool = [p for p in enabled() if p["gender"] == gender] or [NATIVE[gender]]
        taken = set(self.in_use.values()) | {moderator()["id"]}
        prof = BY_ID.get(self.saved.get(name))
        if prof is None or prof not in pool or prof["id"] in taken:
            start = int(hashlib.md5(name.encode("utf-8")).hexdigest(), 16) % len(pool)
            order = pool[start:] + pool[:start]
            prof = next((p for p in order if p["id"] not in taken), order[0])
            if self.saved.get(name) is None:      # kalıcı eşleme sadece ilk seferde yazılır
                self.saved[name] = prof["id"]
                self._save()
        self.in_use[name] = prof["id"]
        return prof

    def _load(self) -> dict:
        if not self.path:
            return {}
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save(self):
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.saved, f, ensure_ascii=False, indent=1)
        except OSError:
            pass
