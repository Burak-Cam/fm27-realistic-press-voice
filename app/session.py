"""Canlı köprü döngüsü: press_state.json'u izler, her yeni soru için soru üret -> oku -> dinle -> sınıflandır -> uygula."""
import json
import os
import random
import threading
import time
from datetime import datetime

import closing
import match as match_log
import config as C
import press
import status
import voices
from bridge import BridgeIO


class _Debounce:
    """Koşul en az `hold` saniye kesintisiz doğruysa True (tek seferlik okuma hatası iptal ettirmesin)."""

    def __init__(self, cond, hold: float):
        self.cond, self.hold, self.since = cond, hold, None

    def __call__(self) -> bool:
        if not self.cond():
            self.since = None
            return False
        now = time.time()
        if self.since is None:
            self.since = now
        return now - self.since >= self.hold


class PressSession:
    def __init__(self, io: BridgeIO, speak, listen, match: dict | None = None,
                 follow_up_prob: float | None = None, log_dir: str | None = None, max_questions: int | None = None):
        self.io, self.speak, self.listen = io, speak, listen
        self.match = match
        self.manager_team: str | None = None   # röportajdaki rakip adından öğrenilir; basın toplantısında rakip gelmiyor
        self.meeting_kind: str | None = None   # basın toplantısı "pre"/"post" (oyunun sorusundan; toplantı başında sıfırlanır)
        self.follow_up_prob = C.FOLLOW_UP_PROB if follow_up_prob is None else follow_up_prob
        self.history: list[dict] = []
        self.handled: set[str] = set()
        self.log_dir = log_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
        self.max_questions = max_questions
        self.answered = 0
        self.seen = 0              # bu toplantıda görülen soru sayısı
        self.fu_asked: set[str] = set()   # bu toplantıda takip sorusu sorulmuş gazeteciler
        self.introduced: set[str] = set() # bu toplantıda kendini tanıtmış gazeteciler
        self._opening = None       # açılış cümlesini okuyan arka plan iş parçacığı
        self._closing_line = self._closing_audio = self._closing_prof = None
        self.voicebook = voices.VoiceBook(os.path.join(self.log_dir, "voices_map.json"))
        self.closed = False        # kapanış cümlesi söylendi mi
        self._last_st = None
        self._closing_qid, self._closing_since = None, 0.0

    # ---------------------------------------------------------------
    def run(self, stop=lambda: False):
        print(f"Köprü klasörü: {self.io.dir}\nBasın ekranı bekleniyor... (Ctrl+C ile çık)")
        was_active = False
        while not stop():
            st = self.io.read_state()
            active = bool(st and st.get("active"))
            if active and not was_active:
                self.seen, self.closed = 0, False
                self.meeting_kind = None
                self.fu_asked = set()
                self.introduced = set()
                self.voicebook.new_conference()
                reset = getattr(self.speak, "reset", None)
                if reset:
                    reset()                                  # çıkış cihazı yeniden seçilsin
                self._open(st)
            if was_active and not active:
                if self.seen and not self.closed and self._last_st:
                    self._close(self._last_st, on_screen=False)      # oyun kapanış balonu göstermeden kapandı
                self._end_conference()
            was_active = active
            if active:
                self._last_st = st
            if active and self.seen and not self.closed and self._closing_bubble(st):
                self._close(st, on_screen=True)
            if active and st.get("ready") and st.get("question_id") not in self.handled:
                self.handled.add(st["question_id"])
                self.seen += 1
                try:
                    self.handle(st)
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    print(f"  [hata] soru işlenemedi: {e!r}")
                if self.max_questions and self.answered >= self.max_questions:
                    break
            time.sleep(C.POLL_SEC)
        if self.history:
            self._end_conference()

    # ---------------------------------------------------------------
    def _closing_bubble(self, st: dict) -> bool:
        """Oyunun kapanış balonu ("Çok teşekkürler." gibi): metin var, cevap seçeneği yok, 1,2 sn değişmeden duruyor."""
        has_options = any(c.get("options") for c in (st.get("categories") or []))
        if st.get("ready") or has_options or not st.get("game_question"):
            self._closing_qid = None
            return False
        if st.get("question_id") != self._closing_qid:
            self._closing_qid, self._closing_since = st.get("question_id"), time.time()
            return False
        return time.time() - self._closing_since >= 0.6

    def _prepare_fixed(self, text: str, prof: dict | None):
        """Sabit cümle (açılış/kapanış): önbellekli hazırla; desteklemeyen konuşucuda normal hazırla."""
        pc = getattr(self.speak, "prepare_cached", None)
        if pc and getattr(self.speak, "voiced", False):
            return pc(text, prof)
        return self._prepare(text, prof)

    def _open(self, st: dict):
        """Ekrana girer girmez açılış cümlesi; ilk soru hazırlanırken arka planda okunur (soruyu geciktirmez).
        Aynı anda kapanış cümlesi seçilip sesi hazırlanır: toplantı bitince beklemeden çalar."""
        line = closing.make_opening(st.get("screen"), st.get("event_hint"),
                                    os.path.join(self.log_dir, "opening_recent.json"))
        prof = self._host_voice(st)
        print(f"\n  Açılış [{prof['id']}]: {line}")
        status.set("speaking", "Toplantı başlıyor...")
        self._closing_line = closing.make(st.get("screen"), None, os.path.join(self.log_dir, "closing_recent.json"))
        self._closing_prof = prof
        self._closing_audio = None

        def run():
            try:
                self._play_now(self._prepare_fixed(line, prof), line, None, prof)
            except Exception as e:
                print(f"  [açılış] okunamadı: {e!r}")
            try:
                self._closing_audio = self._prepare_fixed(self._closing_line, prof)   # kapanış sesi şimdiden hazır
            except Exception as e:
                print(f"  [kapanış] hazırlanamadı: {e!r}")
        self._opening = threading.Thread(target=run, daemon=True)
        self._opening.start()

    def _wait_opening(self):
        if self._opening is not None:
            self._opening.join(timeout=15)
            self._opening = None

    def _close(self, st: dict, on_screen: bool):
        """Gazeteci teşekkür edip toplantıyı kapatır (her seferinde farklı cümle)."""
        self.closed = True
        line, prof, audio = getattr(self, "_closing_line", None), getattr(self, "_closing_prof", None), None
        if line:
            self._wait_opening()                        # açılış iş parçacığı kapanış sesini de hazırlıyor
            audio = self._closing_audio
        else:                                           # açılış görülmeden kapanış (olağan dışı)
            line = closing.make(st.get("screen"), None, os.path.join(self.log_dir, "closing_recent.json"))
            prof = self._host_voice(st)
            audio = self._prepare_fixed(line, prof)
        self._closing_line = self._closing_audio = None
        print(f"\n  Kapanış [{prof['id'] if prof else '?'}]: {line}")
        if on_screen and C.REPLACE_QUESTION and st.get("question_id"):
            self.io.write_question(st["question_id"], line)     # oyunun kapanış balonunda da bizim cümle yazsın
        status.set("speaking", "Gazeteci toplantıyı kapatıyor...")
        self._play(audio, line, None, prof)
        status.set("idle", "Toplantı bitti")

    def _host_voice(self, st: dict) -> dict:
        """Basın toplantısını moderatör açar/kapatır; saha kenarı röportajında gazetecinin kendisi."""
        if st.get("screen") == "press_conference" or not st.get("journalist"):
            return voices.moderator()
        return self.voicebook.for_journalist(st.get("journalist"))

    @staticmethod
    def _name_hint(st: dict, question: str, match: dict | None) -> str:
        """Whisper ipucu: takımlar, oyuncular, gazeteci ve sorudaki özel isimler (tekrarsız). Maç verisinin tamamı
        taranmaz: hazır cümlelerdeki büyük harfli kelimeler ("Rakip", "Maç", "Lider") ipucunu doldurup oyuncu
        adlarını dışarıda bırakıyordu (2026-11-21 ölçümü: WER %27,8 -> %19,3)."""
        import re as _re
        if match and len(match) == 1 and str(next(iter(match))).startswith("GECEN_MAC"):
            match = next(iter(match.values()))                     # maç öncesi: geçen maçın özeti iç içe
        match = match or {}
        names: list[str] = []
        add = lambda *xs: names.extend(x.strip() for x in xs if x and x.strip())
        teams = [t.split(" (")[0] for t in (match.get("takimlar") or "").split(" - ") if " (" in t]
        add(*teams, st.get("opponent"), (st.get("journalist") or {}).get("name"))
        for line in match.get("ayni_anda_oynanan_maclar", []):    # "Çaykur Rizespor 1 - 2 Samsunspor"
            add(*_re.split(r"\s+\d+ - \d+\s+", line))
        for m in _re.finditer(r"(?:Lider|takipçi) (.+?) \d+ puan", match.get("puan_durumu") or ""):
            add(m.group(1))
        add(*match.get("teknik_direktorun_ilk_11", []))
        player = r"([A-ZÇĞİÖŞÜ][\wçğıöşüéáíóãñ'.-]+(?: [A-ZÇĞİÖŞÜ][\wçğıöşüéáíóãñ'.-]+)?) \([A-Z]{2,4}\)"
        for text in (match.get("onemli_anlar", []) + match.get("rakip_tartismali_anlar", [])
                     + match.get("en_iyi_reytingler", []) + match.get("en_dusuk_reytingler", [])):
            add(*_re.findall(player, text))
        add(st.get("competition"))
        for w in _re.findall(r"[A-ZÇĞİÖŞÜ][\wçğıöşüéáíóãñ.-]{2,}", question or ""):
            if w not in ("Hocam", "GOL", "VAR"):
                add(w)
        out, seen = [], set()
        for n in names:
            k = n.casefold()
            if k not in seen:
                seen.add(k)
                out.append(n)
        return ", ".join(out[:40])

    def _current_qid(self):
        st = self.io.read_state() or {}
        return st.get("question_id") if st.get("active") else None

    def _say(self, text: str, aborted, prof: dict | None = None):
        self._wait_opening()
        self._speak_direct(text, aborted, prof)

    def _speak_direct(self, text: str, aborted, prof: dict | None = None):
        status.set("speaking")
        if getattr(self.speak, "voiced", False):
            self.speak(text, aborted, prof)
        elif getattr(self.speak, "abortable", False):
            self.speak(text, aborted)
        else:
            self.speak(text)

    def _prepare(self, text: str, prof: dict | None = None):
        """Sesi önceden hazırla (soru ekrana gelince hemen çalsın). Desteklemeyen konuşucuda None."""
        prep = getattr(self.speak, "prepare", None)
        if not prep:
            return None
        return prep(text, prof) if getattr(self.speak, "voiced", False) else prep(text)

    def _play(self, audio, text: str, aborted, prof: dict | None = None):
        self._wait_opening()
        self._play_now(audio, text, aborted, prof)

    def _play_now(self, audio, text: str, aborted, prof: dict | None = None):
        if audio is None:
            self._speak_direct(text, aborted, prof)
            return
        status.set("speaking")
        self.speak.play(audio, aborted)

    @staticmethod
    def _discard(audio):
        if audio:
            try:
                os.remove(audio)
            except OSError:
                pass

    def handle(self, st: dict):
        qid = st["question_id"]
        t0 = time.time()
        aborted = _Debounce(lambda: self._current_qid() != qid, hold=0.6)
        j = st.get("journalist") or {}
        print(f"\n=== {st.get('title') or st.get('screen')} {st.get('question_index') or ''}"
              f"{'/' + str(st['question_total']) if st.get('question_total') else ''} | {j.get('name')} ({j.get('outlet')}, {j.get('mood')})")
        print(f"  Oyunun sorusu: {st.get('game_question')}")

        match = st.get("match") or self.match
        if st.get("screen") == "press_conference" and not st.get("event_hint"):
            # panel maç öncesi/sonu ayırmıyor: oyunun sorusundan karar ver, toplantı boyunca hatırla
            if self.meeting_kind is None:
                self.meeting_kind = press.meeting_kind(st.get("game_question"))
                if self.meeting_kind:
                    print(f"  [toplantı] tür: {'maç öncesi' if self.meeting_kind == 'pre' else 'maç sonu'}")
            if self.meeting_kind == "pre":
                st = dict(st, event_hint="pre_match")
        # maç öncesi: saha kenarı röportajı ya da oyunun sorusundan maç öncesi olduğu anlaşılan basın toplantısı
        pre_match = st.get("screen") == "tunnel_interview" or (st.get("screen") == "press_conference"
                                                               and st.get("event_hint") == "pre_match")
        if match is None and pre_match:                                # maç öncesi: bu maç oynanmadı, geçen maç
            prev = match_log.previous_summary(opponent=st.get("opponent"))
            if prev:
                prev = match_log.mark_manager_team(prev, None, my_team=self.manager_team)
                match = {"GECEN_MAC (bugünkü maç DEĞİL, geçen maç)": prev}
                print(f"  [maç] geçen maç: {prev.get('takimlar')} {prev.get('skor', '')}")
            else:
                print("  [maç] geçen maç yok (ya da aynı rakibe karşı tekrar oynanan kaydedilmemiş maç)")
        elif match is None:
            match = match_log.recent_summary()
            if match:
                match = match_log.mark_manager_team(match, st.get("opponent"), my_team=None if st.get("opponent")
                                                    else self.manager_team)
                if match.get("teknik_direktorun_takimi"):
                    self.manager_team = match["teknik_direktorun_takimi"].split(" (")[0]
                print(f"  [maç] özet: {match.get('takimlar')} {match.get('skor', '')}, "
                      f"{len(match.get('onemli_anlar', []))} an, {len(match.get('goller', []))} gol")
        status.set("generating")
        jn = (st.get("journalist") or {}).get("name")
        first = bool(jn) and jn not in self.introduced
        if first:
            self.introduced.add(jn)
        gen = press.generate_question(st, match, self.history, introduce=first)
        question = gen["question"]
        print(f"  Soru [{gen['source']}, {gen['event']}, {time.time() - t0:.1f} sn]: {question}")
        if self._current_qid() != qid:
            print("  (soru ekranda değişti, atlandı: elle cevaplandı)"); status.set("manual"); return

        prof = self.voicebook.for_journalist(j)
        audio = self._prepare(question, prof)     # ses hazır olmadan soruyu ekrana koyma: ikisi birlikte gelsin
        if self._current_qid() != qid:
            self._discard(audio)
            print("  (soru ekranda değişti, atlandı: elle cevaplandı)"); status.set("manual"); return

        if C.REPLACE_QUESTION and gen["source"] == "llm":
            self.io.write_question(qid, question)
            la = self.io.wait_applied(qid, "question", timeout=1.5)
            if la and not la.get("ok"):
                print(f"  [eklenti] soru değiştirilemedi: {la.get('detail')}")
                if "bayat" in (la.get("detail") or ""):
                    self._discard(audio)
                    print("  (soru ekranda değişti, okunmadı)"); status.set("manual"); return

        print(f"  (okuma başlıyor, soru çıktıktan {time.time() - t0:.1f} sn sonra)")
        self._play(audio, question, aborted, prof)
        if aborted():
            print("  (soru okunurken ekranda değişti, atlandı)"); return

        hint_fn = getattr(self.listen, "set_hint", None)
        if hint_fn:
            hint_fn(self._name_hint(st, question, match))
        answer = None
        for attempt in range(C.LISTEN_RETRIES + 1):
            answer = self.listen(aborted)
            if answer is None:
                print("  (iptal: soru ekranda değişti; manuel cevaplandı varsayıldı)"); status.set("manual"); return
            if answer:
                break
            if attempt < C.LISTEN_RETRIES:
                sorry = "Kusura bakmayın, sizi duyamadım. Tekrar eder misiniz?"
                self._wait_opening()
                self._play_now(self._prepare_fixed(sorry, prof), sorry, aborted, prof)
        if not answer:
            print("  Cevap alınamadı; seçimi oyunda elle yap."); return
        print(f"  Sen: {answer}")

        status.set("classifying")
        jname = j.get("name") or "?"
        want_fu = (random.random() < self.follow_up_prob
                   and jname not in self.fu_asked               # gazeteci başına toplantıda en fazla 1 takip sorusu
                   and not press.is_refusal(answer)             # "yorum yok" / "geçelim" -> üsteleme yok
                   and not press.is_game_repeat(st))            # oyun zaten soruyu yineliyor
        res = press.classify_answer(st, question, answer, want_follow_up=want_fu)
        cat = next((c for c in st["categories"] if c["index"] == res["category_index"]), None)
        opt_text = cat["options"][res["option_index"]]["text"] if cat else "?"
        print(f"  -> {cat['title'] if cat else '?'} / {res['option_index']}: {opt_text}")
        print(f"  -> Ekrana: {res['display_text']}  ({res['source']}; {res.get('reason') or ''})")

        entry = {"time": datetime.now().isoformat(timespec="seconds"), "question_id": qid,
                 "screen": st.get("screen"), "event": gen["event"], "journalist": j,
                 "game_question": st.get("game_question"), "question": question, "answer": answer,
                 "category": cat["title"] if cat else None, "option_text": opt_text, **res}

        # Takip sorusu: oyuna etkisi yok, sadece atmosfer. Oyun ilerlemeden ÖNCE yapılır.
        if res.get("follow_up") and not aborted():
            self.fu_asked.add(jname)
            print(f"  Takip sorusu: {res['follow_up']}")
            self._say(res["follow_up"], aborted, prof)
            fu_answer = self.listen(aborted)
            if fu_answer:
                print(f"  Sen (takip): {fu_answer}")
                entry["follow_up_answer"] = fu_answer

        if aborted():
            print("  (soru ekranda değişti, cevap gönderilmedi)"); return
        if C.AUTO_ANSWER:
            status.set("applying")
            self.io.write_answer(qid, res["category_index"], res["option_index"], res["display_text"])
            # eklenti tıklamayı doğrular; etkisizse diğer buton/yöntemleri dener (en fazla ~12 sn)
            la = self.io.wait_applied(qid, "answer", timeout=14,
                                      final=lambda x: not x.get("ok") or "doğrulanıyor" not in (x.get("detail") or ""))
            if la is None:
                print("  [eklenti] onay gelmedi (eklenti çalışıyor mu?)")
            else:
                print(f"  [eklenti] {'OK' if la.get('ok') else 'HATA'}: {la.get('detail')}")
            entry["applied"] = la
        self.history.append(entry)
        self.answered += 1
        status.set("idle", "Hazır, sıradaki soru bekleniyor")

    def _end_conference(self):
        if not self.history:
            return
        os.makedirs(self.log_dir, exist_ok=True)
        path = os.path.join(self.log_dir, f"press_{datetime.now():%Y%m%d_%H%M%S}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.history, f, ensure_ascii=False, indent=1)
        print(f"\nToplantı bitti, kayıt: {path}")
        self.history = []
