"""FM27 sesli basın toplantısı yan uygulaması.

  py main.py                 canlı: oyunla (eklenti) konuş, soruları sesli oku, cevabı bas-konuş ile al
  py main.py --text          canlı ama cevabı klavyeden yaz (mikrofonsuz deneme)
  py main.py sim [--voice]   oyunsuz: sahte eklenti + gerçek dökümlerden sorular (varsayılan klavye, TTS kapalı)
  py main.py check           ayarlar, API anahtarları, Gemini modelleri, TTS/mikrofon kontrolü
Seçenekler: --match maç.json (bağlam verisi), --no-tts, --follow-up 0.3
"""
import argparse
import json
import os
import sys
import tempfile
import threading

# Windows konsolunda Türkçe karakterler
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import config as C
from bridge import BridgeIO
from session import PressSession


def _speaker(enabled: bool):
    if not enabled:
        return lambda text: None
    from voice import speak
    return speak


def _listener(text_mode: bool):
    import voice
    if text_mode:
        return voice.listen_text
    voice.load_stt()          # modeli baştan yükle (ilk cevapta beklemesin)
    return voice.listen_voice


class _Tee:
    """Konsol çıktısını logs/live_*.log dosyasına da yazar (sonradan incelemek için)."""

    def __init__(self, stream, path):
        self.stream, self.f = stream, open(path, "a", encoding="utf-8", buffering=1)

    def write(self, s):
        self.stream.write(s)
        self.f.write(s)

    def flush(self):
        self.stream.flush()
        self.f.flush()


def cmd_live(a):
    log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
    os.makedirs(log_dir, exist_ok=True)
    from datetime import datetime
    sys.stdout = _Tee(sys.stdout, os.path.join(log_dir, f"live_{datetime.now():%Y%m%d_%H%M%S}.log"))
    import llm
    import status
    threading.Thread(target=llm.warm_up, daemon=True).start()
    if not a.no_tts:
        import voice
        def _warm():
            voice.warm_voices()
            voice.precache_fixed_lines()
        threading.Thread(target=_warm, daemon=True).start()
    status.start(C.BRIDGE_DIR)
    status.set("loading", "Ses tanıma yükleniyor, birkaç saniye...")
    match = json.load(open(a.match, encoding="utf-8")) if a.match else None
    s = PressSession(BridgeIO(), _speaker(not a.no_tts), _listener(a.text), match=match, follow_up_prob=a.follow_up)
    status.set("idle")
    try:
        s.run()
    except KeyboardInterrupt:
        print("\nÇıkılıyor.")
    finally:
        status.stop()


def cmd_sim(a):
    from sim_plugin import SimPlugin, load_states
    folder = tempfile.mkdtemp(prefix="fm_sim_")
    states = load_states(a.states or None)
    sim = SimPlugin(folder, states)
    t = threading.Thread(target=sim.run, daemon=True)
    t.start()
    match = json.load(open(a.match, encoding="utf-8")) if a.match else None
    s = PressSession(BridgeIO(folder), _speaker(a.voice and not a.no_tts), _listener(not a.voice),
                     match=match, follow_up_prob=a.follow_up)
    try:
        s.run(stop=sim.done.is_set)
    except KeyboardInterrupt:
        pass
    print(f"\nSahte eklentiye giden komutlar: {len(sim.log)}")


