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
    assert s["goller"][0]["dakika"] == "7" and s["goller"][0]["golcu"] == "Muriqi (FB)"
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
    st = dict(load_states()[0], active=True, ready=True, screen="post_match_tunnel_interview", match=None,
              event_hint="post_match")                                 # eklenti panelle birlikte gönderir
    s = PressSession(_FakeIO(st), lambda *a, **k: None, lambda abort: "cevap", follow_up_prob=0,
                     log_dir=str(tmp_path / "logs"))
    s.handle(st)
    assert "direkten" in prompts[0] and "Rakip sizden fazla şut çekti (rakip 12, siz 5)" in prompts[0] and "2,77" not in prompts[0]
    st2 = dict(st, screen="tunnel_interview", question_id="x2", opponent="Trabzonspor", event_hint="pre_match")  # maç öncesi: GEÇEN maç
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
        ("3", "Galatasaray", "bilinmiyor (tahmin etme)"), ("71", "Fenerbahçe", "bilinmiyor (tahmin etme)")]
    assert not any("Sallai" in str(x) for x in g)


def _derby_rows():
    """Gerçek kayıttan (2026-11-21, FB 2-1 GS): tabela 19' Muriqi, 34' Osimhen, 77' Mert Müldür."""
    return [{"type": "start", "teams": "FB-GS"},
            {"type": "c", "t": "18:30", "s": "", "x": "GOL Fenerbahçe A.Ş.!!"},
            {"type": "c", "t": "33:09", "s": "", "x": "GOL Galatasaray A.Ş.!!"},
            {"type": "c", "t": "34:30", "s": "", "x": "Ama Asensio topu direğin hemen üstünden dışarı attı!"},
            {"type": "c", "t": "40:10", "s": "", "x": "Osimhen'in şutu direkten dönüyor!"},
            {"type": "c", "t": "46:02", "s": "", "x": "Leão, Semedo'dan kaçtı"},
            {"type": "c", "t": "60:00", "s": "", "x": "Hakem penaltı noktasını gösterdi! Asensio yerde kaldı"},
            {"type": "c", "t": "76:40", "s": "", "x": "GOL Fenerbahçe A.Ş.!!"},
            {"type": "snap", "t": "90:00", "items": [
                ["ClubHomeTeamText", "FB"], ["ClubAwayTeamText", "GS"],
                ["FormationView", "GS Diziliş (TS)"], ["Name", "Osimhen"], ["Name", "Rafa Leão"],
                ["FormationView", "FB Diziliş (TS)"], ["Name", "Asensio"], ["Name", "Semedo"],
                ["primary-text", "FENERBAHÇE"], ["", "Şut"], ["", "11"],
                ["primary-text", "GALATASARAY"], ["", "Şut"], ["", "9"]]},
            {"type": "end", "t": "90:00", "s": "2 - 1"}]


def test_goal_minutes_match_scoreboard():
    """Anlatım saati 18:30 -> tabelada 19'. Soru tabeladaki dakikayı kullanmalı."""
    import match
    g = match.summarize(_derby_rows())["goller"]
    assert [x["dakika"] for x in g] == ["19", "34", "77"]


def test_manager_perspective_goals_and_moments():
    """Rakibin golü teknik direktöre mal edilmesin; rakibin sıradan pozisyonu sorulmasın, tartışmalı olanı kalsın."""
    import match
    s = match.mark_manager_team(match.summarize(_derby_rows()), None, my_team="Galatasaray")
    assert s["teknik_direktorun_takimi"] == "Galatasaray (GS)"
    kim = [(g["dakika"], g["kimin_golu"]) for g in s["goller"]]
    assert kim[0][0] == "19" and "RAKİP" in kim[0][1]
    assert kim[1][0] == "34" and "RAKİP" not in kim[1][1]
    anlar = " ".join(s["onemli_anlar"])
    assert "Osimhen" in anlar and "Leão" in anlar          # kendi takımının pozisyonları
    assert "Asensio" not in anlar                          # rakibin sıradan kaçan fırsatı yok
    assert "GOL" not in anlar                              # goller ayrı listede, tekrar yok (yanlış sahiplenme)
    assert any("penaltı" in m for m in s["rakip_tartismali_anlar"])
    assert s["sonuc_teknik_direktor_icin"] == "MAĞLUBİYET: Galatasaray 1 - 2 Fenerbahçe"
    assert [g["bu_golden_sonra"] for g in s["goller"]] == [         # LLM ara skoru kendi hesaplayıp "farkı ikiye çıkardı" diyordu
        "Galatasaray 0 - 1 Fenerbahçe", "Galatasaray 1 - 1 Fenerbahçe", "Galatasaray 1 - 2 Fenerbahçe"]
    assert "Rakip sizden fazla şut çekti (rakip 11, siz 9)" in s["istatistik_cumleleri"] and "xG" not in s
    assert s["teknik_direktorun_takimi_sahasi"] == "deplasman"
    # rakip adıyla da aynı sonuç
    s2 = match.mark_manager_team(match.summarize(_derby_rows()), "Fenerbahçe")
    assert s2["teknik_direktorun_takimi"] == "Galatasaray (GS)" and "RAKİP" in s2["goller"][0]["kimin_golu"]


