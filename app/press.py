"""Basın toplantısı LLM görevleri: soru üretme ve sesli cevabı oyun seçeneğine eşleme.

Önemli: Oyunun cevap seçenekleri oyunun KENDİ sorusuna göre yazılmış. Bu yüzden ürettiğimiz soru aynı konu ve niyeti
korur (seçenekler hâlâ anlamlı kalsın), sadece maç verisi ve gazeteci kişiliğiyle zenginleştirilir.
"""
import json
import re

import config as C
from llm import ask, LLMError

EVENTS = ["manager_intro", "pre_match", "post_match", "player_signing", "other"]
SCREEN_TR = {
    "press_conference": "basın toplantısı",
    "tunnel_interview": "maç öncesi saha kenarı röportajı (maçtan hemen önce, kısa)",
    "post_match_tunnel_interview": "maç sonu saha kenarı röportajı (düdükten hemen sonra, kısa)",
}


# Gerçek basın toplantısı kalıpları (docs/press-questions.md). Kaynaklardan kopyalanmadı, kalıba göre yazıldı.
STYLE_POST = """Maç sonu:
- Genel performans: "Hocam, ilk yarıyla ikinci yarı arasında büyük fark vardı. Devre arasında ne değişti?"
- Kırılma anı: "67. dakikadaki golden sonra oyun koptu. O bölümde neler oldu?"
- Tek oyuncu: "Greenwood bugün sağ kanatta çok etkiliydi. Ona karşı neden önlem alamadınız?"
- İstatistik: "Rakibe sadece bir isabetli şut izni verdiniz. Savunma organizasyonundan memnun musunuz?"
- Değişiklik: "Yunus'u 55. dakikada oyundan aldınız. Bu değişikliğin sebebi neydi?"
- Hakem: "30. dakikadaki pozisyonda penaltı beklediniz mi?"
- Seri / puan: "Bu sonuçla liderle fark üç puana indi. Yarışı nasıl görüyorsunuz?"
- Sakatlık: "Osimhen ikinci yarıda topallayarak çıktı. Durumu hakkında bilgi var mı?"
- Devre arası: "İkinci yarıya bambaşka bir takım çıktı. Devre arasında oyunculara ne söylediniz?"
- Sonucun anlamı: "Bu deplasmanda uzun süredir kazanılamıyordu. Bu galibiyet sizin için ne ifade ediyor?"
- Sistem: "İkinci yarıda üçlü savunmaya geçtiniz. Bu kararı neye göre verdiniz?"
- Geç değişiklik: "Değişikliklerinizi 80. dakikadan sonra yaptınız. Neden daha erken müdahale etmediniz?"
- Eksik kalma: "60. dakikadan sonra 10 kişi kaldınız. Oyun planınızda neyi değiştirdiniz?"
- Golcüler: "Bugün de forvetlerinizden gol gelmedi. Bu durum sizi endişelendiriyor mu?"
- Kaçan fırsat: "Kazansanız farkı açacaktınız. Bu beraberliği kayıp olarak mı görüyorsunuz?"
- Sorumluluk: "Üst üste ikinci mağlubiyet geldi. Sorumluluğu nerede görüyorsunuz?"
- Soyunma odası: "Maçtan sonra oyunculara ne söylediniz? Soyunma odasında hava nasıldı?"
- Hak edilen sonuç: "Rakibe tek pozisyon verdiniz ama kaybettiniz. Bugün daha iyi olan takım mı kaybetti?"
- Kıl payı galibiyet: "Son dakikalarda skoru korudunuz. Bu tür zor galibiyetler takıma ne katıyor?"
- Hücum gücü: "Çok pozisyon buldunuz ama tek gol attınız. Ön tarafta daha fazla güce ihtiyacınız var mı?"
- Fikstür: "Üç gün sonra yine maçınız var. Kadroda değişiklik düşünüyor musunuz?"
SONUCA GÖRE AÇI (gerçek toplantılarda gözlenen): galibiyette sonucun anlamı, seri/rekor, öne çıkan oyuncu, puan
durumu; mağlubiyette kırılma anı, değişikliklerin zamanlaması, 10 kişi kalma, golcülerin verimi, sakatlık, sorumluluk,
hakem; beraberlikte kaçan fırsat, puan kaybı, tartışmalı pozisyon.
TOPLANTI AKIŞI (Arsenal, Real Madrid ve Süper Lig maç sonu toplantılarında gözlenen; soru sayacına göre uygula):
İLK soru sonucun anlamı / genel performans; ORTADA kırılma anı, taktik ve değişiklik, hakem, soyunma odası; SONA doğru
tek oyuncu soruları, puan durumu / hedef, sonraki maç ve fikstür.
"""