def cmd_check(a):
    print(f"Köprü klasörü : {C.BRIDGE_DIR} ({'var' if os.path.isdir(C.BRIDGE_DIR) else 'YOK'})")
    st = BridgeIO().read_state()
    print(f"press_state   : {'yok (eklenti henüz yazmadı / oyun kapalı)' if st is None else ('aktif' if st.get('active') else 'pasif') + ' seq=' + str(st.get('seq'))}")
    print(f"LLM sırası    : {C.PROVIDERS}")
    print(f"GEMINI_API_KEY: {'var' if C.GEMINI_KEY else 'YOK'}  model={C.GEMINI_MODEL}")
    print(f"OPENAI/GROQ   : {'var' if C.OPENAI_KEY else 'YOK'}  {C.OPENAI_BASE} {C.OPENAI_MODEL}")
    if C.GEMINI_KEY:
        try:
            from llm import list_gemini_models
            ms = list_gemini_models()
            print(f"Gemini modelleri ({len(ms)}): {', '.join(m for m in ms if 'flash' in m)}")
        except Exception as e:
            print(f"Gemini model listesi alınamadı: {e}")
    try:
        from llm import ask
        print("LLM deneme   :", ask('Sadece JSON döndür: {"ok": true}', task="ping"))
    except Exception as e:
        print(f"LLM deneme   : BAŞARISIZ -> {e}")
    try:
        import devices
        mic, spk = devices.describe()
        print(f"Mikrofon      : {mic}")
        print(f"Hoparlör      : {spk}")
    except Exception as e:
        print(f"Ses cihazları : HATA -> {e}")
    try:
        from voice import synth
        p = os.path.join(tempfile.gettempdir(), "fm_check.mp3")
        synth("Merhaba hocam, basın toplantısına hoş geldiniz.", p)
        print(f"TTS           : OK ({os.path.getsize(p)} bayt)")
    except Exception as e:
        print(f"TTS           : HATA -> {e}")
    print(f"Bas-konuş tuşu: {C.HOTKEY}  STT: {C.WHISPER_MODEL}/{C.WHISPER_DEVICE}")
    import voices
    import tts_chirp
    if voices.chirp_available():
        m, d = tts_chirp.usage()
        print(f"Chirp TTS     : anahtar var  bu ay {m}/{C.CHIRP_MONTHLY_CHARS}, bugün {d}/{C.CHIRP_DAILY_CHARS} karakter")
        try:
            import tempfile as _t
            p = os.path.join(_t.gettempdir(), "fm_chirp_check.mp3")
            tts_chirp.synth("Merhaba hocam.", p, voices.BY_ID["chirp-charon"])
            print(f"Chirp deneme  : OK ({os.path.getsize(p)} bayt)")
        except Exception as e:
            print(f"Chirp deneme  : HATA -> {str(e)[:200]}")
    else:
        print("Chirp TTS     : GOOGLE_TTS_API_KEY yok (edge-tts kullanılıyor)")


def cmd_devices(a):
    """Mikrofon ve hoparlörleri listeler; seçim FM_MIC / FM_SPEAKER ile (ad parçası ya da numara)."""
    import sounddevice as sd
    import devices
    mic, spk = devices.describe()
    print("Mikrofonlar (FM_MIC):")
    for i, n in devices.input_devices(list(sd.query_devices()), list(sd.query_hostapis())):
        print(f"  {i:3}  {n}")
    print("\nHoparlör / kulaklık (FM_SPEAKER):")
    for i, n in enumerate(devices.output_names()):
        print(f"  {i:3}  {n}")
    print(f"\nŞu an seçili  -> mikrofon: {mic}\n                 hoparlör: {spk}")
    print('\nÖrnek: setx FM_MIC "Kulaklık"   setx FM_SPEAKER "Kulaklık"   (sonra yeni pencere; silmek için setx FM_MIC "")')


def cmd_voices(a):
    """Tüm ses profillerini sırayla çalar (beğenmediklerini FM_VOICES_OFF ile kapat)."""
    import voice
    import voices
    text = "Hocam, deplasmandaki bu derbi galibiyeti sizi ne kadar sevindirdi? Şampiyonluk yarışında ağırlığı nedir?"
    off = {x.strip() for x in C.VOICES_OFF.split(",") if x.strip()}
    for p in voices.PROFILES:
        print(f"  {p['id']:12} {p['label']}{'   (KAPALI)' if p['id'] in off else ''}")
        voice.speak(text, None, p)
    print("\nBeğenmediklerini kapatmak için: setx FM_VOICES_OFF \"id1,id2\"  (sonra yeni pencere)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="live", choices=["live", "sim", "check", "voices", "devices"])
    ap.add_argument("states", nargs="*", help="sim: kullanılacak durum dosyaları (varsayılan sample_states/)")
    ap.add_argument("--text", action="store_true", help="cevabı klavyeden yaz")
    ap.add_argument("--voice", action="store_true", help="sim: sesli mod (TTS + bas-konuş)")
    ap.add_argument("--no-tts", action="store_true")
    ap.add_argument("--match", help="maç verisi JSON (eklenti maç verisi vermeyene kadar)")
    ap.add_argument("--follow-up", type=float, default=None, help="takip sorusu olasılığı 0-1")
    a = ap.parse_args()
    {"live": cmd_live, "sim": cmd_sim, "check": cmd_check, "voices": cmd_voices, "devices": cmd_devices}[a.cmd](a)


if __name__ == "__main__":
    main()
