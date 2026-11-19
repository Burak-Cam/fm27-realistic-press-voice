"""TTS (edge-tts), bas-konuş kayıt (global hotkey), STT (faster-whisper)."""
import asyncio
import os
import tempfile
import threading
import time

import numpy as np

import config as C
import status

SR = 16000


# ---------------- TTS ----------------
def synth(text: str, path: str, profile: dict | None = None):
    """profile: voices.py profili (ses/perde/hız). Sentez başarısızsa aynı cinsiyetin doğal Türkçe sesine düşer."""
    import edge_tts
    if not profile:
        asyncio.run(edge_tts.Communicate(text, C.TTS_VOICE, rate=C.TTS_RATE).save(path))
        return
    try:
        if profile.get("provider") == "chirp":
            import tts_chirp
            tts_chirp.synth(text, path, profile)
        else:
            asyncio.run(edge_tts.Communicate(text, profile["voice"], rate=profile["rate"], pitch=profile["pitch"]).save(path))
    except Exception as e:
        import voices
        fb = voices.NATIVE[profile.get("gender", "m")]
        if fb["voice"] == profile["voice"]:
            raise
        print(f"  [tts] {profile['id']} kullanılamadı ({type(e).__name__}: {str(e)[:80]}), {fb['id']} kullanılıyor")
        asyncio.run(edge_tts.Communicate(text, fb["voice"], rate=fb["rate"], pitch=fb["pitch"]).save(path))


def warm_voices():
    """Açılışta her sesi bir kez kısa metinle dene: ilk kullanım 8 sn'ye kadar sürebiliyor, sonrakiler ~1 sn."""
    import voices
    t0 = time.time()
    seen = set()
    for p in voices.enabled():
        if p["voice"] in seen or p.get("provider") == "chirp":   # Chirp'te ısınma gereksiz, kota harcamasın
            continue
        seen.add(p["voice"])
        fd, path = tempfile.mkstemp(suffix=".mp3", prefix="fm_warm_")
        os.close(fd)
        try:
            synth("Merhaba.", path, p)
        except Exception as e:
            print(f"  [tts] {p['id']} ısınmadı: {type(e).__name__}")
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
    print(f"  [tts] {len(seen)} ses hazır ({time.time() - t0:.1f} sn)")


def prepare(text: str, profile: dict | None = None) -> str | None:
    """Sesi önceden sentezler (~1-2 sn, ağ). Dosya yolunu döndürür; hata olursa None."""
    if not text:
        return None
    try:
        fd, path = tempfile.mkstemp(suffix=".mp3", prefix="fm_tts_")
        os.close(fd)
        synth(text, path, profile)
        return path
    except Exception as e:  # ağ yok...
        print(f"  [tts] sentezlenemedi: {e}")
        return None


_mixer_ready = False


def play(path: str | None, should_abort=None):
    """Hazır ses dosyasını çalar (bloklar), sonra siler. should_abort() True olursa keser."""
    global _mixer_ready
    if not path:
        return
    try:
        import pygame
        if not _mixer_ready:
            import devices
            name = devices.speaker_name()
            if name:
                pygame.mixer.init(devicename=name)
            else:
                pygame.mixer.init()
            _mixer_ready = True
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            if should_abort and should_abort():
                pygame.mixer.music.stop()
                print("  [tts] soru değişti, okuma kesildi")
                break
            pygame.time.wait(30)
        pygame.mixer.music.unload()
    except Exception as e:  # ses aygıtı yok...
        print(f"  [tts] çalınamadı: {e}")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def reset_output():
    """Çıkış cihazını bırak: sonraki okumada yeniden seçilir (toplantı başında; sonradan takılan kulaklık için)."""
    global _mixer_ready
    if _mixer_ready:
        try:
            import pygame
            pygame.mixer.quit()
        except Exception:
            pass
        _mixer_ready = False