STYLE_TUNNEL_POST = """Maç sonu saha kenarı (TV/flaş) röportajı: düdükten hemen sonra, 2-3 soru, en kısa format.
Muhabir çoğu zaman önce kısa bir değerlendirme cümlesi kurar, sonra teknik direktörün yorumunu ister; suçlamaz,
konuşturur. Analiz, istatistik, uzun gerekçe yok:
- Sonuç (İLK soru, açık uçlu): "Hocam tebrikler, deplasmandan üç puanla dönüyorsunuz. Nasıl bir maçtı sizin için?"
- Sonuç (mağlubiyet): "Hocam geçmiş olsun. Maçın genelini nasıl gördünüz?"
- Kırılma anı: "İlk yarıyı iki farklı önde kapattınız, sonrası daha rahat geçti. Maçı orada mı kopardınız?"
- Geri dönüş: "Geriye düştükten sonra iyi tepki verdiniz. Devre arasında ne söylediniz?"
- Geç gol: "Son dakikada yediğiniz golle iki puan bıraktınız. O an ne hissettiniz?"
- Hakem: "67. dakikadaki pozisyonda penaltı bekliyordunuz. Siz ne gördünüz?"
- Kaçan fırsat: "Çok pozisyon buldunuz ama gol gelmedi. Bugün ne eksikti?"
- Taraftar: "Taraftarlarınıza ne söylemek istersiniz?"
- Sonraki maç: "Üç gün sonra yine sahadasınız. Oyuncuların durumu nasıl?"
AKIŞ (beIN SPORTS flaş röportajlarında gözlenen): ilk soru sonuç ve duygu; ikinci soru tek bir an (gol, hakem kararı,
değişiklik); varsa üçüncü soru taraftar, puan durumu ya da sonraki maç.
"""
STYLE_PRE = """Maç öncesi:
- Kadro: "Hocam, sakat oyuncularınızın son durumu ne? Yarın kimler forma giyebilecek?"
- Rakip: "Rakibiniz son beş maçta yenilmedi. En çok hangi yönlerine dikkat ediyorsunuz?"
- Kötü sonuç sonrası: "Geçen haftaki mağlubiyetten sonra takımın moral durumu nasıl?"
- Derbi: "Deplasmanda derbi oynayacaksınız. Atmosferin oyuncular üzerinde etkisi olur mu?"
- Oyuncu kullanımı: "Genç oyuncunuz son maçlarda süre bulamıyor. Yarın şans verecek misiniz?"
- Tekrarlayan zaaf: "Son maçlarda hep son 15 dakikada gol yediniz. Bunun üzerine çalıştınız mı?"
- Baskı: "Zirvede fark açılıyor. Bu maç sizin için final niteliğinde mi?"
- Rotasyon: "Üç gün içinde iki maç oynayacaksınız. Kadroda rotasyona gidecek misiniz?"
- Rakibin yıldızı: "Rakibin golcüsü son dört maçta beş gol attı. Onu durdurmak için özel bir planınız var mı?"
- Hakem / gündem: "Maçın hakemi açıklandı, kulübünüzden tepki geldi. Siz ne düşünüyorsunuz?"
- Tek oyuncunun durumu: "Kaptanınız dünkü antrenmana katılmadı. Yarınki maçta forma giyebilecek mi?"
- Hedef: "Ligde ilk dörde iki puan uzaktasınız. Bu haftaki maçı nasıl görüyorsunuz?"
MAÇ ÖNCESİ AĞIRLIKLAR (gerçek toplantılarda): kadro/sakatlık en sık (yaklaşık dörtte bir, genelde ilk soru), sonra
puan durumu/baskı, form ve son sonuca tepki, taktik/tekrarlayan zaaf, tek oyuncu, rakip/derbi, en sonda kulüp gündemi.
"""