def test_screen_text_drops_noise_panels():
    """Maç sonu ekran kaydındaki portal/röportaj panelleri LLM'e gitmesin (röportaj seçeneğinden 'özür' uyduruyordu)."""
    import match
    rows = _derby_rows() + [{"type": "screen", "where": "mac_sonu_ekrani", "panels": {
        "PortalScreen": [["", "Mevcut Bütçe"], ["", "€6,28M"]],
        "PostMatchTunnelInterviewPanel": [["text", "Taraftarlarımızdan özür diliyorum"]],
        "MatchStatsPanel": [["", "Muriqi 19'"], ["", "Osimhen 34'"]]}}]
    t = match.summarize(rows)["mac_sonu_ekrani_metni"]
    assert "Muriqi" in t and "Bütçe" not in t and "özür" not in t
    multi = _derby_rows() + [                                   # v0.4.2: düdük sonrası birden çok çekim birleşir
        {"type": "screen", "where": "mac_sonu_ekrani_1", "panels": {"OverviewPrototype": [["", "V. Muriqi 19'"]]}},
        {"type": "screen", "where": "mac_sonu_ekrani_2", "panels": {"MatchStatsPanel": [["", "Topla Oynama"]],
                                                                    "PostMatchTunnelInterviewPanel": [["", "özür"]]}}]
    t2 = match.summarize(multi)["mac_sonu_ekrani_metni"]
    assert "Muriqi 19'" in t2 and "Topla Oynama" in t2 and "özür" not in t2
    only_noise = _derby_rows() + [{"type": "screen", "where": "mac_sonu_ekrani",
                                   "panels": {"PortalScreen": [["", "Mevcut Bütçe"]]}}]
    assert "mac_sonu_ekrani_metni" not in match.summarize(only_noise)


def test_manager_team_from_squad_list_without_opponent():
    """Rakip adı da öğrenilmiş takım da yoksa: maç ekranındaki 'Kadro' listesi teknik direktörün kendi kadrosudur."""
    import match
    rows = _derby_rows()
    rows.insert(1, {"type": "snap", "t": "00:04", "items": [
        ["text", "Kadro"], ["text", "5/5 Yedek"], ["text", "KL"],
        ["fm-tactics-shirt-number", "45"], ["text", "Osimhen"], ["text", "6,6"], ["text", "Normal"],
        ["fm-tactics-shirt-number", "27"], ["text", "Rafa Leão"], ["text", "6,6"]]})
    s = match.mark_manager_team(match.summarize(rows), None)
    assert s["teknik_direktorun_takimi"] == "Galatasaray (GS)"
    assert "RAKİP" in s["goller"][0]["kimin_golu"]
    assert not any(k.startswith("_") for k in s)
    # LLM ilk 11'i bilmeyince "Yunus bugün sahada yoktu" diye uyduruyordu
    assert s["teknik_direktorun_ilk_11"] == ["Osimhen", "Rafa Leão"]
    assert "oyundan_alinanlar" not in s                    # ikisi de son dizilişte var


