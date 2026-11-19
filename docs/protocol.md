# Eklenti <-> App protokolü (v1)

Klasör: `<FM27>\BepInEx\fm27pressvoice\` (dökümlerin oturum klasörleri de burada).
Tüm dosyalar UTF-8 JSON, **atomik** yazılır (önce `*.tmp`, sonra yeniden adlandırma). Okuyan taraf okuma hatasında
(dosya kilitli / yarım) bir sonraki turda tekrar dener.

## 1. press_state.json — eklenti yazar (içerik değişince, ~0.25 sn kontrol)

```jsonc
{
  "v": 1,
  "seq": 42,                       // her yazımda +1
  "time": "2026-11-19T03:12:39",
  "active": true,                  // basın ekranı açık mı (false ise aşağıdakiler boş)
  "screen": "press_conference",    // press_conference | tunnel_interview | post_match_tunnel_interview
  "event_hint": null,              // tunnel_interview -> "pre_match", post_match_tunnel_interview -> "post_match",
                                   // press_conference -> null (tanıtım/maç öncesi/maç sonu/transfer: app çıkarır)
  "question_id": "a1b2c3d4e5f6",   // gazeteci + oyunun orijinal sorusu + sayaçtan hash; soru değişince değişir
  "ready": true,                   // soru metni sabitlendi ve en az bir seçenek var
  "question_index": 2, "question_total": 6,   // röportajda null; total toplantı sırasında ARTABİLİR
  "title": "Basın Toplantısı",     // veya "Röportaj" / "Maç Sonrası Röportaj"
  "opponent": null,                // röportajda rakip kulüp
  "competition": null,             // röportajda lig/kupa
  "overall_mood": "Belirsiz",      // basın toplantısı genel havası (varsa)
  "manager_name": "Mehmet Demir",
  "journalist": {"name": "Óscar Sánchez", "outlet": "İspanya Futbol Dergisi",
                 "mood": "Kısmen Olumlu", "mood_class": "slightly-positive", "active": true},
  "journalists": [ { ...aynı alanlar... } ],   // basın toplantısındaki tüm kartlar
  "game_question": "Neden özellikle Mbappé? Onu diğerlerinden daha tehlikeli yapan şey ne sizce?",  // etiketsiz
  "game_question_raw": "Neden özellikle <link=\"0\">...",
  "previous_npc_bubbles": ["..."], // aynı gazetecinin önceki balonları (takip sorusu bağlamı)
  "categories": [
    {"index": 0, "title": "Olumsuz", "sentiment": "negative",   // sentiment: speakto-header-<x> class'ından
     "options": [{"index": 0, "text": "Diğer oyunculardan kat be kat...", "enabled": true}, ...]},
    {"index": 1, "title": "Olumlu", "sentiment": "positive", "options": [...]}
  ],
  "override_question_id": "a1b2c3d4e5f6",   // soru metni şu an bizim metnimizle değiştirilmiş mi
  "last_applied": {"question_id": "...", "ok": true, "action": "answer", "detail": "Submit outer", "time": "..."},
  "match": null                    // adım 6 (oyundan maç verisi); şimdilik null
}
```

Notlar:
- Kategori adı, sırası, sayısı ve seçenek sayısı değişkendir (Olumlu/Nötr/Olumsuz, Hemfikir Ol/Görüşe Karşı Çık,
  İkna Et/Önemseme...). `sentiment` yardımcıdır, 1:1 değildir (İkna Et = neutral görüldü). Eşlemeyi `index` ile yap.
- Soru metni bizim metnimizle değiştirilmiş olsa bile `game_question` ORİJİNAL soruyu verir.

## 2. press_question.json — app yazar (oyunun sorusunu değiştirmek için)

```json
{"v": 1, "question_id": "a1b2c3d4e5f6", "text": "Bizim ürettiğimiz soru"}
```
Eklenti `question_id` güncel soruyla eşleşirse ekrandaki soru balonunu bu metinle değiştirir (oyun yeniden yazarsa
tekrar uygular), dosyayı siler. Eşleşmezse (bayat) siler, uygulamaz. Sonuç `last_applied`'da (`action: "question"`).

## 3. press_answer.json — app yazar (cevabı uygulamak için)

```json
{"v": 1, "question_id": "a1b2c3d4e5f6", "category_index": 1, "option_index": 0,
 "display_text": "Kullanıcının temizlenmiş cevabı", "click": true}
```
Eklenti: seçeneğin ekran metnini `display_text` ile değiştirir (ReplaceAnswerText açıksa), `click` ve AutoClick açıksa
seçeneği tıklar; ardından menajer balonunda orijinal seçenek metni görünürse onu da `display_text` ile değiştirir.
Oyun etkisi seçilen kategoriden/seçenekten gelir. Sonuç `last_applied`'da (`action: "answer"`):
önce `"tıklandı (outer/submit), doğrulanıyor"`, sonra `"tıklama doğrulandı (...): outer/submit"` ya da hata.
**Tıklama doğrulama:** 2 sn içinde soru değişmez / menajer balonu belirmezse eklenti sıradaki kombinasyonu dener
(outer/inner × submit/invoke/navsubmit). Çalışan kombinasyon cfg'ye (`ClickTarget`, `ClickMethod`) kaydedilir.

## 4. app_status.json — app yazar (oyun içi gösterge için, ~1 sn'de bir yenilenir)
```json
{"v": 1, "time_ms": 1763550000000, "phase": "waiting_key", "text": "Cevap için F8'e bas", "hotkey": "F8"}
```
- `phase`: idle | generating | speaking | waiting_key | recording | transcribing | classifying | applying | manual
- `text`: eklentinin olduğu gibi gösterdiği Türkçe metin (metni app belirler, eklenti yorumlamaz).
- Eklenti `time_ms` 4 sn'den eskiyse ya da dosya yoksa "uygulama kapalı" gösterir. App çıkarken dosyayı siler.
- Gösterge (Overlay.cs, IMGUI): basın ekranında üst ortada renkli şerit (kayıt kırmızı, senin sıran turuncu, gazeteci
  mavi). Sol altta küçük rozet sadece oyun açılınca 12 sn ve app açılıp kapanınca 8 sn görünür.
  Ayarlar `[Overlay] Enabled`, `ShowBadge`, `BadgeSeconds`.

## Eklenti ayarları (`BepInEx\config\fm27pressvoice.cfg`, [Bridge])
- `Enabled` (true): durum okuma/yazma.
- `PollSec` (0.25): kontrol aralığı.
- `ReplaceQuestion` (true), `ReplaceAnswerText` (true), `AutoClick` (true).
- `ClickTarget` (`outer` | `inner`) + `ClickMethod` (`submit` | `invoke` | `navsubmit`): İLK denenecek kombinasyon
  (`SIButton.Submit()` / `Button.clickable.Invoke(null)` / `NavigationSubmitEvent`). Etkisizse diğerleri otomatik
  denenir; çalışan kombinasyon buraya otomatik yazılır.