STYLE_TUNNEL_PRE = """Maç öncesi saha kenarı (TV) röportajı: basın toplantısından da kısa, tek konu, maça dakikalar var:
- İlk 11: "Hocam, bugün ilk 11'de sürpriz bir tercihiniz var. Bunun sebebi ne?"
- Maç planı: "Rakip son maçlarda önde baskı yapıyor. Bugün nasıl bir oyun planıyla çıkıyorsunuz?"
- Rakibin yıldızı: "Rakibin en golcü oyuncusu bu sezon sekiz gol attı. Ona karşı özel bir önlem var mı?"
- Geçen maç: "Geçen hafta erken gol yediniz. Bugün başlangıca özellikle dikkat edecek misiniz?"
- Eksik: "Kaptanınız sakatlık nedeniyle yok. Onun yokluğunu nasıl telafi edeceksiniz?"
- Atmosfer: "Tribünler dolu, derbi havası var. Oyunculara son olarak ne söylediniz?"
- Hedef: "Bu maçı kazanırsanız zirveye yaklaşacaksınız. Takım bu baskıyı nasıl taşıyor?"
"""


def _options_text(state: dict) -> str:
    lines = []
    for c in state.get("categories", []):
        lines.append(f"[{c['index']}] {c['title']} (ton: {c.get('sentiment') or '?'})")
        for o in c.get("options", []):
            lines.append(f"    {c['index']}.{o['index']}: {o['text']}")
    return "\n".join(lines)


def _intro_example(state: dict) -> str:
    j = state.get("journalist") or {}
    name, outlet = j.get("name") or "", j.get("outlet") or ""
    if name and outlet:
        return f"Hocam merhaba, {name}, {outlet}."
    return f"Hocam merhaba, {name or outlet}." if (name or outlet) else "Hocam merhaba."


def _journalist_text(state: dict) -> str:
    j = state.get("journalist") or {}
    return f"{j.get('name') or 'Bir gazeteci'} ({j.get('outlet') or 'yayın organı bilinmiyor'}), ruh hali: {j.get('mood') or 'bilinmiyor'}"


def _history_text(history: list[dict]) -> str:
    if not history:
        return "(henüz yok)"
    return "\n".join(f"- S: {h['question']}\n  C: {h.get('display_text') or h.get('answer')}" for h in history[-6:])


_WE = re.compile(
    r"\b(biz|bizi|bize|bizim|bizce|bizler)\b|"
    r"\b(takım|oyun|maç|skor|galibiyet|mağlubiyet|yenilgi|taraftar|kulüb|aldığ|kaybettiğ|attığ|yediğ|"
    r"oyuncular|hedef|sezon)(ımız|imiz|umuz|ümüz)\w*|"
    r"\b(saha|ev|lig|forma|seri|kale|defans|hücum|orta saha)(mız|miz|muz|müz|ımız|imiz)\w*|"
    r"\b(kaybettik|yenildik|kazandık|aldık|oynadık|attık|yedik)\b", re.IGNORECASE)


_PRE_CUES = re.compile(
    r"\byarın|önümüzdeki|karşılaşacaksınız|oynayacaksınız|çıkacaksınız|gideceksiniz|maç(ı|tan)? öncesi|"
    r"maç öncesinde|hazırlıklar|hazırlanıyorsunuz|hafta sonu oynanacak|ilk 11'i(nizi)? belirle", re.IGNORECASE)
_POST_CUES = re.compile(
    r"\bbugün|kazandınız|kaybettiniz|yenildiniz|berabere kaldınız|galibiyet(in)?(in)? ardından|"
    r"mağlubiyet(in)? ardından|maçın sonucu|aldığınız (sonuç|skor)|son düdük|maç sonrası|derbiyi (kazan|kaybet)",
    re.IGNORECASE)


def meeting_kind(game_question: str) -> str | None:
    """Basın toplantısı maç öncesi mi sonrası mı? Panel ayırmıyor (docs/ui-map.md); oyunun sorusu ayırır.
    Kararsızsa None (sıradaki soruya bakılır)."""
    q = game_question or ""
    pre, post = bool(_PRE_CUES.search(q)), bool(_POST_CUES.search(q))
    return "pre" if pre and not post else "post" if post and not pre else None


_GAME_STATS = re.compile(r"\b\d{1,2},\d{1,2}\b(?!\s*(milyon|milyar|bin|M\b|€|euro|sterlin|yaş))|reyting|\bxG\b|beklenen gol|\bnot(u|unu|uyla)?\s+al", re.IGNORECASE)