def test_substituted_starters_listed():
    import match
    rows = [{"type": "start", "teams": "FB-GS"},
            {"type": "snap", "t": "00:04", "items": [["text", "Kadro"],
                ["fm-tactics-shirt-number", "11"], ["text", "Yunus"], ["fm-tactics-shirt-number", "45"], ["text", "Osimhen"],
                ["fm-tactics-shirt-number", "4"], ["text", "Jakobs"]]},
            {"type": "snap", "t": "90:00", "items": [["ClubHomeTeamText", "FB"], ["ClubAwayTeamText", "GS"],
                ["FormationView", "GS Diziliş (TS)"], ["Name", "Osimhen"], ["Name", "Barış Alper"], ["Name", "Eren Elmalı"],
                ["FormationView", "FB Diziliş (TS)"], ["Name", "Asensio"], ["Name", "Kanté"],
                ["primary-text", "FENERBAHÇE"], ["primary-text", "GALATASARAY"]]},
            {"type": "end", "t": "90:00", "s": "1 - 0"}]
    s = match.mark_manager_team(match.summarize(rows), "Fenerbahçe")
    assert s["teknik_direktorun_ilk_11"] == ["Yunus", "Osimhen", "Jakobs"]
    assert s["oyundan_alinanlar"] == ["Yunus", "Jakobs"]
    assert not any(k.startswith("_") for k in s)


def test_game_stat_numbers_rewritten():
    """Gerçek muhabir FM reytingi / xG söylemez: böyle bir soru bir kez yeniden yazdırılır."""
    assert press.cites_game_stats("Sallai 6,2 reytingle oynadı. Neden oyunda tuttunuz?")
    assert press.cites_game_stats("xG üstünlüğüne rağmen kaybettiniz.")
    assert not press.cites_game_stats("77. dakikada yediğiniz golle 1-2 kaybettiniz. Ne diyorsunuz?")
    assert not press.cites_game_stats("Kulüp 2,5 milyon euroluk teklifi reddetti. Oyuncu kalacak mı?")
    answers = iter([{"question": "Sallai 6,2 puanla en düşük notu aldı. Neden oyunda tuttunuz?", "event": "post_match"},
                    {"question": "Sallai bugün etkisizdi. Onu neden oyunda tuttunuz?", "event": "post_match"}])
    llm.set_mock(lambda p, t: next(answers))
    r = press.generate_question({"game_question": "Sallai neden oyundaydı?", "screen": "press_conference"}, None, [])
    assert r["question"] == "Sallai bugün etkisizdi. Onu neden oyunda tuttunuz?"


def test_provider_hedge(monkeypatch):
    """Ana sağlayıcı (Gemini) yavaşsa LLM_HEDGE_SEC sonra ikinciye (Groq) de sorulur, ilk gelen kullanılır;
    ana sağlayıcı hızlıysa ikinci hiç çağrılmaz."""
    calls = []
    def slow_gemini(p, d):
        calls.append("gemini"); time.sleep(1.5); return '{"question": "G"}'
    def fast_groq(p, d):
        calls.append("openai"); return '{"question": "Q"}'
    monkeypatch.setattr(C, "PROVIDERS", ["gemini", "openai"])
    monkeypatch.setattr(C, "LLM_HEDGE_SEC", 0.3)
    monkeypatch.setattr(llm, "_gemini", slow_gemini)
    monkeypatch.setattr(llm, "_openai", fast_groq)
    t = time.time()
    assert llm.ask("p", budget=5)["question"] == "Q" and time.time() - t < 1.2
    calls.clear()
    monkeypatch.setattr(llm, "_gemini", lambda p, d: calls.append("gemini") or '{"question": "G"}')
    assert llm.ask("p", budget=5)["question"] == "G" and calls == ["gemini"]
    calls.clear()                                                     # ana sağlayıcı hata verirse hemen ikinci
    def bad(p, d):
        calls.append("gemini"); raise llm.LLMError("503")
    monkeypatch.setattr(llm, "_gemini", bad)
    t = time.time()
    assert llm.ask("p", budget=5)["question"] == "Q" and time.time() - t < 0.3


def _table_items(rows_):
    out = []
    for rank, team, played, pts in rows_:
        out += [["", str(rank)], ["primary-text", team], ["SIText", f"{played} Maç"], ["", f"{pts} Pua"]]
    return out


