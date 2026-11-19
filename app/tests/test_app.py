import json
import os
import threading
import time

import pytest

import config as C
import llm
import press
from bridge import BridgeIO
from session import PressSession
from sim_plugin import SimPlugin, load_states


def _speech(spoken):
    """Açılış cümlesini çıkar (her toplantı başında okunur)."""
    import closing
    opens = {m for v in closing.OPENINGS.values() for m in v}
    return [x for x in spoken if x not in opens]


def _until(sim, limit=60):
    end = time.time() + limit
    return lambda: sim.done.is_set() or time.time() > end


@pytest.fixture(autouse=True)
def mock_llm(monkeypatch):
    monkeypatch.setattr(C, "PROVIDERS", ["mock"])
    calls = []

    def handler(prompt, task):
        calls.append((task, prompt))
        if task == "question":
            return {"question": "ÜRETİLEN SORU", "event": "post_match"}
        if task == "classify":
            # cevapta "harika" geçiyorsa olumlu (positive) kategoriyi seç
            return {"category_index": 0, "option_index": 1, "display_text": "Temiz cevap.", "follow_up": None, "reason": "test"}
        return {}

    llm.set_mock(handler)
    yield calls
    llm.set_mock(None)


def test_sample_states_loaded():
    states = load_states()
    assert len(states) >= 10
    for s in states:
        assert s["question_id"] and s["game_question"] and s["categories"]


def test_question_prompt_contains_game_question_and_options(mock_llm):
    st = load_states()[0]
    r = press.generate_question(st, {"score": "2-1"}, [])
    assert r == {"question": "ÜRETİLEN SORU", "event": "post_match", "source": "llm"}
    prompt = mock_llm[-1][1]
    assert st["game_question"] in prompt
    assert st["categories"][0]["title"] in prompt
    assert '"score": "2-1"' in prompt


def test_context_in_question_prompt(mock_llm):
    st = dict(load_states()[0], context={"next_opponent": "Real Madrid", "date": "CUM 4 EYL"})
    press.generate_question(st)
    assert "Real Madrid" in mock_llm[-1][1] and "CUM 4 EYL" in mock_llm[-1][1]


def test_question_fallback_to_game_question():
    llm.set_mock(lambda p, t: (_ for _ in ()).throw(llm.LLMError("kota")))
    st = load_states()[0]
    r = press.generate_question(st)
    assert r["source"] == "game" and r["question"] == st["game_question"]


def test_classify_invalid_index_falls_back_to_neutral():
    llm.set_mock(lambda p, t: {"category_index": 99, "option_index": 0, "display_text": "x"})
    st = load_states()[0]
    r = press.classify_answer(st, "soru", "cevap")
    neutral = next(c["index"] for c in st["categories"] if c["sentiment"] == "neutral")
    assert r["source"] == "fallback" and r["category_index"] == neutral and r["display_text"] == "cevap"


def test_classify_option_index_clamped():
    llm.set_mock(lambda p, t: {"category_index": 0, "option_index": 7, "display_text": "ok"})
    r = press.classify_answer(load_states()[0], "soru", "cevap")
    assert r["category_index"] == 0 and r["option_index"] == 0 and r["source"] == "llm"


def test_end_to_end_with_sim_plugin(tmp_path):
    states = load_states()
    sim = SimPlugin(str(tmp_path), states, linger=0.05)
    threading.Thread(target=sim.run, daemon=True).start()
    answers = iter([f"cevap {i}" for i in range(100)])
    spoken = []
    s = PressSession(BridgeIO(str(tmp_path)), spoken.append, lambda abort: next(answers),
                     follow_up_prob=0, log_dir=str(tmp_path / "logs"))
    s.run(stop=_until(sim))
    q = [c for c in sim.log if c["type"] == "question"]
    a = [c for c in sim.log if c["type"] == "answer"]
    assert len(a) == len(states), sim.log
    assert len(q) == len(states)
    assert all(x["display_text"] == "Temiz cevap." for x in a)
    assert [x["question_id"] for x in a] == [st["question_id"] for st in states]
    assert spoken.count("ÜRETİLEN SORU") == len(states)
    logs = [f for f in os.listdir(tmp_path / "logs") if f.startswith("press_")]
    assert logs, "toplantı kaydı yazılmadı"
    hist = json.load(open(tmp_path / "logs" / logs[0], encoding="utf-8"))
    assert all(h["applied"]["ok"] for h in hist)