def cites_game_stats(q: str) -> bool:
    """FM'ye özgü analiz sayısı (reyting '6,2', xG) var mı? Gerçek muhabir bunları söylemez (2026-11-21 testi)."""
    return bool(_GAME_STATS.search(q or ""))


def speaks_as_fan(q: str) -> bool:
    """Gazeteci kulüp adına 'biz' diye konuşuyor mu? (taraftar ağzı)"""
    return bool(_WE.search(q or ""))


def generate_question(state: dict, match: dict | None = None, history: list[dict] | None = None,
                      introduce: bool = False) -> dict:
    """{"question": str, "event": str}. LLM başarısızsa oyunun kendi sorusu döner.
    introduce: bu gazetecinin bu toplantıdaki ilk sorusu (kısa tanıtımla başlar)."""
    game_q = state.get("game_question") or ""
    prev = state.get("previous_npc_bubbles") or []
    current = bool(match) and not any(str(k).startswith("GECEN_MAC") for k in match)   # bu maçın verisi mi
    post = ((current and state.get("event_hint") != "pre_match") or state.get("screen") == "post_match_tunnel_interview"
            or state.get("event_hint") == "post_match")
    pre = state.get("screen") == "tunnel_interview" or state.get("event_hint") == "pre_match"
    tunnel_pre = state.get("screen") == "tunnel_interview"
    if tunnel_pre:
        post = False                               # geçen maç verisi olsa bile bu bir maç öncesi röportajı
    tunnel_post = state.get("screen") == "post_match_tunnel_interview"
    examples = (STYLE_TUNNEL_PRE if tunnel_pre else STYLE_TUNNEL_POST if tunnel_post else STYLE_POST if post
                else STYLE_PRE if pre else STYLE_POST + "\n" + STYLE_PRE)
    prompt = f"""GOREV: SORU
Football Manager kariyerinde Türkçe bir {SCREEN_TR.get(state.get('screen'), 'basın etkinliği')} var. Sen gerçek bir Türk spor
muhabirisin: {_journalist_text(state)}. Görevin oyunun sorusunu, GERÇEK basın toplantılarında sorulan bir soru gibi
yeniden yazmak. Rol yapma, tiyatro yapma: gerçek muhabirler kısa konuşur, bir olgu söyler, soruyu sorar.
Teknik direktör: {state.get('manager_name') or 'menajer'}. {('Rakip: ' + state['opponent'] + '. ') if state.get('opponent') else ''}{('Organizasyon: ' + state['competition'] + '.') if state.get('competition') else ''}
Soru sayacı: {state.get('question_index') or '-'}/{state.get('question_total') or '-'}.

Oyunun orijinal sorusu: "{game_q}"
{('Aynı gazetecinin önceki sözleri: ' + ' / '.join(prev)) if prev else ''}

Oyundaki cevap seçenekleri (teknik direktör bunlardan birine denk gelen bir cevap verecek):
{_options_text(state)}

Maç verisi (son oynanan maç; yoksa kullanma, ASLA veri uydurma):
{json.dumps(match, ensure_ascii=False) if match else '(veri yok)'}
Oyun ekranından bağlam (tarih, sonraki maç, son haber; soruyla ilgisizse kullanma):
{json.dumps(state.get('context'), ensure_ascii=False) if state.get('context') else '(yok)'}

Bu toplantıda şimdiye kadar:
{_history_text(history or [])}

GERÇEK BASIN TOPLANTISI SORULARI (üslup örnekleri; kalıbı al, kelimesi kelimesine kopyalama):
{examples}

Kurallar:
1. KONU: orijinal sorunun konusunu ve niyetini koru; cevap seçenekleri senin sorun için de anlamlı kalmalı.
2. SORU TÜRÜ VE VERİ: önce yukarıdaki gerçek soru türlerinden orijinal soruya uyanı seç (sonucun anlamı, kırılma anı,
   tek oyuncu, değişiklik, hakem, puan durumu, sorumluluk...). Maç verisi sorunun DOĞRU olmasını sağlar, sorunun konusu
   olmak zorunda değildir: seçtiğin tür gerektiriyorsa en fazla TEK olgu kullan (gol dakikası, golcü, kart, penaltı,
   oyuncu değişikliği, sakatlık, skor, seri, puan durumu; istatistik ancak TV'de söylenen basitlikteyse: şut, isabetli
   şut, topla oynama). Gerçek muhabirler FM reyting puanını ("6,2 puan/not"), xG'yi, katedilen mesafeyi, pas yüzdesini
   SÖYLEMEZ: bunları soruya yazma; reyting sadece kimin öne çıktığını/kötü oynadığını seçmene yarar ("Greenwood bugün
   sağ kanatta çok etkiliydi"). Konu tekrarı yok: "Bu toplantıda şimdiye kadar" kısmında işlenen gol, oyuncu ya da
   konuyu yeniden sorma, başka bir türe geç. Veride OLMAYAN dakika, isim, sayı ASLA uydurma. Skoru olduğu
   gibi yaz ("1-4"), farkı kendin hesaplama. Veri son oynanan maça aittir; toplantı maç öncesiyse "geçen maç" diye an.
   Oyuncuların yanındaki kod takımını gösterir; olayı doğru takıma bağla ("teknik_direktorun_takimi" senin muhatabının
   takımıdır, rakibin golünü ona mal etme). Anlatım satırlarını aynen kopyalama, kendi düz cümlenle söyle.
   "mac_sonu_ekrani_metni" varsa golcüleri, dakikaları ve istatistikleri ÖNCE oradan oku (en güvenilir kaynak).
   Golcü "bilinmiyor" ise golü oyuncuya bağlama, takım ve dakikayla an ("2. dakikadaki golünüz"); asist yapanı golcü sanma.
   "sonuc_teknik_direktor_icin" varsa sonucu ondan al (galibiyet/mağlubiyet/beraberlik ve skor), başka skor yazma.
   Maç sonu etkinliğinde maç BUGÜN oynandı: "dün", "geçen hafta" deme. İstatistiklerde "siz" = teknik direktörün
   takımı, "rakip" = karşı takım; karşılaştırmayı buna göre yap.
   Her golün "kimin_golu" alanına uy: "RAKİP attı" yazıyorsa o gol teknik direktörün YEDİĞİ goldür ("19. dakikada
   yediğiniz gol"), ona ASLA "golünüz" deme. Oyunun orijinal sorusundaki olgular (golcü, oyuncu adı, sonuç) oyunun
   kendi verisidir ve doğrudur: onlarla çelişme, onları değiştirme.
   Penaltı, kırmızı kart, VAR, sakatlık, bir oyuncunun oynamadığı/eksik olduğu gibi olayları SADECE veride ya da
   oyunun sorusunda açıkça yazıyorsa an; yoksa hiç anma. Ara skoru gollerdeki "bu_golden_sonra" alanından al.
   TARAF: soru teknik direktörün KENDİ takımına odaklanır (attıkları/yedikleri goller, kendi kaçan fırsatları, kendi
   oyuncuları, kendi kararları). Rakibin pozisyonunu sadece "rakip_tartismali_anlar" varsa sor; o zaman da kararı
   sor ("Sizce o pozisyon penaltı mıydı?"), rakibin kaçırdığı sıradan bir şutu sorma.
3. ÜSLUP: 1-2 kısa cümle, en fazla 25 kelime. Önce olgu, sonra soru ("... nasıl değerlendiriyorsunuz?", "... neden
   tercih ettiniz?", "... son durumu ne?", "... olacak mı?"). Sıfat yağmuru, metafor, dramatik anlatım YOK
   ("havalara uçurdu", "acı gerçekler", "muhteşem zafer", "derinden sarstı" gibi ifadeler yok).
4. TAVIR: ruh hali gazetecinin teknik direktöre bakış AÇISIDIR, duygusu değil. Olumlu muhabir iyi giden bir şeyi,
   eleştirel muhabir aksayan bir şeyi sorar; ikisi de düz ve kibar konuşur. Kulüp adına "biz/takımımız" deme,
   "takımınız/siz" de. Hakaret, alay, suçlama, provokasyon ve söylenmemiş sözü atfetmek yok.
5. {('Bu senin bu toplantıdaki İLK sorun: kısa bir açılışla başla. Türkiye usulü: "' + _intro_example(state) + '" gibi; galibiyet sonrasıysa "Hocam tebrikler", mağlubiyet sonrasıysa "Hocam geçmiş olsun" da diyebilirsin. Sonra doğrudan soru.') if introduce else 'Kendini TANITMA, selamlama yapma; gerekiyorsa sadece "Hocam" diye başla.'}
6. Teknik direktör bu toplantıda bir soruyu cevaplamak istemediyse o konunun üstüne gitme. Oyun soruyu yineliyorsa
   ("Sorumu yineliyorum") asıl soruyu kısaca, nazikçe tekrar sor; önceki cevabı yorumlama.
7. Sesli okunacak düz Türkçe; etiket, emoji, tırnak yok.
8. Etkinlik türünü tahmin et: {EVENTS} (yeni kulübe tanıtım = manager_intro, transfer tanıtımı = player_signing).

Sadece JSON döndür: {{"question": "...", "event": "..."}}"""
    try:
        r = ask(prompt, task="question", budget=C.QUESTION_BUDGET)
        q = (r.get("question") or "").strip()
        if speaks_as_fan(q):                       # taraftar ağzı: bir kez düzelttir
            print(f"  [press] 'biz' dili, düzeltiliyor: {q}")
            fix = ask(prompt + f'\n\nÖNCEKİ DENEMEN HATALIYDI ("{q}"): kulüp adına "biz/bizim/-ımız" dili kullandın. '
                      'Tarafsız muhabir olarak "siz/takımınız" diliyle yeniden yaz. Sadece JSON.', task="question",
                      budget=4)
            q2 = (fix.get("question") or "").strip()
            if q2 and not speaks_as_fan(q2):
                q, r = q2, fix
        if cites_game_stats(q):                    # reyting/xG: bir kez gerçek muhabir diliyle yeniden yazdır
            print(f"  [press] oyun istatistiği (reyting/xG), düzeltiliyor: {q}")
            fix = ask(prompt + f'\n\nÖNCEKİ DENEMEN HATALIYDI ("{q}"): reyting puanı ya da xG söyledin; gerçek muhabir '
                      'bunları söylemez. Aynı konuyu sayısız, düz cümleyle yeniden yaz. Sadece JSON.', task="question",
                      budget=4)
            q2 = (fix.get("question") or "").strip()
            if q2 and not cites_game_stats(q2) and not speaks_as_fan(q2):
                q, r = q2, fix
        ev = r.get("event") if r.get("event") in EVENTS else (state.get("event_hint") or "other")
        if not q:
            raise LLMError("boş soru")
        return {"question": q, "event": ev, "source": "llm"}
    except (LLMError, AttributeError) as e:
        print(f"  [press] soru üretilemedi, oyunun sorusu kullanılacak: {e}")
        return {"question": game_q, "event": state.get("event_hint") or "other", "source": "game"}