def test_standings_from_live_table():
    """Maç ekranındaki canlı tablo (gerçek kayıt biçimi): maç sonu sıralaması ve aynı anda oynanan maçlar."""
    import match
    rows = _derby_rows()
    rows.insert(-1, {"type": "snap", "t": "90:00", "items": [
        ["ClubHomeTeamText", "FB"], ["ClubAwayTeamText", "GS"],
        ["primary-text", "Çaykur Rizespor"], ["primary-text", "1 - 2"], ["primary-text", "Samsunspor"],
        ["primary-text", "Fenerbahçe"], ["primary-text", "2 - 1"], ["primary-text", "Galatasaray"],
        ["primary-text", "Tümosan Konyaspor"], ["primary-text", "1 - 1"], ["primary-text", "Gaziantep FK"],
        *_table_items([(1, "Samsunspor", 3, 7), (2, "Corendon Alanyaspor", 2, 6), (3, "Göztepe", 2, 6),
                       (4, "Galatasaray", 3, 6), (5, "Çorum FK", 2, 4)]),
        ["primary-text", "FENERBAHÇE"], ["primary-text", "GALATASARAY"]]})
    s = match.mark_manager_team(match.summarize(rows), "Fenerbahçe")
    assert s["puan_durumu"] == ("Maç sonu canlı tabloya göre Galatasaray 4. sırada (3 maçta 6 puan). "
                                "Lider Samsunspor 7 puan, fark 1 puan.")
    assert s["ayni_anda_oynanan_maclar"] == ["Çaykur Rizespor 1 - 2 Samsunspor", "Tümosan Konyaspor 1 - 1 Gaziantep FK"]


def test_standings_leader_and_absent():
    import match
    leader = match._standings_sentence([(1, "Galatasaray", 3, 9), (2, "Samsunspor", 3, 7)], "Galatasaray (GS)")
    assert leader == "Maç sonu canlı tabloya göre Galatasaray lider (3 maçta 9 puan). En yakın takipçi Samsunspor 7 puan, fark 2 puan."
    assert match._standings_sentence([(1, "Samsunspor", 3, 7)], "Galatasaray (GS)") is None   # görünen satırlarda yok


def test_meeting_kind_from_game_question():
    """Basın toplantısı paneli maç öncesi/sonu ayırmıyor: oyunun sorusu ayırır."""
    assert press.meeting_kind("Yarınki Trabzonspor maçı öncesi kadroda eksik var mı?") == "pre"
    assert press.meeting_kind("Hafta sonu zorlu bir deplasmana gideceksiniz. Hazırlıklar nasıl gidiyor?") == "pre"
    assert press.meeting_kind("Önemli bir derbiyi kaybettiniz, duygularınızı paylaşır mısınız?") == "post"
    assert press.meeting_kind("Bugünkü sonuç sizi tatmin etti mi?") == "post"
    assert press.meeting_kind("Yunus Akgün rekabete yabancı değil. Tutku ne kadar önemli?") is None


def test_pre_match_press_conference_uses_previous_match(tmp_path, monkeypatch):
    """Maç oynandıktan sonra bir sonraki maçın ÖNCESİNDEKİ basın toplantısı: biten maç 'geçen maç' olarak gider,
    maç sonu toplantısı gibi sorulmaz (eskiden son 2 saatteki maç 'bugünkü maç' sayılıyordu)."""
    import match
    f = tmp_path / "match_20261121_2227_FB-GS.jsonl"
    f.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in _derby_rows()), encoding="utf-8")
    monkeypatch.setattr(match, "MATCH_DIR", str(tmp_path))
    prompts = []
    llm.set_mock(lambda p, t: prompts.append(p) or ({"question": "S", "event": "pre_match"} if t == "question" else
                 {"category_index": 0, "option_index": 0, "display_text": "D", "follow_up": None}))
    st = dict(load_states()[0], active=True, ready=True, screen="press_conference", match=None, opponent=None,
              event_hint=None, game_question="Yarınki Gençlerbirliği maçı öncesi sakat oyuncularınızın durumu ne?")
    s = PressSession(_FakeIO(st), lambda *a, **k: None, lambda abort: "cevap", follow_up_prob=0,
                     log_dir=str(tmp_path / "logs"))
    s.handle(st)
    assert "GECEN_MAC" in prompts[0] and "Maç öncesi:" in prompts[0] and "TOPLANTI AKIŞI" not in prompts[0]
    st2 = dict(st, question_id="q2", game_question="Taraftarlar bu sezon için umutlu. Siz ne düşünüyorsunuz?")
    s.io = _FakeIO(st2)
    prompts.clear()
    s.handle(st2)                                                    # karar toplantı boyunca hatırlanır
    assert "GECEN_MAC" in prompts[0]