def test_silence_retries_then_gives_up(tmp_path):
    states = load_states()[:1]
    sim = SimPlugin(str(tmp_path), states, linger=0.05)
    t = threading.Thread(target=sim.run, kwargs={"timeout_per_state": 2}, daemon=True)
    t.start()
    spoken = []
    s = PressSession(BridgeIO(str(tmp_path)), spoken.append, lambda abort: "", follow_up_prob=0,
                     log_dir=str(tmp_path / "logs"))
    s.run(stop=_until(sim))
    assert not [c for c in sim.log if c["type"] == "answer"]
    assert any("duyamadım" in x for x in spoken)


def test_follow_up_spoken_before_answer(tmp_path):
    llm.set_mock(lambda p, t: {"question": "S", "event": "pre_match"} if t == "question" else
                 {"category_index": 0, "option_index": 0, "display_text": "D", "follow_up": "Peki neden?"})
    states = load_states()[:1]
    sim = SimPlugin(str(tmp_path), states, linger=0.05)
    threading.Thread(target=sim.run, daemon=True).start()
    spoken = []
    s = PressSession(BridgeIO(str(tmp_path)), spoken.append, lambda abort: "cevap", follow_up_prob=1,
                     log_dir=str(tmp_path / "logs"))
    s.run(stop=_until(sim))
    assert _speech(spoken)[:2] == ["S", "Peki neden?"]
    assert len([c for c in sim.log if c["type"] == "answer"]) == 1


class _FakeIO:
    """Oyunun soruyu biz hazırlarken değiştirdiği durumu taklit eder."""

    dir = "(sahte)"

    def __init__(self, state):
        self.state, self.writes = state, []

    def read_state(self):
        return self.state

    def write_question(self, qid, text):
        self.writes.append(("question", qid))

    def write_answer(self, *a):
        self.writes.append(("answer",) + a)

    def wait_applied(self, *a, **k):
        return None


def test_stale_question_not_spoken(tmp_path):
    """Soru üretilirken oyunda soru değiştiyse (kullanıcı elle tıkladı) okunmaz, eklentiye bir şey gönderilmez."""
    st = dict(load_states()[0], active=True, ready=True)
    io = _FakeIO(st)

    def handler(prompt, task):
        io.state = dict(st, question_id="yeni_soru")   # LLM beklerken oyun sonraki soruya geçti
        return {"question": "GEÇ KALAN SORU", "event": "pre_match"}

    llm.set_mock(handler)
    spoken = []
    s = PressSession(io, spoken.append, lambda abort: "cevap", follow_up_prob=0, log_dir=str(tmp_path / "logs"))
    s.handle(st)
    assert spoken == [] and io.writes == []


def test_speech_aborted_when_question_changes(tmp_path):
    """Okuma sırasında soru değişirse dinlemeye geçilmez, cevap gönderilmez."""
    st = dict(load_states()[0], active=True, ready=True)
    io = _FakeIO(st)
    spoken = []

    def speaker(text, should_abort=None):
        spoken.append(text)
        io.state = dict(st, question_id="yeni_soru")
        end = time.time() + 3                           # gerçek speak gibi okurken soruyu yokla
        while time.time() < end and not (should_abort and should_abort()):
            time.sleep(0.05)
    speaker.abortable = True

    listened = []
    s = PressSession(io, speaker, lambda abort: listened.append(1) or "cevap", follow_up_prob=0,
                     log_dir=str(tmp_path / "logs"))
    s.handle(st)
    assert spoken == ["ÜRETİLEN SORU"] and not listened
    assert not [w for w in io.writes if w[0] == "answer"]


def test_audio_prepared_before_question_shown(tmp_path):
    """Ses sentezi soru ekrana yazılmadan önce biter; soru yazılınca hemen çalınır (ekran ve ses birlikte)."""
    st = dict(load_states()[0], active=True, ready=True)
    io = _FakeIO(st)
    order = []
    orig_write = io.write_question
    io.write_question = lambda qid, text: (order.append("ekrana"), orig_write(qid, text))

    def speaker(text, should_abort=None):
        order.append("speak")
    speaker.abortable = True
    speaker.prepare = lambda text: order.append("hazırla") or "ses.mp3"
    speaker.play = lambda path, abort=None: order.append("çal:" + path)

    s = PressSession(io, speaker, lambda abort: "cevap", follow_up_prob=0, log_dir=str(tmp_path / "logs"))
    s.handle(st)
    assert order == ["hazırla", "ekrana", "çal:ses.mp3"]