_REFUSAL = re.compile(
    r"yorum yok|yorum yapmayaca|yorum yapmak istemiyor|cevap vermeyece|cevap vermek istemiyor|yan[ıi]t vermeyece|"
    r"yan[ıi]t vermek istemiyor|s[ıi]radaki soru|devam edelim|ge[cç]elim|bu kadar|konu kapan|"
    r"(bu|o) konuya girmeyece|konu[sş]mak istemiyor|cevab[ıi]m yok|s[oö]yleyece[gğ]im (bir )?[sş]ey yok",
    re.IGNORECASE)


def is_refusal(answer: str) -> bool:
    """Teknik direktör cevap vermek istemiyor / konuyu kapatıyor mu? (takip sorusu sorulmaz)"""
    return bool(_REFUSAL.search(answer or ""))


def is_game_repeat(state: dict) -> bool:
    """Oyunun kendi tekrar sorusu ("Sorumu yineliyorum ...")."""
    q = (state.get("game_question") or "").lower()
    return "yineliyorum" in q or "tekrar soruyorum" in q


def _fallback_choice(state: dict) -> tuple[int, int]:
    """LLM yoksa: ilk 'neutral' kategori, yoksa ilk seçenekli kategori."""
    cats = [c for c in state.get("categories", []) if c.get("options")]
    for c in cats:
        if c.get("sentiment") == "neutral":
            return c["index"], 0
    return (cats[0]["index"], 0) if cats else (0, 0)


