# FM27 Press Voice

FM27 basın toplantılarını ve saha kenarı röportajlarını sesli hale getirir:
1. Eklenti, gazetecinin sorusunu ve cevap seçeneklerini okur.
2. App, soruyu maç bağlamıyla yeniden yazar ve Türkçe seslendirir.
3. Kullanıcı bas-konuş ile cevap verir.
4. App, cevabı oyundaki en yakın seçeneğe eşler; eklenti o seçeneği tıklar ve ekrandaki metni kullanıcının sözleriyle değiştirir.

Bağlam, kararlar ve yapılacaklar için `CLAUDE.md`'ye bak. Protokol `docs/protocol.md`'de, ekran haritası `docs/ui-map.md`'de.

| Klasör | İçerik |
|---|---|
| `plugin/` | BepInEx 6 IL2CPP eklentisi (C#) |
| `app/` | Python yan uygulama (LLM, TTS, STT) |
| `tools/InteropInspect` | Oyunun interop DLL'lerinde tip/üye arar |
| `tools/DumpReplay` | Eklentinin okuyucusunu UI dökümleri üzerinde oyunsuz çalıştırır |

## Kurulum
**Eklenti** (oyun kapalıyken): `plugin\build.ps1`. Varsayılan oyun yolu Steam; farklıysa `-GameDir "..."` ver.

**App** (bir kez):
```
cd app
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
setx GEMINI_API_KEY "<aistudio.google.com/apikey adresinden alınan anahtar>"
```
`setx`'ten sonra yeni bir terminal aç. Yedek sağlayıcı olarak `setx GROQ_API_KEY "..."` de verilebilir.

## Kullanım (`app\start.bat`)
| Komut | Ne yapar |
|---|---|
| `start.bat check` | Anahtarlar, Gemini modelleri, mikrofon, TTS ve eklenti durumunu kontrol eder |
| `start.bat` | Canlı mod: oyunu aç, app'i başlat, basın ekranına gir |
| `start.bat --text` | Canlı mod, cevap mikrofon yerine klavyeden |
| `start.bat sim` | Oyunsuz deneme: gerçek dökümlerden 11 soru, sahte eklenti, klavye |
| `start.bat sim --voice` | Oyunsuz deneme, sesli |
| `.venv\Scripts\python -m pytest tests` | Testler |

**Gazeteci sesleri:** Her gazetecinin kendi sesi var (kadın/erkek, adına göre). `start.bat voices` tüm sesleri sırayla
çalar; beğenmediklerini `setx FM_VOICES_OFF "brian,thalita"` gibi kapat. Moderatör sesi `FM_MODERATOR_VOICE`.

**Bas-konuş:** Varsayılan F8 (`FM_HOTKEY` ile değişir); kaydı başlatmak için bas, bitirmek için tekrar bas. Bip sesi kaydın başladığını/bittiğini bildirir.
Cevap beklenirken tuş oyuna iletilmez. Değiştirmek için `set FM_HOTKEY=f8`.

**Diğer ayarlar:**
- App: `app/config.py` ve ortam değişkenleri (`FM_LLM_PROVIDERS`, `GEMINI_MODEL`, `WHISPER_MODEL`, `FM_FOLLOW_UP_PROB`...).
- Eklenti: `BepInEx\config\fm27pressvoice.cfg`, `[Bridge]` bölümü (`AutoClick`, `ClickTarget`, `ClickMethod`...).

## İlk oyun testi (kontrol listesi)
1. **Eklenti yükleniyor mu:** Oyunu aç; `BepInEx\LogOutput.log` içinde `Loading [FM27 Press Voice 0.1.1]` ve `FM27PressVoice yüklendi.` olmalı.
2. **Okuma (app kapalı):** Bir basın toplantısına gir. `BepInEx\fm27pressvoice\press_state.json` oluşmalı ve içinde
   soru, gazeteci ve kategoriler doğru görünmeli. Log'da `Bridge` hatası olmamalı.
3. **Uçtan uca, klavyeyle:** `start.bat --text` çalıştır.
   - Soru balonu bizim soruyla değişmeli.
   - Cevabı yazınca doğru seçenek tıklanmalı ve menajer balonunda senin cevabın görünmeli.
   - Eklenti tıklamanın etkisini kontrol eder; etkisizse diğer buton/yöntem kombinasyonlarını kendisi dener
     ve çalışanı cfg'ye yazar. Log'da `Tıklama denendi` / `tıklama doğrulandı` satırlarına bak.
4. **Sesli:** `start.bat`. F8 ile konuş. Basın ekranında üstteki şerit ne yapıldığını gösterir.
5. **Maç verisi:** Maç bitince istatistik ekranını aç; `ui_dump_N_mac.txt` oluşmalı. Bir ekran görüntüsü de at.

## Modu aç/kapat (masaüstü kısayolu)
Masaüstündeki **FM27 Basın Modu** kısayolu `mod-toggle.ps1` dosyasını çalıştırır:
- Kapalıyken tıklanırsa BepInEx'i etkinleştirir (`doorstop_config.ini` içinde `enabled = true`) ve sesli uygulamayı ayrı pencerede başlatır.
- Açıkken tıklanırsa uygulamayı kapatır ve BepInEx'i devre dışı bırakır. FM eklentisiz, normal açılır.
- FM açıkken yapılan değişiklik oyun yeniden başlatılınca geçerli olur.
- FM kapalıyken açarken, derlenmiş eklenti oyundakinden yeniyse onu da kurar (`pluginuild.ps1` gerekmez).
Kısayolu yeniden oluşturmak için: `powershell -ExecutionPolicy Bypass -File mod-toggle.ps1 -InstallShortcut`

## Katkı
Anahtarlar sadece ortam değişkeninde tutulur (`setx GEMINI_API_KEY ...`, isteğe bağlı `setx GOOGLE_TTS_API_KEY ...`).
Repoyu klonladıktan sonra gizli anahtar engelini etkinleştir: `git config core.hooksPath .githooks`