def test_status_file_written(tmp_path):
    import status
    status.start(str(tmp_path))
    try:
        status.set("waiting_key")
        d = json.load(open(tmp_path / "app_status.json", encoding="utf-8"))
        assert d["phase"] == "waiting_key" and "F8" in d["text"] and d["time_ms"] > 0
    finally:
        status.stop()
    assert not (tmp_path / "app_status.json").exists()


def test_closing_line_varies_and_avoids_repeats(tmp_path):
    import closing
    path = str(tmp_path / "recent.json")
    lines = [closing.make("press_conference", "pre_match", path) for _ in range(30)]
    assert all(lines[i] not in lines[max(0, i - 3):i] for i in range(len(lines)))   # son 3 cümle tekrar etmez
    assert set(lines) <= set(closing.CLOSINGS["press_conference"])
    assert all(len(v) >= 7 for v in closing.CLOSINGS.values())
    assert all(len(v) >= 7 for v in closing.OPENINGS.values())
    ops = [closing.make_opening("tunnel_interview", None, str(tmp_path / "o.json")) for _ in range(20)]
    assert set(ops) <= set(closing.OPENINGS["tunnel_interview"])
    assert all(ops[i] not in ops[max(0, i - 3):i] for i in range(len(ops)))


def test_closing_spoken_on_game_thank_you_bubble(tmp_path):
    """Soru(lar) cevaplandıktan sonra oyun 'Çok teşekkürler.' balonunu gösterince kapanış bir kez okunur ve balona yazılır."""
    states = load_states()
    q = dict(states[0], active=True, ready=True)
    bye = dict(q, question_id="kapanis", game_question="Çok teşekkürler.", categories=[], ready=False)
    io = _FakeIO(q)
    spoken = []

    def listen(abort):
        io.state = bye                                          # cevaptan sonra oyun kapanış balonuna geçti
        return "cevap"

    s = PressSession(io, spoken.append, listen, follow_up_prob=0, log_dir=str(tmp_path / "logs"))
    end = time.time() + 4
    s.run(stop=lambda: time.time() > end or s.closed)
    spoken = _speech(spoken)
    assert spoken[0] == "ÜRETİLEN SORU"
    import closing
    assert len(spoken) == 2 and spoken[1] in {x for v in closing.CLOSINGS.values() for x in v}
    assert ("question", bye["question_id"]) in io.writes


def test_closing_spoken_when_screen_closes(tmp_path):
    """Kapanış balonu olmadan ekran kapanırsa da kapanış okunur (bir kez)."""
    st = dict(load_states()[0], active=True, ready=True)
    io = _FakeIO(st)
    spoken = []

    def listen(abort):
        io.state = {"active": False}
        return "cevap"

    s = PressSession(io, spoken.append, listen, follow_up_prob=0, log_dir=str(tmp_path / "logs"))
    end = time.time() + 3
    s.run(stop=lambda: time.time() > end)
    spoken = _speech(spoken)
    assert len(spoken) == 2 and spoken[0] == "ÜRETİLEN SORU"


def test_opening_spoken_first(tmp_path):
    st = dict(load_states()[0], active=True, ready=True)
    io = _FakeIO(st)
    spoken = []
    s = PressSession(io, spoken.append, lambda abort: "cevap", follow_up_prob=0, log_dir=str(tmp_path / "logs"))
    end = time.time() + 2
    s.run(stop=lambda: time.time() > end or s.answered)
    assert len(spoken) >= 2 and _speech(spoken[:1]) == [] and spoken[1] == "ÜRETİLEN SORU"


