"""Toplantı/röportaj açılış ve kapanış cümleleri (hazır, LLM'siz). Son kullanılanlar logs/*_recent.json'da tutulur."""
import json
import os
import random

# Hazır kapanış cümleleri (kullanıcı isteği: her tür için 7-8 sabit cümle, ses önceden hazırlanır -> toplantı anında biter).
# Basın toplantısını moderatör, saha kenarı röportajını gazeteci kapatır.
CLOSINGS = {
    "press_conference": [
        "Evet arkadaşlar, sorularımız bu kadardı. Hocamıza teşekkür ediyoruz.",
        "Basın toplantımızın sonuna geldik. Katılımınız için hepinize teşekkürler.",
        "Bugünlük bu kadar arkadaşlar. Hocam, değerlendirmeleriniz için teşekkürler.",
        "Zamanımız doldu arkadaşlar. Hocamıza teşekkür ediyor, toplantıyı burada sonlandırıyoruz.",
        "Son soruyu da aldık. Hocam teşekkürler, herkese iyi çalışmalar.",
        "Toplantımızı burada noktalıyoruz. Hocam, açıklamalarınız için sağ olun.",
        "Evet, bugünkü basın toplantımız sona erdi. Hepinize teşekkür ederiz.",
        "Sorularınız için teşekkürler arkadaşlar. Bir sonraki toplantıda görüşmek üzere.",
    ],
    "tunnel_interview": [
        "Teşekkürler hocam, maçta başarılar.",
        "Sizi daha fazla tutmayalım hocam, iyi maçlar.",
        "Cevaplarınız için sağ olun hocam, bol şans.",
        "Teşekkürler hocam, kulübeye geçebilirsiniz. İyi maçlar.",
        "Sorularımız bu kadardı hocam, başarılar dileriz.",
        "Vakit ayırdığınız için teşekkürler, maçta kolay gelsin.",
        "Tamamdır hocam, teşekkürler. İyi maçlar diliyoruz.",
        "Bizi kırmadığınız için sağ olun hocam, bol şans.",
    ],
    "post_match_tunnel_interview": [
        "Teşekkürler hocam, basın toplantısında görüşmek üzere.",
        "Değerlendirmeleriniz için sağ olun hocam.",
        "Sizi daha fazla tutmayalım hocam, teşekkürler.",
        "Maç sonu sorularımız bu kadardı, teşekkürler hocam.",
        "Vakit ayırdığınız için teşekkürler hocam, kolay gelsin.",
        "Tamamdır hocam, sağ olun. Bir sonraki maçta görüşmek üzere.",
        "Cevaplarınız için teşekkürler hocam, iyi dinlenmeler.",
        "Teşekkür ederiz hocam, sizi soyunma odasına bırakalım.",
    ],
}

RECENT_MAX = 8

# Hazır açılış cümleleri: basın toplantısını moderatör açar, saha kenarında gazeteci selamlar.
OPENINGS = {
    "press_conference": [
        "Arkadaşlar hoş geldiniz, basın toplantımız başlıyor.",
        "Evet arkadaşlar, yerlerimizi alalım. Hocamız aramızda, sorularınızı alabiliriz.",
        "Herkese merhaba. Basın toplantımıza başlıyoruz, ilk soruyu alalım.",
        "Arkadaşlar başlıyoruz. Hocamız hazır, sorularınızı sırayla alalım.",
        "İyi günler arkadaşlar, toplantımızı başlatıyoruz. Söz sizde.",
        "Hoş geldiniz arkadaşlar. Vaktimiz kısıtlı, sorularınızı kısa tutalım lütfen.",
        "Evet arkadaşlar, hocamız geldi. Basın toplantımıza başlayabiliriz.",
        "Herkese hoş geldiniz. Sorularınızı alalım, buyurun.",
    ],
    "tunnel_interview": [
        "Hocam merhaba, maç öncesi birkaç kısa sorumuz olacak.",
        "Hocam hoş geldiniz, kulübeye geçmeden önce iki üç soru soralım.",
        "Merhaba hocam, kısa tutacağız. Maç öncesi düşüncelerinizi alalım.",
        "Hocam merhaba, sizi çok tutmayacağız. Birkaç sorumuz var.",
        "Hoş geldiniz hocam, maç başlamadan kısa bir değerlendirme alalım.",
        "Merhaba hocam, maç öncesi son düşüncelerinizi merak ediyoruz.",
        "Hocam merhaba, vaktinizi almadan hızlıca birkaç soru soralım.",
        "Hocam hoş geldiniz, maç öncesi kısa bir röportaj yapalım.",
    ],
    "post_match_tunnel_interview": [
        "Hocam merhaba, maç sonu sıcağı sıcağına birkaç soru soralım.",
        "Hocam hoş geldiniz, maçla ilgili kısa birkaç sorumuz olacak.",
        "Merhaba hocam, maç sonrası ilk değerlendirmelerinizi alalım.",
        "Hocam merhaba, düdüğün hemen ardından kısa bir değerlendirme alalım.",
        "Hoş geldiniz hocam, sizi çok tutmadan maçı konuşalım.",
        "Hocam merhaba, maçla ilgili ilk izlenimlerinizi merak ediyoruz.",
        "Merhaba hocam, kısa tutacağız. Maç sonu birkaç sorumuz var.",
        "Hocam hoş geldiniz, maç sonu düşüncelerinizi alalım.",
    ],
}


def make_opening(screen: str | None, event: str | None = None, recent_path: str | None = None, rng=random) -> str:
    """Hazır listeden açılış cümlesi; son 3 kullanılan tekrar etmez."""
    lines = OPENINGS.get(screen or "", OPENINGS["press_conference"])
    recent = _load(recent_path)
    fresh = [x for x in lines if x not in recent[-3:]] or lines
    line = rng.choice(fresh)
    _save(recent_path, (recent + [line])[-RECENT_MAX:])
    return line


def make(screen: str | None, event: str | None = None, recent_path: str | None = None, rng=random) -> str:
    """Hazır listeden kapanış cümlesi; son 3 kullanılan tekrar etmez."""
    lines = CLOSINGS.get(screen or "", CLOSINGS["press_conference"])
    recent = _load(recent_path)
    fresh = [x for x in lines if x not in recent[-3:]] or lines
    line = rng.choice(fresh)
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