def test_style_by_event():
    """Her etkinlik kendi gerçek soru kalıplarını alır: maç sonu flaş röportajı basın toplantısından ayrı."""
    seen = {}
    llm.set_mock(lambda p, t: seen.setdefault("p", p) and {"question": "S", "event": "post_match"})
    for screen, marker in [("post_match_tunnel_interview", "saha kenarı (TV/flaş)"),
                           ("press_conference", "TOPLANTI AKIŞI"), ("tunnel_interview", "Maç öncesi saha kenarı")]:
        seen.clear()
        press.generate_question({"game_question": "Maç nasıldı?", "screen": screen}, {"skor": "1 - 0"}, [])
        assert marker in seen["p"], screen


def test_dotless_i_team_names():
    """'KASIMPAŞA'.title() -> 'Kasimpaşa' ama anlatım 'Kasımpaşa' yazar: kendi golü rakibe yazılmamalı."""
    import match
    s = {"takimlar": "Kasimpaşa (KAS) - Galatasaray (GS)", "skor": "1 - 0",
         "goller": [{"dakika": "10", "takim": "Kasımpaşa", "golcu": "bilinmiyor (tahmin etme)"}]}
    s = match.mark_manager_team(s, "Galatasaray")
    assert s["teknik_direktorun_takimi"] == "Kasimpaşa (KAS)"
    assert s["goller"][0]["kimin_golu"] == "teknik direktörün takımı attı"


def test_previous_summary_skips_replayed_fixture(tmp_path, monkeypatch):
    """Kaydedilmeden tekrar oynanan maç: son kayıt aynı rakibe karşıysa 'geçen maç' sayılmaz."""
    import match
    f = tmp_path / "match_20261119_1600_FB-GS.jsonl"
    f.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in _derby_rows()), encoding="utf-8")
    monkeypatch.setattr(match, "MATCH_DIR", str(tmp_path))
    assert match.previous_summary(opponent="Fenerbahçe") is None
    assert match.previous_summary(opponent="Trabzonspor")["skor"] == "2 - 1"


def test_press_conference_without_opponent_uses_learned_team(tmp_path, monkeypatch):
    """Basın toplantısında rakip adı gelmiyor: önceki röportajdan öğrenilen takım kullanılmalı."""
    import match
    f = tmp_path / "match_20261121_2227_FB-GS.jsonl"
    f.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in _derby_rows()), encoding="utf-8")
    monkeypatch.setattr(match, "MATCH_DIR", str(tmp_path))
    prompts = []
    llm.set_mock(lambda p, t: prompts.append(p) or ({"question": "S", "event": "post_match"} if t == "question" else
                 {"category_index": 0, "option_index": 0, "display_text": "D", "follow_up": None}))
    st = dict(load_states()[0], active=True, ready=True, screen="post_match_tunnel_interview", match=None,
              opponent="Fenerbahçe")
    s = PressSession(_FakeIO(st), lambda *a, **k: None, lambda abort: "cevap", follow_up_prob=0,
                     log_dir=str(tmp_path / "logs"))
    s.handle(st)
    st2 = dict(st, screen="press_conference", opponent=None, question_id="pc1", event_hint=None)
    s.io = _FakeIO(st2)
    prompts.clear()
    s.handle(st2)
    assert '"teknik_direktorun_takimi": "Galatasaray (GS)"' in prompts[0]


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


def test_name_hint():
    st = {"opponent": "Fenerbahçe", "competition": "Trendyol Süper Lig", "journalist": {"name": "Berkan Koç"}}
    h = PressSession._name_hint(st, "Hocam, Osimhen'in 40. dakikadaki fırsatı...", {"onemli_anlar": ["89' Uğurcan (GS) kurtardı"]})
    for w in ("Fenerbahçe", "Berkan", "Osimhen", "Uğurcan"):
        assert w in h
    assert "Hocam" not in h


def test_name_hint_structured():
    """İpucu maç verisinin rastgele büyük harfli kelimelerinden değil, isim alanlarından kurulur (2026-11-21: 'RAKİP,
    Kurtarıyor, Sadece, Artık' ipucunu doldurup oyuncu adlarını dışarıda bırakıyordu; WER %27,8 -> %19,3)."""
    import match
    s = match.mark_manager_team(match.summarize(_derby_rows()), "Fenerbahçe")
    s["puan_durumu"] = "Maç sonu canlı tabloya göre Galatasaray 4. sırada (3 maçta 6 puan). Lider Samsunspor 7 puan, fark 1 puan."
    s["ayni_anda_oynanan_maclar"] = ["Çaykur Rizespor 1 - 2 Samsunspor"]
    st = {"opponent": "Fenerbahçe", "competition": "Trendyol Süper Lig", "journalist": {"name": "Berkan Koç"}}
    h = PressSession._name_hint(st, "Hocam, maçı nasıl değerlendiriyorsunuz?", {"GECEN_MAC (bugünkü maç DEĞİL)": s})
    for w in ("Galatasaray", "Fenerbahçe", "Samsunspor", "Çaykur Rizespor", "Berkan Koç", "Osimhen", "Asensio"):
        assert w in h, w
    for junk in ("RAKİP", "Rakip", "Maç sonu", "Lider", "Hocam", "MAĞLUBİYET"):
        assert junk not in h, junk