def test_no_follow_up_after_refusal_or_game_repeat(tmp_path):
    import press
    assert press.is_refusal("Yorum yok.")
    assert press.is_refusal("Cevap vermeyeceğim bu soruları arkadaşlar. Devam edelim.")
    assert press.is_refusal("Lütfen daha fazla üstüne gitmeyelim, sıradaki soruya geçelim.")
    assert not press.is_refusal("Takım çok iyi oynadı, galibiyeti hak ettik.")
    assert press.is_game_repeat({"game_question": "Sorumu yineliyorum: oyuncuların tutkusu ne kadar önemli?"})

    asked = []
    llm.set_mock(lambda p, t: {"question": "S", "event": "post_match"} if t == "question" else
                 asked.append(p) or {"category_index": 0, "option_index": 0, "display_text": "D", "follow_up": "Neden?"})
    st = dict(load_states()[0], active=True, ready=True)
    spoken = []
    s = PressSession(_FakeIO(st), spoken.append, lambda abort: "Yorum yok.", follow_up_prob=1,
                     log_dir=str(tmp_path / "logs"))
    s.handle(st)
    assert "Neden?" not in spoken and "follow_up: null" in asked[0]


def test_one_follow_up_per_journalist(tmp_path):
    llm.set_mock(lambda p, t: {"question": "S", "event": "post_match"} if t == "question" else
                 {"category_index": 0, "option_index": 0, "display_text": "D", "follow_up": "Neden?"})
    st = dict(load_states()[0], active=True, ready=True)
    io = _FakeIO(st)
    spoken = []
    s = PressSession(io, spoken.append, lambda abort: "Takım iyi oynadı.", follow_up_prob=1,
                     log_dir=str(tmp_path / "logs"))
    s.handle(st)
    st2 = dict(st, question_id="ikinci")
    io.state = st2
    s.handle(st2)
    assert spoken.count("Neden?") == 1


def test_voicebook_stable_and_distinct(tmp_path, monkeypatch):
    import voices
    monkeypatch.setenv("FM_VOICES_OFF", "-")     # tüm profiller açık (çakışmasızlık için yeterli ses)
    path = str(tmp_path / "map.json")
    vb = voices.VoiceBook(path)
    a = vb.for_journalist({"name": "Ertuğrul Yılmaz"})
    b = vb.for_journalist({"name": "Berkan Koç"})
    c = vb.for_journalist({"name": "Zeynep Kaya"})
    assert a["gender"] == "m" and b["gender"] == "m" and c["gender"] == "f"
    assert len({a["id"], b["id"], voices.moderator()["id"]}) == 3       # toplantıda çakışma yok
    assert vb.for_journalist({"name": "Ertuğrul Yılmaz"}) is a           # aynı toplantıda aynı ses
    vb2 = voices.VoiceBook(path)                                         # yeni oturum: aynı gazeteci aynı ses
    assert vb2.for_journalist({"name": "Ertuğrul Yılmaz"})["id"] == a["id"]


def test_voices_off_respected(tmp_path, monkeypatch):
    import voices
    monkeypatch.setenv("FM_VOICES_OFF", ",".join(p["id"] for p in voices.PROFILES if p["id"] != "emel"))
    vb = voices.VoiceBook(None)
    assert vb.for_journalist({"name": "Ayşe Demir"})["id"] == "emel"


def test_journalist_voice_used_for_question(tmp_path):
    st = dict(load_states()[0], active=True, ready=True)
    used = []

    def speaker(text, should_abort=None, profile=None):
        used.append((text, profile and profile["id"]))
    speaker.abortable = True
    speaker.voiced = True
    s = PressSession(_FakeIO(st), speaker, lambda abort: "cevap", follow_up_prob=0, log_dir=str(tmp_path / "logs"))
    s.handle(st)
    exp = s.voicebook.for_journalist(st["journalist"])["id"]
    assert used and used[0] == ("ÜRETİLEN SORU", exp)


def test_chirp_cap_blocks_before_request(tmp_path, monkeypatch):
    """0 TL garantisi: sınır dolunca Chirp'e HİÇ istek atılmaz."""
    import tts_chirp
    monkeypatch.setattr(C, "CHIRP_MONTHLY_CHARS", 100)
    monkeypatch.setattr(C, "CHIRP_DAILY_CHARS", 1000)
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "test-degil-gercek")
    calls = []
    monkeypatch.setattr(tts_chirp._http, "post", lambda *a, **k: calls.append(1) or (_ for _ in ()).throw(AssertionError("istek atıldı")))
    up = str(tmp_path / "usage.json")
    tts_chirp.reserve(90, up)
    with pytest.raises(tts_chirp.ChirpLimit):
        tts_chirp.synth("x" * 20, str(tmp_path / "a.mp3"), {"voice": "tr-TR-Chirp3-HD-Charon"}, usage_path=up)
    assert calls == []
    assert tts_chirp.usage(up)[0] == 90


