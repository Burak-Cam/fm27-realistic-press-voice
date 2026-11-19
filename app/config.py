import os

# ---------------- Oyun / köprü ----------------
GAME_DIR = os.getenv("FM_GAME_DIR", r"C:\Program Files (x86)\Steam\steamapps\common\Football Manager 27")
# Eklenti ile konuşulan klasör (docs/protocol.md). Test/simülasyon için FM_BRIDGE_DIR ile değiştirilebilir.
BRIDGE_DIR = os.getenv("FM_BRIDGE_DIR", os.path.join(GAME_DIR, "BepInEx", "fm27pressvoice"))
POLL_SEC = 0.3

# ---------------- LLM ----------------
# Sırayla denenir; kota/ağ hatasında sıradakine geçilir. Seçenekler: gemini | openai | ollama | mock
PROVIDERS = [p.strip() for p in os.getenv("FM_LLM_PROVIDERS", os.getenv("FM_LLM_PROVIDER", "gemini,openai")).split(",") if p.strip()]

GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
# Model adları sık değişiyor: `py main.py check` ile hesabındaki modelleri listele, gerekirse GEMINI_MODEL ayarla.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")   # ölçümde en hızlı (~1,5 sn)
GEMINI_FALLBACK_MODELS = [m.strip() for m in os.getenv(
    "GEMINI_FALLBACK_MODELS", "gemini-3.5-flash-lite,gemini-flash-latest").split(",") if m.strip()]

# Groq (OpenAI uyumlu): base=https://api.groq.com/openai/v1
OPENAI_BASE = os.getenv("OPENAI_BASE", "https://api.groq.com/openai/v1")
OPENAI_KEY = os.getenv("OPENAI_API_KEY", os.getenv("GROQ_API_KEY", ""))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "llama-3.3-70b-versatile")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

LLM_TIMEOUT = float(os.getenv("FM_LLM_TIMEOUT", "8"))        # model başına; canlı toplantıda uzun bekleme olmasın
MODEL_COOLDOWN = float(os.getenv("FM_MODEL_COOLDOWN", "300"))  # 503/zaman aşımı veren model bu kadar sn atlanır

# ---------------- Ses ----------------
TTS_VOICE = os.getenv("FM_TTS_VOICE", "tr-TR-AhmetNeural")
TTS_RATE = os.getenv("FM_TTS_RATE", "+0%")
# Kullanıcı dinledi (2026-11-19): çok dilli sesler Türkçede bozuluyor ("şampiyonluk"), tok varyasyonlar kötü.
VOICES_OFF = os.getenv("FM_VOICES_OFF", "ahmet-tok,emel-tok,brian,william,andrew,remy,giuseppe,emma,ava,thalita")
MODERATOR_VOICE = os.getenv("FM_MODERATOR_VOICE", "")   # boş = otomatik (Chirp varsa chirp-sadaltager, yoksa ahmet)

# Google Cloud TTS Chirp 3 HD. ANAHTAR SADECE ORTAM DEĞİŞKENİNDE (setx GOOGLE_TTS_API_KEY). Repo public!
GOOGLE_TTS_KEY = os.getenv("GOOGLE_TTS_API_KEY", "")
# 0 TL garantisi: uygulama bu sınırlara gelince Chirp'e istek ATMAZ, edge-tts'e düşer (logs/tts_usage.json sayar).
CHIRP_MONTHLY_CHARS = int(os.getenv("FM_CHIRP_MONTHLY_CHARS", "500000"))   # ücretsiz kotanın yarısı (1M varsayımı)
CHIRP_DAILY_CHARS = int(os.getenv("FM_CHIRP_DAILY_CHARS", "40000"))        # kaçak döngüye karşı günlük sınır  # basın toplantısı moderatörü
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")    # small | medium
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")    # GPU FM27 ile paylaşılıyor -> varsayılan CPU int8
WHISPER_BEAM = int(os.getenv("WHISPER_BEAM", "1"))     # 1: ~2 sn, 5: ~12 sn (CPU, 7 sn ses), doğruluk testte aynı
# Bas-konuş tuşu (keyboard kütüphanesi adı). Cevap beklenirken tuş oyuna GİTMEZ (suppress), diğer zamanlarda serbest.
HOTKEY = os.getenv("FM_HOTKEY", "f8")
MIC = os.getenv("FM_MIC", "")           # mikrofon: ad parçası ya da numara (start.bat devices); boş = Windows varsayılanı
SPEAKER = os.getenv("FM_SPEAKER", "")   # hoparlör/kulaklık: ad parçası ya da numara; boş = Windows varsayılanı
MAX_RECORD_SEC = 90
BEEP = True                                            # kayıt başla/bitir sesi

# ---------------- Davranış ----------------
REPLACE_QUESTION = True        # oyundaki soru balonunu bizim soruyla değiştir
AUTO_ANSWER = True             # sınıflandırılan cevabı eklentiye gönder (eklentide AutoClick açıksa tıklar)
FOLLOW_UP_PROB = float(os.getenv("FM_FOLLOW_UP_PROB", "0.3"))  # takip sorusu olasılığı (oyuna etkisi yok, atmosfer)
LISTEN_RETRIES = 1             # cevap duyulmazsa kaç kez tekrar istenir
