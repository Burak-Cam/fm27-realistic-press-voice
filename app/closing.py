"""Toplantı/röportaj bitince gazetecinin kapanış cümlesi (anında, LLM'siz).

Cümle üç parçadan kurulur: teşekkür + kapanış + dilek. Parçalar etkinlik türüne göre seçilir; son kullanılan
cümleler logs/closing_recent.json'da tutulur ve tekrar edilmez.
"""
import json
import os
import random

THANKS = [
    "Cevaplarınız için çok teşekkürler hocam.",
    "Zaman ayırdığınız için teşekkür ederiz.",
    "Açıklamalarınız için sağ olun hocam.",
    "Samimi cevaplarınız için teşekkürler.",
    "Vakit ayırdığınız için çok sağ olun.",
    "Bizi kırmadığınız için teşekkürler hocam.",
    "Değerlendirmeleriniz için teşekkür ederiz.",
]

ENDS = {
    "press_conference": [
        "Bugünlük sorularımız bu kadar.",
        "Basın toplantımızın sonuna geldik.",
        "Soru cevap bölümünü burada bitiriyoruz.",
        "Toplantıyı burada noktalıyoruz.",
        "Başka sorumuz yok.",
        "Sorularımız bu kadardı.",
    ],
    "tunnel_interview": [
        "Sizi daha fazla tutmayalım, maç başlamak üzere.",
        "Kulübeye geçmeden son sorumuz buydu.",
        "Sizi daha fazla bekletmeyelim.",
        "Röportajımız bu kadardı.",
        "Maç öncesi sorularımız bu kadar.",
    ],
    "post_match_tunnel_interview": [
        "Sizi daha fazla tutmayalım.",
        "Röportajımız bu kadardı.",
        "Maç sonu sorularımız bu kadar.",
        "Sizi soyunma odasına bırakalım.",
        "Sorularımız bu kadardı.",
    ],
}

WISHES = {
    "pre_match": ["Maçta başarılar.", "Bol şans hocam.", "İyi maçlar.", "Kolay gelsin, iyi maçlar dileriz."],
    "post_match": ["Bir sonraki maçta görüşmek üzere.", "İyi akşamlar.", "Haftaya görüşmek üzere.", "Kolay gelsin."],
    "manager_intro": ["Yeni görevinizde başarılar dileriz.", "Hayırlı olsun, kolay gelsin.", "Yolunuz açık olsun hocam."],
    "player_signing": ["Transfer hayırlı olsun.", "Yeni transferle birlikte başarılar dileriz.", "Hayırlı olsun."],
    "other": ["İyi çalışmalar.", "Görüşmek üzere.", "Kolay gelsin."],
}

RECENT_MAX = 8

# Açılış: basın toplantısında moderatör konuşur, saha kenarında gazeteci selamlar.
OPEN_GREET = {
    "press_conference": [
        "Arkadaşlar hoş geldiniz.",
        "Evet arkadaşlar, yerlerimizi alalım.",
        "Herkese merhaba, hoş geldiniz.",
        "Arkadaşlar, başlıyoruz.",
        "İyi günler arkadaşlar.",
    ],
    "tunnel_interview": ["Hocam merhaba.", "Hocam hoş geldiniz.", "Merhaba hocam, kısa tutacağız."],
    "post_match_tunnel_interview": ["Hocam merhaba.", "Hocam geçmiş olsun, hoş geldiniz.", "Merhaba hocam."],
}
OPEN_MAIN = {
    "press_conference": [
        "Basın toplantımız başlıyor.",
        "Hocamız aramızda, sorularınızı alabiliriz.",
        "Basın toplantımıza başlıyoruz, ilk soruyu alalım.",
        "Hocamız hazır, sorularınızı sırayla alalım.",
        "Toplantımızı başlatıyoruz, söz sizde.",
    ],
    "tunnel_interview": [
        "Maç öncesi birkaç kısa sorumuz olacak.",
        "Kulübeye geçmeden önce iki üç soru soralım.",
        "Maç öncesi düşüncelerinizi alalım.",
    ],
    "post_match_tunnel_interview": [
        "Maç sonu sıcağı sıcağına birkaç soru soralım.",
        "Maçla ilgili kısa birkaç sorumuz olacak.",
        "Maç sonrası ilk değerlendirmelerinizi alalım.",
    ],
}


def make_opening(screen: str | None, event: str | None = None, recent_path: str | None = None, rng=random) -> str:
    """Toplantı/röportaj açılış cümlesi; son kullanılanlardan farklı."""
    key = screen if screen in OPEN_MAIN else "press_conference"
    recent = _load(recent_path)
    line = ""
    for _ in range(30):
        line = f"{rng.choice(OPEN_GREET[key])} {rng.choice(OPEN_MAIN[key])}"
        if line not in recent:
            break
    _save(recent_path, (recent + [line])[-RECENT_MAX:])
    return line


def _event_for(screen: str | None, event: str | None) -> str:
    if event in WISHES:
        return event
    if screen == "tunnel_interview":
        return "pre_match"
    if screen == "post_match_tunnel_interview":
        return "post_match"
    return "other"


def make(screen: str | None, event: str | None = None, recent_path: str | None = None, rng=random) -> str:
    """Kapanış cümlesi üret; recent_path verilirse son kullanılanlardan farklı olur ve oraya kaydedilir."""
    ends = ENDS.get(screen or "", ENDS["press_conference"])
    wishes = WISHES[_event_for(screen, event)]
    recent = _load(recent_path)
    line = ""
    for _ in range(30):
        parts = [rng.choice(THANKS), rng.choice(ends), rng.choice(wishes)]
        if rng.random() < 0.4:                 # bazen kapanış önce gelsin
            parts[0], parts[1] = parts[1], parts[0]
        line = " ".join(parts)
        # aynı cümle ya da son cümleyle aynı parça tekrar etmesin
        if line not in recent and not (recent and any(p in recent[-1] for p in parts[:2])):
            break
    _save(recent_path, (recent + [line])[-RECENT_MAX:])
    return line


def _load(path):
    if not path:
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _save(path, items):
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=1)
    except OSError:
        pass