def test_chirp_profiles_only_when_key(monkeypatch):
    import voices
    monkeypatch.delenv("GOOGLE_TTS_API_KEY", raising=False)
    monkeypatch.setattr(C, "GOOGLE_TTS_KEY", "")
    assert all(p.get("provider", "edge") == "edge" for p in voices.enabled())
    assert voices.moderator()["id"] == "ahmet"
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "test-degil-gercek")
    en = voices.enabled()
    assert en and all(p["provider"] == "chirp" for p in en)
    assert {p["gender"] for p in en} == {"m", "f"}
    assert voices.moderator()["provider"] == "chirp"


def test_device_selection():
    import devices
    apis = [{"name": "MME"}, {"name": "Windows DirectSound"}, {"name": "Windows WASAPI"}, {"name": "Windows WDM-KS"}]
    devs = [
        {"name": "Microsoft Sound Mapper - Input", "hostapi": 0, "max_input_channels": 2},
        {"name": "Mikrofon Dizisi (2- Realtek(R)", "hostapi": 0, "max_input_channels": 2},
        {"name": "Kulaklık Mikrofonu (HyperX Cloud", "hostapi": 0, "max_input_channels": 1},
        {"name": "Hoparlör (Realtek)", "hostapi": 0, "max_input_channels": 0},
        {"name": "Mikrofon Dizisi (2- Realtek(R) Audio)", "hostapi": 1, "max_input_channels": 2},
        {"name": "Kulaklık Mikrofonu (HyperX Cloud II)", "hostapi": 1, "max_input_channels": 1},
        {"name": "Kulaklık Mikrofonu (HyperX Cloud II)", "hostapi": 2, "max_input_channels": 1},
        {"name": "Mikrofon (Realtek HD Audio Mic input)", "hostapi": 3, "max_input_channels": 2},
    ]
    names = [n for _, n in devices.input_devices(devs, apis)]
    assert names == ["Mikrofon Dizisi (2- Realtek(R) Audio)", "Kulaklık Mikrofonu (HyperX Cloud II)"]  # tekrar yok, DirectSound
    assert devices.pick_input(devs, apis, "hyperx") == 5
    assert devices.pick_input(devs, apis, "4") == 4
    assert devices.pick_input(devs, apis, "yok böyle") is None
    assert devices.pick_input(devs, apis, "") is None
    outs = ["Hoparlör (2- Realtek(R) Audio)", "Kulaklık (HyperX Cloud II)"]
    assert devices.pick_output(outs, "kulaklık") == "Kulaklık (HyperX Cloud II)"
    assert devices.pick_output(outs, "0") == outs[0]
    assert devices.pick_output(outs, "yok") is None


def test_fan_voice_detected():
    import press
    for bad in ["aldığımız bu skor bizi gerçekten hayal kırıklığına uğrattı",
                "çıkan dokuz kart bizi çok üzdü",
                "maç genelindeki oyunumuzu ve aldığımız bu mağlubiyeti nasıl değerlendiriyorsunuz?",
                "Derbiyi kaybettik hocam, ne düşünüyorsunuz?"]:
        assert press.speaks_as_fan(bad), bad
    for ok in ["Hocam, takımınızın bugünkü performansını nasıl değerlendiriyorsunuz?",
               "Aldığınız bu sonuç sizi hayal kırıklığına uğrattı mı?",
               "Hocam merhaba, Berkan Koç, Habertürk. Dokuz kartlık bu sert maçı bekliyor muydunuz?"]:
        assert not press.speaks_as_fan(ok), ok


def test_fan_voice_rewritten(tmp_path):
    import press
    answers = iter([{"question": "Aldığımız skor bizi üzdü, ne diyorsunuz?", "event": "post_match"},
                    {"question": "Aldığınız skor sizi üzdü mü?", "event": "post_match"}])
    llm.set_mock(lambda p, t: next(answers))
    g = press.generate_question(load_states()[0])
    assert g["question"] == "Aldığınız skor sizi üzdü mü?"


