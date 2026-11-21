"""Eklentinin maç kaydını (matches/match_*.jsonl) soru üretimi için özete çevirir.

Kayıt satırları: start | score {t,s} | c {t,s,x: anlatım} | snap {t, mentality, items: [[ad, metin], ...]} | end
Not: anlatımdaki olay kalıpları ilk gerçek kayıtlardan sonra ayarlanacak (KEYWORDS genişletilebilir).
"""
import glob
import json
import os
import re
import time

import config as C

MATCH_DIR = os.path.join(C.BRIDGE_DIR, "matches")

# Anlatımda "önemli an" sayılacak kalıplar (küçük harf). İlk kayıtlarla genişletilecek.
MOMENT = re.compile(
    r"\bGOL\b|direk(ten| bu| dibin)|direğ|kurtar|kart\b|kartı|penaltı|sakat|yerde kaldı|oyuna giriyor|"
    r"yerine .*(giriyor|alıyor)|değişiklik|ofsayt|(?-i:\bVAR\b)|burun buruna|kaçırdı|kaçtı|son anda|"
    r"harika bir müdahale|müthiş|frikik|kafa vuruşu|ağları|tehlikeli|inanılmaz|maç sona erdi", re.IGNORECASE)
KEYWORDS = MOMENT   # geriye uyum
STAT_LABELS = ["Şut", "İsabetli Şut", "Topla Oynama", "İsabetli Pas", "Korner", "Faul", "Sarı Kart", "Kırmızı Kart",
               "Topa Müdahale", "Ofsayt", "Katettiği Mesafe"]
_RATING = re.compile(r"^\d{1,2},\d$")
_VALUE = re.compile(r"^(%?\d+([.,]\d+)?%?|\d+([.,]\d+)?km)$")


def latest_file(max_age_min: float = 120, folder: str | None = None) -> str | None:
    """Son max_age_min dakikada güncellenmiş en yeni maç kaydı."""
    files = glob.glob(os.path.join(folder or MATCH_DIR, "match_*.jsonl"))
    if not files:
        return None
    f = max(files, key=os.path.getmtime)
    return f if time.time() - os.path.getmtime(f) <= max_age_min * 60 else None


