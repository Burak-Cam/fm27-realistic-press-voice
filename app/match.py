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
    return (t or "").split(":")[0] or "?"


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
    stats = {}
    for i, t in enumerate(texts):
        if t in STAT_LABELS and t not in stats:
            vals = [v for v in texts[i + 1:i + 4] if _VALUE.match(v)][:2]
            if vals:
                stats[t] = " - ".join(vals)
    if stats:
        out["istatistik"] = stats
    ratings = []
    for i, (n, t) in enumerate(items):
        if n == "Name":
            for _, prev in reversed(items[max(0, i - 3):i]):
                if _RATING.match(prev):
                    ratings.append((t, prev))
                    break
    if ratings:
        rs = sorted(ratings, key=lambda x: float(x[1].replace(",", ".")), reverse=True)
        out["en_iyi_reytingler"] = [f"{n} {r}" for n, r in rs[:3]]
        out["en_dusuk_reytingler"] = [f"{n} {r}" for n, r in rs[-3:]]
    return out


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
        summary.update({k: v for k, v in parse_snapshot(last.get("items") or []).items() if k != "skor" or "skor" not in summary})
        if last.get("mentality"):
            summary["son_mentalite"] = last["mentality"]
    return {k: v for k, v in summary.items() if v}


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