def test_journalist_introduces_only_first_time(tmp_path):
    prompts = []
    llm.set_mock(lambda p, t: prompts.append(p) or ({"question": "S", "event": "post_match"} if t == "question" else
                 {"category_index": 0, "option_index": 0, "display_text": "D", "follow_up": None}))
    st = dict(load_states()[0], active=True, ready=True)
    io = _FakeIO(st)
    s = PressSession(io, lambda *a, **k: None, lambda abort: "cevap", follow_up_prob=0, log_dir=str(tmp_path / "logs"))
    s.handle(st)
    st2 = dict(st, question_id="ikinci")
    io.state = st2
    s.handle(st2)
    qp = [p for p in prompts if p.startswith("GOREV: SORU")]
    assert "İLK sorun" in qp[0] and "Kendini TANITMA" in qp[1]


def test_closing_audio_prepared_at_start(tmp_path):
    """Kapanış sesi toplantı başında hazırlanır; bitişte yeniden sentez yapılmaz."""
    st = dict(load_states()[0], active=True, ready=True)
    io = _FakeIO(st)
    prepared, played = [], []

    def speaker(text, should_abort=None, profile=None):
        played.append(("speak", text))
    speaker.abortable = speaker.voiced = True
    speaker.prepare = lambda text, prof=None: prepared.append(("q", text)) or "soru.mp3"
    speaker.prepare_cached = lambda text, prof=None: prepared.append(("sabit", text)) or f"sabit-{len(prepared)}.mp3"
    speaker.play = lambda path, abort=None: played.append(("play", path))

    def listen(abort):
        io.state = {"active": False}
        return "cevap"
    s = PressSession(io, speaker, listen, follow_up_prob=0, log_dir=str(tmp_path / "logs"))
    end = time.time() + 3
    s.run(stop=lambda: time.time() > end or s.closed)
    fixed = [t for k, t in prepared if k == "sabit"]
    assert len(fixed) == 2                                   # açılış + kapanış, ikisi de toplantı başında
    import closing
    assert fixed[1] in closing.CLOSINGS[st["screen"]] if st.get("screen") in closing.CLOSINGS else True
    assert played[-1][0] == "play" and played[-1][1].startswith("sabit-")   # kapanış hazır sesle çaldı


def test_tts_cache_reuses_file(tmp_path, monkeypatch):
    import voice
    monkeypatch.setattr(voice, "CACHE_DIR", str(tmp_path / "cache"))
    calls = []

    def fake_prepare(text, profile=None):
        calls.append(text)
        p = tmp_path / f"t{len(calls)}.mp3"
        p.write_bytes(b"ID3fake")
        return str(p)
    monkeypatch.setattr(voice, "prepare", fake_prepare)
    a = voice.prepare_cached("Teşekkürler hocam.", {"voice": "tr-TR-AhmetNeural"})
    b = voice.prepare_cached("Teşekkürler hocam.", {"voice": "tr-TR-AhmetNeural"})
    assert calls == ["Teşekkürler hocam."] and a != b and open(b, "rb").read() == b"ID3fake"


def test_tts_speed_applied(monkeypatch):
    import voice
    monkeypatch.setattr(C, "TTS_SPEED", 12)
    assert voice.effective({"voice": "tr-TR-AhmetNeural", "pitch": "+0Hz", "rate": "+0%"})["rate"] == "+12%"
    assert voice.effective({"voice": "tr-TR-AhmetNeural", "pitch": "+10Hz", "rate": "+8%"})["rate"] == "+20%"
    assert voice.effective({"provider": "chirp", "voice": "x", "speaking_rate": 1.0})["speaking_rate"] == 1.12
    monkeypatch.setattr(C, "TTS_SPEED", 0)
    assert voice.effective({"voice": "v", "pitch": "+0Hz", "rate": "-5%"})["rate"] == "-5%"


def test_gemini_hedged_fast_second_model(monkeypatch):
    """İlk model yavaşsa ikinciye paralel sorulur, ilk gelen cevap kullanılır (24 sn sıralı bekleme yok)."""
    monkeypatch.setattr(C, "GEMINI_KEY", "test")
    monkeypatch.setattr(C, "GEMINI_MODEL", "yavas")
    monkeypatch.setattr(C, "GEMINI_FALLBACK_MODELS", ["hizli", "ucuncu"])
    monkeypatch.setattr(C, "LLM_HEDGE_SEC", 0.3)
    monkeypatch.setattr(llm, "_cooldown", {})

    def one(model, prompt):
        if model == "yavas":
            time.sleep(3)
            return '{"m": "yavas"}'
        time.sleep(0.1)
        return '{"m": "%s"}' % model
    monkeypatch.setattr(llm, "_gemini_one", one)
    t = time.time()
    assert llm._gemini("p", time.time() + 5) == '{"m": "hizli"}'
    assert time.time() - t < 1.5