def speak(text: str, should_abort=None, profile: dict | None = None):
    """Metni sesli okur (bloklar). should_abort() True olursa (soru ekranda değişti) okumayı keser."""
    if not text or (should_abort and should_abort()):
        return
    play(prepare(text, profile), should_abort)


speak.abortable = True
speak.voiced = True        # prepare/speak ses profili alır
speak.reset = reset_output
speak.prepare = prepare
speak.play = play


def beep(start: bool):
    if not C.BEEP:
        return
    try:
        import winsound
        winsound.Beep(880 if start else 520, 120)
    except Exception:
        pass


# ---------------- STT ----------------
_model = None
_model_lock = threading.Lock()


def load_stt():
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            ct = "int8" if C.WHISPER_DEVICE == "cpu" else "float16"
            t0 = time.time()
            _model = WhisperModel(C.WHISPER_MODEL, device=C.WHISPER_DEVICE, compute_type=ct)
            # ısınma: ilk gerçek cevap yavaş olmasın (ilk çözümleme ~15 sn sürüyordu)
            noise = (np.random.default_rng(0).standard_normal(SR * 2) * 0.01).astype(np.float32)
            list(_model.transcribe(noise, language="tr", beam_size=1, vad_filter=False)[0])
            print(f"  [stt] {C.WHISPER_MODEL} yüklendi ve ısındı ({time.time() - t0:.1f} sn)")
    return _model


def transcribe(audio) -> str:
    """audio: 16 kHz mono float32 dizi ya da ses dosyası yolu."""
    if audio is None or (isinstance(audio, np.ndarray) and audio.size < SR * 0.3):
        return ""
    segs, _ = load_stt().transcribe(audio, language="tr", vad_filter=True, beam_size=C.WHISPER_BEAM,
                                    initial_prompt="Futbol basın toplantısında teknik direktörün cevabı.")
    return " ".join(s.text.strip() for s in segs).strip()


# ---------------- Bas-konuş ----------------
class PushToTalk:
    """Tuşa bas -> kayıt başlar, tekrar bas -> biter. Dinlerken tuş oyuna iletilmez (suppress)."""

    def __init__(self, hotkey: str | None = None):
        self.hotkey = hotkey or C.HOTKEY

    def record(self, should_abort=lambda: False) -> np.ndarray | None:
        """Kaydı döndürür; should_abort() True olursa (soru değişti vb.) None."""
        import keyboard
        import sounddevice as sd

        presses = []
        ev = threading.Event()

        def on_press():
            presses.append(time.time())
            ev.set()

        handle = keyboard.add_hotkey(self.hotkey, on_press, suppress=True, trigger_on_release=False)
        try:
            print(f"  [{self.hotkey.upper()}] konuşmak için bas...")
            status.set("waiting_key")
            while not ev.wait(0.2):
                if should_abort():
                    return None
            ev.clear()
            beep(True)
            chunks = []
            import devices
            with sd.InputStream(device=devices.mic_device(), samplerate=SR, channels=1, dtype="float32",
                                callback=lambda d, *_: chunks.append(d.copy())):
                print(f"  ● kayıt... (bitirmek için [{self.hotkey.upper()}])")
                status.set("recording")
                t0 = time.time()
                while not ev.wait(0.2):
                    if should_abort():
                        return None
                    if time.time() - t0 > C.MAX_RECORD_SEC:
                        print("  kayıt süre sınırı doldu")
                        break
            beep(False)
            return np.concatenate(chunks).flatten() if chunks else None
        finally:
            keyboard.remove_hotkey(handle)


def listen_voice(should_abort=lambda: False) -> str | None:
    """None = iptal, "" = duyulamadı."""
    audio = PushToTalk().record(should_abort)
    if audio is None:
        return None
    t0 = time.time()
    status.set("transcribing")
    text = transcribe(audio)
    print(f"  [stt] {time.time() - t0:.1f} sn")
    return text


def listen_text(should_abort=lambda: False) -> str | None:
    """Test modu: cevabı klavyeden yaz."""
    try:
        return input("  Cevabın > ").strip()
    except EOFError:
        return None