_WORD = re.compile(r"[a-zçğıöşüâîû]+")
_FILLER = re.compile(r"\b(ı+|e+h?|ee+|hı+|şey|yani|işte)\b[,.]?\s*", re.IGNORECASE)


def adds_content(said: str, shown: str) -> bool:
    """Ekrana yazılacak metin, söylenmeyen fikir ekliyor mu? Söylenenlerde (4 harflik kök eşleşmesiyle) karşılığı
    olmayan kelime sayısı 4'ü ve metnin %35'ini aşarsa evet. Duyma hatası düzeltmesi birkaç kelimede kalır."""
    low = lambda s: (s or "").casefold().replace("i̇", "i")
    said_roots = {w[:4] for w in _WORD.findall(low(said))}
    shown_words = [w for w in _WORD.findall(low(shown)) if len(w) > 2]
    novel = [w for w in shown_words if w[:4] not in said_roots]
    return len(novel) >= 4 and len(novel) > 0.35 * max(1, len(shown_words))


def _minimal_clean(answer: str) -> str:
    """LLM metni güvenilmezse: söyleneni dolgu kelimeleri atılmış haliyle göster (hiçbir şey ekleme)."""
    t = re.sub(r"\s+", " ", _FILLER.sub("", answer or "")).strip(" ,")
    if t and t[-1] not in ".!?":
        t += "."
    return t[:1].upper() + t[1:] if t else (answer or "").strip()