def test_gemini_deadline_and_errors(monkeypatch):
    monkeypatch.setattr(C, "GEMINI_KEY", "test")
    monkeypatch.setattr(C, "GEMINI_MODEL", "a")
    monkeypatch.setattr(C, "GEMINI_FALLBACK_MODELS", ["b"])
    monkeypatch.setattr(C, "LLM_HEDGE_SEC", 0.2)
    monkeypatch.setattr(llm, "_cooldown", {})

    def failing(model, prompt):
        raise llm.LLMError(f"{model}: HTTP 503")
    monkeypatch.setattr(llm, "_gemini_one", failing)
    with pytest.raises(llm.LLMError):
        llm._gemini("p", time.time() + 2)                      # hata verenler hızlıca biter

    def slow(model, prompt):
        time.sleep(5)
        return "{}"
    monkeypatch.setattr(llm, "_gemini_one", slow)
    t = time.time()
    with pytest.raises(llm.LLMError):
        llm._gemini("p", time.time() + 1)                      # süre sınırında vazgeçer
    assert time.time() - t < 2


def _match_rows():
    return [
        {"type": "start", "teams": "FB-GS"},
        {"type": "score", "t": "00:01", "s": "0 - 0"},
        {"type": "c", "t": "05:40", "s": "0 - 0", "x": "Greenwood kısa pas veriyor, Kanté orada"},
        {"type": "score", "t": "06:12", "s": "1 - 0"},
        {"type": "c", "t": "06:12", "s": "1 - 0", "x": "GOL! Muriqi kafa vuruşuyla ağları sarsıyor!"},
        {"type": "c", "t": "33:02", "s": "1 - 0", "x": "Osimhen'in şutu direkten dönüyor!"},
        {"type": "c", "t": "55:10", "s": "1 - 0", "x": "Yunus oyundan çıkıyor, yerine Barış Alper oyuna giriyor"},
        {"type": "snap", "t": "81:48", "mentality": "Aşırı Hücum Ağırlıklı", "items": [
            ["time", "81:48"], ["ClubHomeTeamText", "FB"], ["ClubAwayTeamText", "GS"],
            ["primary-text", "Fenerbahçe"],
            ["FormationView", "FB Diziliş (TS)"], ["Name", "Muriqi"], ["FormationView", "GS Diziliş (TS)"],
            ["ExpectedGoals", "2,77"], ["ExpectedGoals", "0,38"], ["Score", "1 - 0"],
            ["DugoutEvent0", "6"], ["DugoutEvent1", "55"],
            ["primary-text", "FENERBAHÇE"], ["", "Şut"], ["", "12"], ["", "Topla Oynama"], ["", "%50"],
            ["primary-text", "GALATASARAY"], ["", "Şut"], ["", "5"], ["", "Topla Oynama"], ["", "%50"],
            ["text", "8,5"], ["", "DKF"], ["Name", "Greenwood"], ["text", "6,1"], ["", "SB"], ["Name", "Jakobs"],
            ["text", "7,0"], ["", "MF"], ["Name", "Osimhen"]]},
        {"type": "end", "t": "90:00", "s": "1 - 0"},
    ]


def test_match_summary():
    import match
    s = match.summarize(_match_rows())
    assert s["skor"] == "1 - 0"
    assert s["goller"][0]["dakika"] == "6" and s["goller"][0]["golcu"] == "Muriqi (FB)"
    assert s["takimlar"] == "Fenerbahçe (FB) - Galatasaray (GS)"
    assert match.mark_manager_team(dict(s), "Fenerbahçe")["teknik_direktorun_takimi"] == "Galatasaray (GS)"
    assert any("direkten" in m for m in s["onemli_anlar"]) and any("oyuna giriyor" in m for m in s["onemli_anlar"])
    assert not any("kısa pas" in m for m in s["onemli_anlar"])
    assert s["xG"] == "FB 2,77 - GS 0,38" and s["istatistik"]["Şut"] == "FB 12 - GS 5"
    assert s["en_iyi_reytingler"][0] == "Greenwood (GS) 8,5" and s["en_dusuk_reytingler"][-1] == "Jakobs (GS) 6,1"
    assert s["son_mentalite"] == "Aşırı Hücum Ağırlıklı"


