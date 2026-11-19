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
KEYWORDS = [
    "gol", "golü", "ağlar", "file", "direk", "üst direk", "yan direk", "kurtar", "kurtarış", "çıkardı", "penaltı",
    "kırmızı kart", "sarı kart", "ihraç", "sakat", "sakatlık", "oyuna giriyor", "oyundan çıkıyor", "değişiklik",
    "ofsayt", "var ", "kaçırdı", "kaçtı", "inanılmaz", "muhteşem", "harika", "uzaktan", "kafa vuruşu", "frikik",
    "korner", "faul", "tehlikeli", "son dakika", "uzatma", "devre", "maç sona erdi", "maç sonu",
]
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
    m = (t or "").split(":")[0]
    return str(int(m)) if m.isdigit() else "?"


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
        out["olay_dakikalari"] = ev
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
    if len(codes) == 2:
        out["ev"] = f"{fulls[0].title() if fulls else codes[0]} ({codes[0]})"
        out["deplasman"] = f"{fulls[1].title() if len(fulls) > 1 else codes[1]} ({codes[1]})"
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
        for key in {name, short}:
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
    summary["son_dakika"] = (end or {}).get("t") or (comments[-1]["t"] if comments else None)

    # goller: skor değişimleri + o ana yakın anlatım satırları
    goals, prev = [], None
    for s in scores:
        if prev is not None and s["s"] != prev:
            near = [c["x"] for c in comments if c.get("s") == s["s"] and _minute(c.get("t")) == _minute(s.get("t"))][:2]
            goals.append({"dakika": _minute(s.get("t")), "skor": s["s"], "anlatim": near})
        prev = s["s"]
    if goals:
        summary["goller"] = goals

    # önemli anlar: anahtar kelimeli anlatım satırları (tekrarsız, dakikaya yayılmış)
    moments, seen = [], set()
    for c in comments:
        x = c.get("x", "")
        low = x.lower()
        if x in seen or not any(k in low for k in KEYWORDS):
            continue
        seen.add(x)
        moments.append(f"{_minute(c.get('t'))}' {x}")
    if len(moments) > max_moments:                      # eşit aralıklı seç
        step = len(moments) / max_moments
        moments = [moments[int(i * step)] for i in range(max_moments)]
    if moments:
        summary["onemli_anlar"] = moments

    if snaps:
        last = snaps[-1]
        parsed = parse_snapshot(last.get("items") or [])
        players = {}
        for sn in snaps:                                  # tüm fotoğraflardan oyuncu-takım eşlemesi (değişikliklerle gelenler)
            players.update(parse_snapshot(sn.get("items") or []).get("_oyuncu_takim", {}))
        parsed.pop("_oyuncu_takim", None)
        summary.update({k: v for k, v in parsed.items() if k != "skor" or "skor" not in summary})
        if last.get("mentality"):
            summary["son_mentalite"] = last["mentality"]
        if players:                                       # olayları doğru takıma bağlayabilsin
            summary["onemli_anlar"] = [_tag_players(m, players) for m in summary.get("onemli_anlar", [])]
            for g in summary.get("goller", []):
                g["anlatim"] = [_tag_players(x, players) for x in g.get("anlatim", [])]
    if summary.get("ev") and summary.get("deplasman"):
        summary["takimlar"] = f"{summary.pop('ev')} - {summary.pop('deplasman')}"
    return {k: v for k, v in summary.items() if v}


def mark_manager_team(summary: dict, opponent: str | None) -> dict:
    """Rakip adına göre teknik direktörün takımını işaretle (soru doğru tarafa sorulsun)."""
    teams = (summary.get("takimlar") or "").split(" - ")
    if opponent and len(teams) == 2:
        opp = opponent.casefold().replace("i̇", "i")
        mine = [t for t in teams if opp not in t.casefold().replace("i̇", "i")]
        if len(mine) == 1:
            summary["teknik_direktorun_takimi"] = mine[0]
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


def previous_summary(max_age_days: float = 7) -> dict | None:
    """Maç öncesi için: en son TAMAMLANMIŞ maçın özeti (end satırı olan, 80. dakikayı görmüş). O an başlamış
    güncel maçın kaydı alınmaz."""
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
        return s if len(s) > 2 else None
    return None