def load(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return rows


def _minute(t: str | None) -> str:
    """Geçen tam dakika ("18:30" -> "18"); süre karşılaştırmaları için."""
    m = (t or "").split(":")[0]
    return str(int(m)) if m.isdigit() else "?"


def _match_minute(t: str | None) -> str:
    """Tabeladaki dakika: 18:30 oyunun 19. dakikası (FM tabelası 19' yazar; 2026-11-21 kaydıyla doğrulandı)."""
    m = _minute(t)
    return str(int(m) + 1) if m.isdigit() else "?"


# Ekran kaydında maç bilgisi taşımayan paneller (2026-11-21 kaydı: Portal menüsü, bütçe, röportaj cevap seçenekleri,
# devre arası takım konuşması tepkileri). Bunlar prompt'u şişirip Groq dakikalık token sınırına (429) takılıyordu.
_NOISE_PANEL = re.compile(r"Portal|TitleBar|Interview|Press|Meeting|SpeakTo|TeamTalk", re.IGNORECASE)

# LLM'e cümle olarak giden istatistikler: sadece TV'de söylenen basitlikte olanlar (xG, mesafe, pas %, müdahale yok).
STAT_SENTENCES = [("Şut", "şut çekti"), ("İsabetli Şut", "isabetli şut çekti"), ("Topla Oynama", ""),
                  ("Korner", "korner kullandı"), ("Faul", "faul yaptı"), ("Sarı Kart", "sarı kart gördü"),
                  ("Kırmızı Kart", "kırmızı kart gördü"), ("Ofsayt", "ofsayta düştü")]

# Rakibin pozisyonu sadece tartışmalı bir karar içeriyorsa soruya girer (kullanıcı isteği 2026-11-21).
CONTROVERSIAL = re.compile(r"penaltı|(?-i:\bVAR\b)|kırmızı|ofsayt|iptal|itiraz|tartışmalı", re.IGNORECASE)


_FORMATION = re.compile(r"^(\S+) Diziliş")


def parse_snapshot(items: list[list[str]]) -> dict:
    """Fotoğraftaki metinlerden istatistik, xG, reyting ve olay dakikalarını çıkar (sezgisel)."""
    texts = [t for _, t in items]
    out: dict = {}
    xg = [t for n, t in items if n == "ExpectedGoals"]
    if len(xg) >= 2:
        out["xG"] = f"{xg[0]} - {xg[1]}"
    sc = [t for n, t in items if n == "Score"]
    if sc:
        out["skor"] = sc[-1]
    ev = [t for n, t in items if n.startswith("DugoutEvent") and t.strip().isdigit()]
    if ev:
        out["olay_dakikalari"] = sorted(set(ev), key=int)
    # istatistik kutusu takım takım yazılır: "FENERBAHÇE", Şut, 12, İsabetli Şut, 9, ... "GALATASARAY", Şut, 6, ...
    per_team: dict[str, list[str]] = {}
    side = -1
    for i, (n, t) in enumerate(items):
        if n == "primary-text" and t.isupper() and len(t) > 2:
            side += 1
            continue
        if t in STAT_LABELS and 0 <= side <= 1 and i + 1 < len(items) and _VALUE.match(items[i + 1][1]):
            vals = per_team.setdefault(t, ["?", "?"])
            if vals[side] == "?":
                vals[side] = items[i + 1][1]
    stats = {k: f"{v[0]} - {v[1]}" for k, v in per_team.items() if "?" not in v}
    if stats:
        out["istatistik"] = stats
    # takımlar: başlıktaki kısa kodlar + istatistik bölümündeki BÜYÜK HARFLİ tam adlar (sırayla ev, deplasman)
    codes = [t for n, t in items if n in ("ClubHomeTeamText", "ClubAwayTeamText")][:2]
    fulls = [t for n, t in items if n == "primary-text" and t.isupper() and len(t) > 2][:2]
    if len(codes) == 2 and len(fulls) == 2:
        out["ev"] = f"{fulls[0].title()} ({codes[0]})"
        out["deplasman"] = f"{fulls[1].title()} ({codes[1]})"
    # oyuncu -> takım kodu (diziliş başlığından: "GS Diziliş (TS)")
    team, players, ratings = None, {}, []
    for i, (n, t) in enumerate(items):
        fm = _FORMATION.match(t)
        if fm:
            team = fm.group(1)
            continue
        if n == "Name":
            if team:
                players[t] = team
            for _, prev in reversed(items[max(0, i - 3):i]):
                if _RATING.match(prev):
                    ratings.append((t, prev, team))
                    break
    if players:
        out["_oyuncu_takim"] = players
    if len(codes) == 2:                      # iki taraflı sayılara takım kodu: "FB 2,77 - GS 0,38" (karışmasın)
        tag = lambda v: " - ".join(f"{c} {x}" for c, x in zip(codes, v.split(" - "))) if " - " in v else v
        if "xG" in out:
            out["xG"] = tag(out["xG"])
        if "istatistik" in out:
            out["istatistik"] = {k: tag(v) for k, v in out["istatistik"].items()}
    if ratings:
        rs = sorted(ratings, key=lambda x: float(x[1].replace(",", ".")), reverse=True)
        fmt = lambda x: f"{x[0]} ({x[2]}) {x[1]}" if x[2] else f"{x[0]} {x[1]}"
        out["en_iyi_reytingler"] = [fmt(x) for x in rs[:3]]
        out["en_dusuk_reytingler"] = [fmt(x) for x in rs[-3:]]
    return out


def _tag_players(text: str, players: dict) -> str:
    """Anlatımdaki oyuncu adlarına takım kodunu ekle: 'Muriqi' -> 'Muriqi (FB)'."""
    for name, team in sorted(players.items(), key=lambda kv: -len(kv[0])):
        short = name.split(". ")[-1]           # "M. Asensio" -> "Asensio"
        last = short.split()[-1]               # "Rafa Leão" -> "Leão" (anlatım çoğu zaman soyadı kullanır)
        for key in sorted({name, short, last}, key=len, reverse=True):
            if len(key) >= 3 and key in text and f"{key} (" not in text:
                text = text.replace(key, f"{key} ({team})", 1)
                break
    return text


def summarize(rows: list[dict], max_moments: int = 14) -> dict:
    """Soru üretimine gidecek kısa maç özeti."""
    start = next((r for r in rows if r.get("type") == "start"), {})
    comments = [r for r in rows if r.get("type") == "c"]
    scores = [r for r in rows if r.get("type") == "score"]
    snaps = [r for r in rows if r.get("type") == "snap"]
    end = next((r for r in reversed(rows) if r.get("type") == "end"), None)
    summary: dict = {"takimlar": start.get("teams")}

    final = (end or {}).get("s") or (scores[-1]["s"] if scores else None)
    if final:
        summary["skor"] = final
    # "son_dakika" (90:00) bilerek yok: LLM bunu olay dakikası sanıp uyduruyordu ("90:00'daki penaltı").

    # goller: skor değişimleri + o ana yakın anlatım satırları
    # goller: anlatımdaki "GOL ..." satırları (gerçek kayıt: "GOL Galatasaray A.Ş.!!"). Skor elemanı geç güncellendiği
    # için (gol 02:06, skor 03:36) dakika buradan alınır; golcü sadece satırda oyuncu adı geçerse bilinir.
    goals = []
    for c in comments:
        x = c.get("x", "")
        if re.match(r"^\s*GOL\b", x):
            team = re.sub(r"\s*A\.Ş\.|[!.]+$", "", re.sub(r"^\s*GOL\b[!\s]*", "", x)).strip(" !")
            goals.append({"dakika": _match_minute(c.get("t")), "anlatim": x, "_takim_metni": team})
    if not goals:                                         # eski kayıt / anlatım kaçtıysa: skor değişimleri (golcüsüz)
        prev = None
        for s in scores:
            if prev is not None and s["s"] != prev:
                goals.append({"dakika": _match_minute(s.get("t")), "skor": s["s"], "golcu": "bilinmiyor (tahmin etme)"})
            prev = s["s"]
    if goals:
        summary["goller"] = goals

    # önemli anlar: anahtar kelimeli anlatım satırları (tekrarsız, dakikaya yayılmış)
    moments, seen = [], set()
    for c in comments:
        x = c.get("x", "")
        low = x.lower()
        if x in seen or not MOMENT.search(x):
            continue
        if goals and re.match(r"^\s*GOL\b", x):           # goller ayrı listede; "18' GOL ..." satırı sahiplenmeyi karıştırıyordu
            continue
        seen.add(x)
        moments.append(f"{_match_minute(c.get('t'))}' {x}")
    if len(moments) > max_moments:                      # eşit aralıklı seç
        step = len(moments) / max_moments
        moments = [moments[int(i * step)] for i in range(max_moments)]
    if moments:
        summary["onemli_anlar"] = moments

    if snaps:
        last = snaps[-1]
        parsed = {}
        late_only = {"xG", "istatistik", "en_iyi_reytingler", "en_dusuk_reytingler"}   # erken fotoğrafta hepsi 0
        for sn in reversed(snaps):
            m = _minute(sn.get("t"))
            early = not m.isdigit() or int(m) < 45
            for k, v in parse_snapshot(sn.get("items") or []).items():
                if early and k in late_only:
                    continue
                parsed.setdefault(k, v)
        players = {}
        for sn in snaps:                                  # tüm fotoğraflardan oyuncu-takım eşlemesi (değişikliklerle gelenler)
            players.update(parse_snapshot(sn.get("items") or []).get("_oyuncu_takim", {}))
        parsed.pop("_oyuncu_takim", None)
        summary.update({k: v for k, v in parsed.items() if k != "skor" or "skor" not in summary})
        if last.get("mentality"):
            summary["son_mentalite"] = last["mentality"]
        if players:                                       # olayları doğru takıma bağlayabilsin
            summary["onemli_anlar"] = [_tag_players(m, players) for m in summary.get("onemli_anlar", [])]
            summary["_kendi_kod"] = _own_code(snaps, players)
        late = [sn for sn in snaps if _minute(sn.get("t")).isdigit() and int(_minute(sn.get("t"))) >= 85]
        if late:                                          # canlı tablo maç sonunda = güncel puan durumu
            items = late[-1].get("items") or []
            summary["_tablo"] = _parse_table(items)
            summary["_skorlar"] = _parse_scores(items)
        starters = _squad_names(snaps)
        if starters:                                      # LLM ilk 11'i bilmeyince "X bugün sahada yoktu" uyduruyordu
            summary["_ilk_11"] = starters
            last_pl = parse_snapshot(snaps[-1].get("items") or []).get("_oyuncu_takim", {})
            if last_pl and _minute(snaps[-1].get("t")).isdigit() and int(_minute(snaps[-1].get("t"))) >= 60:
                summary["_son_dizilis"] = last_pl          # {ad: takım kodu}; oyundan alınanlar mark_manager_team'de
        for g in summary.get("goller", []):
            text = g.get("anlatim", "")
            scorer = next((p for p in sorted(players, key=len, reverse=True)
                           if len(p.split(". ")[-1]) >= 3 and p.split(". ")[-1] in text), None)
            g["golcu"] = f"{scorer} ({players[scorer]})" if scorer else g.get("golcu", "bilinmiyor (tahmin etme)")
    for g in summary.get("goller", []):
        team = g.pop("_takim_metni", "")
        if team and "golcu" not in g:
            g["golcu"] = "bilinmiyor (tahmin etme)"
        if team:
            g["takim"] = team
        g.pop("anlatim", None)                    # "GOL X A.Ş.!!" satırı takım/golcü dışında bilgi taşımıyor
    screens = [r for r in rows if r.get("type") == "screen"]
    def _screens_text(rs, limit):
        """Bir aşamanın (devre arası / maç sonu) tüm çekimlerindeki metinler, sırayla ve tekrarsız. Eklenti v0.4.2
        düdükten sonra panel kümesi her değiştiğinde çeker (istatistik ekranı, takım konuşması, röportaj...)."""
        texts, seen = [], set()
        for r in rs:
            for name, items in (r.get("panels") or {}).items():
                if _NOISE_PANEL.search(name):             # menü, portal, röportaj seçenekleri: LLM bunlardan uyduruyordu
                    continue
                for _, t in items:
                    if t not in seen and len(t) < 80:
                        seen.add(t)
                        texts.append(t)
        return " | ".join(texts)[:limit]

    where = lambda r: str(r.get("where", ""))
    full = [r for r in screens if where(r).startswith("mac_sonu") or where(r) == "dudukte_mac_ekrani"]
    half = [r for r in screens if where(r).startswith("devre_arasi")]
    if full:                                              # maç sonu ekranı: golcüler, asistler, istatistikler (ham metin)
        summary["mac_sonu_ekrani_metni"] = _screens_text(full, 3000)
    if half:                                              # devre arası: ilk yarı istatistikleri
        summary["devre_arasi_ekrani_metni"] = _screens_text(half, 1500)
    for k in ("mac_sonu_ekrani_metni", "devre_arasi_ekrani_metni"):
        if not summary.get(k):
            summary.pop(k, None)
    if summary.get("ev") and summary.get("deplasman"):
        summary["takimlar"] = f"{summary.pop('ev')} - {summary.pop('deplasman')}"
    return {k: v for k, v in summary.items() if v}


def _norm(s: str) -> str:
    """Takım adı karşılaştırması: 'KASIMPAŞA'.title() 'Kasimpaşa' verir, anlatım 'Kasımpaşa' yazar; İ -> 'i̇' olur."""
    return (s or "").casefold().replace("i̇", "i").replace("ı", "i")


_PLAYED = re.compile(r"^(\d+) Maç$")
_PTS = re.compile(r"^(\d+) Pua")
_SCORE = re.compile(r"^\d+ - \d+$")


def _parse_table(items: list[list[str]]) -> list[tuple[int, str, int, int]]:
    """Maç ekranının canlı lig tablosu: ['', '4'], ['primary-text', 'Galatasaray'], ['SIText', '3 Maç'], ['', '6 Pua']."""
    rows = []
    for i in range(len(items) - 3):
        (n0, rank), (n1, team), (_, played), (_, pts) = items[i:i + 4]
        mp, mt = _PLAYED.match(played), _PTS.match(pts)
        if rank.isdigit() and n1 == "primary-text" and mp and mt:
            rows.append((int(rank), team, int(mp[1]), int(mt[1])))
    return rows


def _parse_scores(items: list[list[str]]) -> list[str]:
    """Aynı anda oynanan maçlar: üç ardışık primary-text (ev, 'a - b', deplasman), tekrarsız."""
    out = []
    pt = [t for n, t in items if n == "primary-text"]
    for i in range(len(pt) - 2):
        if _SCORE.match(pt[i + 1]) and not _SCORE.match(pt[i]) and not _SCORE.match(pt[i + 2]):
            s = f"{pt[i]} {pt[i + 1]} {pt[i + 2]}"
            if s not in out:
                out.append(s)
    return out


def _standings_sentence(table: list[tuple[int, str, int, int]], me: str) -> str | None:
    """Teknik direktörün takımının sırası ve liderle farkı (tablonun görünen satırlarında yoksa None)."""
    name = me.split(" (")[0]
    mine = next((r for r in table if _norm(r[1]) == _norm(name)), None)
    if not mine:
        return None
    rank, _, played, pts = mine
    head = f"Maç sonu canlı tabloya göre {name}"
    if rank == 1:
        nxt = next((r for r in table if r[0] == 2), None)
        tail = f" En yakın takipçi {nxt[1]} {nxt[3]} puan, fark {pts - nxt[3]} puan." if nxt else ""
        return f"{head} lider ({played} maçta {pts} puan).{tail}"
    lead = next((r for r in table if r[0] == 1), None)
    tail = f" Lider {lead[1]} {lead[3]} puan, fark {lead[3] - pts} puan." if lead else ""
    return f"{head} {rank}. sırada ({played} maçta {pts} puan).{tail}"


def _squad_names(snaps: list[dict]) -> list[str]:
    """İlk 'Kadro' listesindeki ilk 11 ad (forma no + ad): teknik direktörün ilk 11'i."""
    for sn in snaps:
        items = sn.get("items") or []
        if not any(t == "Kadro" for _, t in items):
            continue
        names = [items[i + 1][1] for i, (n, _) in enumerate(items[:-1])
                 if n == "fm-tactics-shirt-number" and items[i + 1][0] == "text" and not _RATING.match(items[i + 1][1])]
        if names:
            return names[:11]
    return []


def _own_code(snaps: list[dict], players: dict) -> str | None:
    """Maç ekranının 'Kadro' listesi teknik direktörün KENDİ kadrosudur (forma no + ad). Adları diziliş görünümünden
    gelen oyuncu->takım eşlemesiyle oylayıp kendi takım kodunu bul. Rakip adı gelmeyen basın toplantısı için."""
    votes: dict[str, int] = {}
    for sn in snaps:
        items = sn.get("items") or []
        if not any(t == "Kadro" for _, t in items):
            continue
        for i, (n, _) in enumerate(items[:-1]):
            if n == "fm-tactics-shirt-number" and items[i + 1][0] == "text":
                team = players.get(items[i + 1][1])
                if team:
                    votes[team] = votes.get(team, 0) + 1
    if not votes:
        return None
    best = max(votes, key=votes.get)
    return best if votes[best] >= 2 and votes[best] > sum(votes.values()) / 2 else None


def mark_manager_team(summary: dict, opponent: str | None, my_team: str | None = None) -> dict:
    """Teknik direktörün takımını işaretle (rakip adından ya da önceden öğrenilen takım adından) ve özeti onun
    gözünden düzenle: her gole kimin attığı açıkça yazılır; rakibin sıradan pozisyonları çıkarılır, sadece
    tartışmalı olanlar (penaltı, VAR, kırmızı kart...) ayrı listede kalır."""
    own = summary.pop("_kendi_kod", None)
    starters = summary.pop("_ilk_11", None)        # Kadro listesi her zaman teknik direktörün kendi kadrosu
    last_pl = summary.pop("_son_dizilis", None)
    table = summary.pop("_tablo", None)
    scores = summary.pop("_skorlar", None)
    if starters:
        summary["teknik_direktorun_ilk_11"] = starters
    teams = (summary.get("takimlar") or "").split(" - ")
    if len(teams) != 2:
        return summary
    # öncelik: oyunun verdiği rakip adı > bu maçın kadro listesi > önceki röportajdan öğrenilen takım
    if opponent:
        mine = [t for t in teams if _norm(opponent) not in _norm(t)]
    elif own:
        mine = [t for t in teams if t.endswith(f"({own})")]
    elif my_team:
        mine = [t for t in teams if _norm(my_team) in _norm(t)]
    else:
        mine = []
    if len(mine) != 1:
        return summary
    me = mine[0]
    other = teams[1] if teams[0] == me else teams[0]
    summary["teknik_direktorun_takimi"] = me
    code = lambda t: (re.search(r"\((\w+)\)\s*$", t) or [None, None])[1]
    my_code, opp_code = code(me), code(other)
    sc = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", summary.get("skor") or "")
    if sc:                                       # sonucu hazır yaz: LLM "2 - 1"i yanlış tarafa okuyup "galibiyetiniz" diyordu
        home, away = int(sc[1]), int(sc[2])
        mine_g, opp_g = (home, away) if teams[0] == me else (away, home)
        res = "GALİBİYET" if mine_g > opp_g else "MAĞLUBİYET" if mine_g < opp_g else "BERABERLİK"
        summary["sonuc_teknik_direktor_icin"] = f"{res}: {me.split(' (')[0]} {mine_g} - {opp_g} {other.split(' (')[0]}"
    summary["teknik_direktorun_takimi_sahasi"] = "iç saha" if teams[0] == me else "deplasman"
    if table:
        sent = _standings_sentence(table, me)
        if sent:
            summary["puan_durumu"] = sent
    if scores:                                    # bu maç hariç; rakiplerin sonucu ("Samsunspor da kazandı") için
        names = {_norm(t.split(" (")[0]) for t in teams}
        others = [s for s in scores if not any(n in _norm(s) for n in names)]
        if others:
            summary["ayni_anda_oynanan_maclar"] = others
    summary.pop("olay_dakikalari", None)          # anlamı belirsiz (kulübe olayları): LLM "78'de oyundan aldınız" uyduruyordu
    if starters and last_pl and my_code:
        on_pitch = {n for n, t in last_pl.items() if t == my_code}
        if on_pitch:
            off = [s for s in starters if s not in on_pitch]
            if off:
                summary["oyundan_alinanlar"] = off
                summary["oyundan_alinanlar_notu"] = "çıkış dakikaları bilinmiyor, dakika söyleme"
    if my_code and opp_code:                     # iki taraflı sayıları ayrı alanlara böl: "FB 11 - GS 9" -> {siz: 9, rakip: 11}
        def split(v):                            # LLM "A - B" biçimini sık sık ters okuyordu (2026-11-21 testi)
            sides = dict(re.findall(r"\b(\w+) ([^\s-][^-]*?)\s*(?:-|$)", v))
            if my_code in sides and opp_code in sides:
                a, b = sides[my_code].strip(), sides[opp_code].strip()
                out = {"siz": a, "rakip": b}
                num = lambda x: float(re.sub(r"[^\d,.]", "", x).replace(",", ".") or "nan")
                try:                              # karşılaştırma hazır: LLM 9'a 11'i "daha fazla şut çektiniz" okudu
                    x, y = num(a), num(b)
                    out["fazla_olan"] = "siz" if x > y else "rakip" if y > x else "eşit"
                except ValueError:
                    pass
                return out
            return v
        summary.pop("xG", None)                   # gerçek muhabir söylemez; LLM'e gitmesin
        if isinstance(summary.get("istatistik"), dict):
            # tablo yerine hazır cümle: qwen {siz: 9, rakip: 11} + fazla_olan alanına rağmen "daha fazla şut çektiniz" dedi
            lines = []
            for label, verb in STAT_SENTENCES:
                v = summary["istatistik"].get(label)
                d = split(v) if isinstance(v, str) else None
                if not isinstance(d, dict) or "fazla_olan" not in d:
                    continue
                a, b = d["siz"], d["rakip"]
                if label == "Topla Oynama":
                    lines.append(f"Topla oynamada {'siz öndesiniz' if d['fazla_olan'] == 'siz' else 'rakip önde' if d['fazla_olan'] == 'rakip' else 'eşitlik var'} (siz {a}, rakip {b})")
                elif d["fazla_olan"] == "siz":
                    lines.append(f"Siz rakipten fazla {verb} (siz {a}, rakip {b})")
                elif d["fazla_olan"] == "rakip":
                    lines.append(f"Rakip sizden fazla {verb} (rakip {b}, siz {a})")
                else:
                    lines.append(f"İki takım eşit sayıda {verb} ({a})")
            summary.pop("istatistik")
            if lines:
                summary["istatistik_cumleleri"] = lines
    mine_n = opp_n = 0
    known = True                                  # bir golün tarafı bilinmezse sonraki ara skorlar yazılmaz
    for g in summary.get("goller", []):
        side = g.get("takim") or ""
        if not side and opp_code and f"({opp_code})" in (g.get("golcu") or ""):
            side = other
        elif not side and my_code and f"({my_code})" in (g.get("golcu") or ""):
            side = me
        if not side:
            known = False
            continue
        mine_goal = _norm(side.split(" (")[0]) in _norm(me)
        g["kimin_golu"] = "teknik direktörün takımı attı" if mine_goal else "RAKİP attı (teknik direktörün takımı gol yedi)"
        if known:                                 # ara skor hazır: LLM "farkı ikiye çıkardı" diye kendi hesaplıyordu
            mine_n, opp_n = mine_n + mine_goal, opp_n + (not mine_goal)
            g["bu_golden_sonra"] = f"{me.split(' (')[0]} {mine_n} - {opp_n} {other.split(' (')[0]}"
    if my_code and opp_code:
        keep, rival = [], []
        for m in summary.get("onemli_anlar", []):
            if f"({opp_code})" in m and f"({my_code})" not in m:
                if CONTROVERSIAL.search(m):
                    rival.append(m)
                continue                               # rakibin sıradan pozisyonu: sorulmasın
            keep.append(m)
        summary["onemli_anlar"] = keep
        if rival:
            summary["rakip_tartismali_anlar"] = rival
    return summary


def recent_summary(max_age_min: float = 120) -> dict | None:
    """Maç sonu toplantısı için: son 2 saatte biten (ya da güncellenen) maçın özeti; yoksa None."""
    f = latest_file(max_age_min)
    if not f:
        return None
    try:
        s = summarize(load(f))
    except Exception as e:
        print(f"  [maç] özet çıkarılamadı: {e!r}")
        return None
    return s if len(s) > 2 else None


def previous_summary(max_age_days: float = 7, opponent: str | None = None) -> dict | None:
    """Maç öncesi için: en son TAMAMLANMIŞ maçın özeti (end satırı olan, 80. dakikayı görmüş). O an başlamış
    güncel maçın kaydı alınmaz. Son maç bugünkü rakibe karşıysa None: oyun kaydedilmeden aynı maç tekrar
    oynanıyor demektir (o maç bu kariyerde hiç olmadı). Bedeli: çift maçlı kupa turunda ilk ayak anılmaz."""
    files = sorted(glob.glob(os.path.join(MATCH_DIR, "match_*.jsonl")), key=os.path.getmtime, reverse=True)
    for f in files:
        if time.time() - os.path.getmtime(f) > max_age_days * 86400:
            break
        try:
            rows = load(f)
        except OSError:
            continue
        end = next((r for r in reversed(rows) if r.get("type") == "end"), None)
        if not end or not _minute(end.get("t")).isdigit() or int(_minute(end.get("t"))) < 80:
            continue
        s = summarize(rows)
        if opponent and _norm(opponent) in _norm(s.get("takimlar")):
            return None
        return s if len(s) > 2 else None
    return None


def cleanup(keep: int = 30):
    """Eski maç kayıtlarını sil (son `keep` kalır)."""
    files = sorted(glob.glob(os.path.join(MATCH_DIR, "match_*.jsonl")), key=os.path.getmtime, reverse=True)
    for f in files[keep:]:
        try:
            os.remove(f)
        except OSError:
            pass