def classify_answer(state: dict, question: str, answer: str, want_follow_up: bool = False) -> dict:
    """{"category_index", "option_index", "display_text", "follow_up", "reason", "source"}"""
    prompt = f"""GOREV: SINIFLANDIR
Football Manager basın etkinliği. Gazeteci ({_journalist_text(state)}) sordu:
"{question}"

Teknik direktörün SESLİ cevabı (konuşmadan metne çevrildi, yazım/duyma hataları olabilir):
"{answer}"

Oyundaki cevap seçenekleri (kategori.seçenek):
{_options_text(state)}

Yapılacak:
1. Cevabın anlamına ve tonuna EN YAKIN kategoriyi ve o kategorideki en yakın seçeneği seç. Kategori adına göre değil
   anlama göre seç (ör. "Hemfikir Ol" = gazeteciye katılmak). Cevap geçiştirme/yorum yapmama ise nötr olanı seç.
2. display_text: cevabı ekranda gösterilecek şekilde temizle: duyma hatalarını düzelt, "ııı, yani, şey" gibi dolguları at,
   anlamı ve birinci tekil şahıs anlatımı KORU, yeni fikir ekleme, en fazla 45 kelime, düzgün Türkçe noktalama.
   Seçtiğin seçeneğin cümlelerini display_text'e KOPYALAMA ya da karıştırma: ekranda sadece teknik direktörün
   kendi söyledikleri durur (söylemediği tebrik, özür, övgü vb. ekleme).
3. {'follow_up: SADECE cevap somut ve açıksa, aynı gazetecinin doğal, dostça, kısa (en fazla 18 kelime) bir merak sorusu. Teknik direktör cevap vermek istemediyse, yorum yapmadıysa, geçiştirdiyse, rahatsız olduysa ya da konuyu kapattıysa: null. Asla üsteleme, "kaçıyorsunuz" deme, aynı soruyu tekrar sorma. Emin değilsen null.' if want_follow_up else 'follow_up: null.'}

Sadece JSON döndür: {{"category_index": 0, "option_index": 0, "display_text": "...", "follow_up": null, "reason": "kısa gerekçe"}}"""
    cats = {c["index"]: c for c in state.get("categories", [])}
    try:
        r = ask(prompt, task="classify", budget=C.CLASSIFY_BUDGET)
        ci, oi = int(r.get("category_index")), int(r.get("option_index", 0))
        if ci not in cats or not cats[ci].get("options"):
            raise LLMError(f"geçersiz category_index {ci}")
        if not 0 <= oi < len(cats[ci]["options"]):
            oi = 0
        text = (r.get("display_text") or "").strip() or answer.strip()
        if adds_content(answer, text):             # söylenmeyen söz eklenmiş: söyleneni göster
            print(f"  [press] ekran metni söylenmeyen söz ekliyordu, cevabın kendisi gösterilecek: {text}")
            text = _minimal_clean(answer)
        fu = r.get("follow_up") if want_follow_up else None
        return {"category_index": ci, "option_index": oi, "display_text": text,
                "follow_up": (fu or None) and str(fu).strip(), "reason": r.get("reason"), "source": "llm"}
    except (LLMError, AttributeError, TypeError, ValueError) as e:
        ci, oi = _fallback_choice(state)
        print(f"  [press] sınıflandırılamadı, yedek seçim {ci}.{oi}: {e}")
        return {"category_index": ci, "option_index": oi, "display_text": answer.strip(),
                "follow_up": None, "reason": f"yedek: {e}", "source": "fallback"}