def test_match_summary_used_after_match(tmp_path, monkeypatch):
    import match
    f = tmp_path / "match_20261119_1600_FB-GS.jsonl"
    f.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in _match_rows()), encoding="utf-8")
    monkeypatch.setattr(match, "MATCH_DIR", str(tmp_path))
    prompts = []
    llm.set_mock(lambda p, t: prompts.append(p) or ({"question": "S", "event": "post_match"} if t == "question" else
                 {"category_index": 0, "option_index": 0, "display_text": "D", "follow_up": None}))
    st = dict(load_states()[0], active=True, ready=True, screen="post_match_tunnel_interview", match=None)
    s = PressSession(_FakeIO(st), lambda *a, **k: None, lambda abort: "cevap", follow_up_prob=0,
                     log_dir=str(tmp_path / "logs"))
    s.handle(st)
    assert "direkten" in prompts[0] and "2,77" in prompts[0]
    st2 = dict(st, screen="tunnel_interview", question_id="x2")                 # maç öncesi: GEÇEN maç olarak
    prompts.clear()
    s2 = PressSession(_FakeIO(st2), lambda *a, **k: None, lambda abort: "cevap", follow_up_prob=0,
                      log_dir=str(tmp_path / "logs2"))
    s2.handle(st2)
    assert "GECEN_MAC" in prompts[0] and "saha kenarı (TV)" in prompts[0]
    f.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in _match_rows()[:-1]), encoding="utf-8")
    assert match.previous_summary() is None                                     # bitmemiş (güncel) maç alınmaz


def test_goals_from_commentary_without_scorer():
    """Gerçek kayıt biçimi: 'GOL Galatasaray A.Ş.!!' (golcü yok); skor elemanı geç güncellenir."""
    import match
    rows = [{"type": "start", "teams": "FB-GS"},
            {"type": "c", "t": "02:01", "s": "0 - 0", "x": "Sallai topla güzel oynuyor, İsmail sadece"},
            {"type": "c", "t": "02:06", "s": "0 - 0", "x": "GOL Galatasaray A.Ş.!!"},
            {"type": "score", "t": "03:36", "s": "0 - 1"},
            {"type": "c", "t": "03:36", "s": "0 - 1", "x": "Sallai geliyor ve taç atışını kullanıyor"},
            {"type": "c", "t": "70:10", "s": "0 - 1", "x": "GOL Fenerbahçe A.Ş.!!"},
            {"type": "end", "t": "90:01", "s": "1 - 1"}]
    g = match.summarize(rows)["goller"]
    assert [(x["dakika"], x["takim"], x["golcu"]) for x in g] == [
        ("2", "Galatasaray", "bilinmiyor (tahmin etme)"), ("70", "Fenerbahçe", "bilinmiyor (tahmin etme)")]
    assert not any("Sallai" in str(x) for x in g)


def test_cleanup(tmp_path, monkeypatch):
    import cleanup
    bridge = tmp_path / "bridge"; (bridge / "matches").mkdir(parents=True)
    logs = tmp_path / "logs"; logs.mkdir()
    for i in range(5):
        f = bridge / "matches" / f"match_{i}.jsonl"; f.write_text("x" * 100); os.utime(f, (1000 + i, 1000 + i))
    old_dump = bridge / "20261101_120000"; old_dump.mkdir(); (old_dump / "ui_dump_1.txt").write_text("y" * 500)
    os.utime(old_dump, (1000, 1000))
    new_dump = bridge / "29991231_120000"; new_dump.mkdir()
    keep_other = bridge / "press_state.json"; keep_other.write_text("{}")
    monkeypatch.setattr(C, "BRIDGE_DIR", str(bridge))
    monkeypatch.setattr(cleanup, "LOG_DIR", str(logs))
    monkeypatch.setattr(cleanup, "KEEP_MATCHES", 2)
    monkeypatch.setattr(cleanup, "_stale_tts_cache", lambda: 0)
    freed = cleanup.run_all(verbose=False)
    assert sorted(os.listdir(bridge / "matches")) == ["match_3.jsonl", "match_4.jsonl"]
    assert not old_dump.exists() and new_dump.exists() and keep_other.exists()
    assert freed >= 300 + 500