def test_stt_groq_then_local_fallback(monkeypatch):
    """Groq anahtarı varsa Groq Whisper (testte WER %9, 0,8 sn); hata/zaman aşımında yerel modele düşer."""
    import numpy as np
    import voice
    sent = {}
    class R:
        status_code = 200
        def json(self):
            return {"text": " Golü Fenerbahçe attı. "}
    def fake_post(url, headers=None, files=None, data=None, timeout=None):
        sent.update(url=url, data=data, auth="Authorization" in headers)
        return R()
    monkeypatch.setattr(C, "STT_PROVIDER", "groq")
    monkeypatch.setattr(C, "OPENAI_KEY", "test")
    monkeypatch.setattr(voice.requests, "post", fake_post)
    monkeypatch.setattr(voice, "_transcribe_local", lambda a, p: "YEREL")
    voice.set_hint("Galatasaray, Fenerbahçe")
    audio = np.zeros(16000, dtype=np.float32)
    assert voice.transcribe(audio) == "Golü Fenerbahçe attı."
    assert sent["data"]["model"] == "whisper-large-v3-turbo" and sent["data"]["language"] == "tr"
    assert "Galatasaray" in sent["data"]["prompt"] and "Gol" in sent["data"]["prompt"] and sent["auth"]
    def boom(*a, **k):
        raise voice.requests.ConnectionError("internet yok")
    monkeypatch.setattr(voice.requests, "post", boom)
    assert voice.transcribe(audio) == "YEREL"
    monkeypatch.setattr(C, "STT_PROVIDER", "local")
    monkeypatch.setattr(voice.requests, "post", fake_post)
    assert voice.transcribe(audio) == "YEREL"


def test_display_text_never_adds_words():
    """Ekrana yazılan cevap teknik direktöre söylemediği sözü atfetmemeli (2026-11-21 log'u: seçenek cümlesi eklendi)."""
    said = "Önemli bir gol tabii ki ama günün sonunda bizim için kazanmaya yetmedi. Başka bir yolun yok."
    bad = ("Önemli bir gol, ancak maçı kazanmak için yeterli olmadı. Fenerbahçe'yi tebrik ediyorum; kaybetmiş olsak "
           "bile sahada güzel şeyler yaptık.")
    assert press.adds_content(said, bad)
    assert not press.adds_content(said, "Önemli bir gol tabii ki, ama günün sonunda kazanmaya yetmedi. Başka yolu yok.")
    assert not press.adds_content("Bak on dokuzda golü Sıfener bahçı attı biz atmadık",       # duyma hatası düzeltmesi
                                  "Bak, 19. dakikadaki golü Fenerbahçe attı, biz atmadık.")
    st = load_states()[0]
    llm.set_mock(lambda p, t: {"category_index": st["categories"][0]["index"], "option_index": 0,
                               "display_text": bad, "follow_up": None})
    r = press.classify_answer(st, "Soru?", "ııı " + said)
    assert "tebrik" not in r["display_text"] and r["display_text"].startswith("Önemli bir gol")


def test_settings_ini(tmp_path, monkeypatch):
    import settings
    f = tmp_path / "settings.ini"
    f.write_text("\n".join(["[genel]", "bas_konus_tusu = f9", "mikrofon = HyperX", "[gizli]",
                            "gemini_api_key = AQ.sahte", ""]), encoding="utf-8")
    for k in ("FM_HOTKEY", "FM_MIC"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FM_MIC", "Ortam")                       # ortam değişkeni kazanır
    w = settings.load(str(f))
    assert os.environ["FM_HOTKEY"] == "f9" and os.environ["FM_MIC"] == "Ortam"
    assert any("gemini_api_key" in x for x in w) and "AQ.sahte" not in os.environ.values()
