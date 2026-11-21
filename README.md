# FM27 Sesli Basın Toplantısı

Football Manager 27 için sesli basın toplantısı modu. Basın toplantılarında ve saha kenarı röportajlarında:

- Oyunun basit sorularını, **maçta gerçekten yaşananlara** (goller, direkler, değişiklikler, kurtarışlar, kartlar)
  dayanan, gerçek basın toplantılarındaki gibi kısa sorulara çevirir.
- Soruyu **gazetecinin sesiyle** okur (her gazetecinin kendi sesi; toplantıyı moderatör açar ve kapatır).
- **Sesli cevabını** (Türkçe) dinler, oyundaki en uygun cevap seçeneğine eşleyip seçer; ekranda senin cevabın yazar.
- Oyun içinde küçük bir gösterge ne olduğunu söyler ("Gazeteci soruyu hazırlıyor", "Cevap için F8'e bas"...).

> Durum: geliştirme sürümü (beta). Oyun dili Türkçe olmalı.

## Nasıl çalışır
- **Eklenti** (BepInEx 6 IL2CPP, `plugin/`): oyunun arayüzündeki metinleri okur (ekran görüntüsü almaz), soruyu ve
  seçenekleri uygulamaya iletir, seçimi uygular. Maç sırasında anlatımı, skoru ve istatistikleri hafifçe kaydeder.
- **Uygulama** (Python, `app/`): soruyu yapay zekâyla üretir (Groq / Gemini, ücretsiz katmanlar), sesi üretir
  (edge-tts; isteğe bağlı Google Chirp 3 HD), cevabını yerelde yazıya döker (faster-whisper; ses bilgisayardan çıkmaz).

## Kurulum
Gereksinimler: Windows, Football Manager 27 (Steam), Python 3.12 (python.org, "py launcher" seçili),
derlemek için isteğe bağlı .NET SDK 8/9.

1. **BepInEx 6 (IL2CPP, win-x64, bleeding edge)** indir: https://builds.bepinex.dev/projects/bepinex_be
   Arşivi oyun klasörüne (`fm.exe` yanına) çıkar, oyunu **bir kez açıp kapat** (ilk açılış uzun sürer; `BepInEx\interop`
   klasörü oluşur).
2. Bu repoyu indir, klasörde PowerShell aç:
   ```
   powershell -ExecutionPolicy Bypass -File install.ps1
   ```
   Oyun farklı bir yerdeyse: `install.ps1 -GameDir "D:\SteamLibrary\steamapps\common\Football Manager 27"`.
   Betik: Python ortamını kurar, eklentiyi oyuna kopyalar, `app\settings.ini` oluşturur, anahtarları sorar,
   masaüstüne **FM27 Basın Modu** kısayolunu koyar.

## Anahtarlar (ücretsiz)
- **Gemini** (zorunlu): https://aistudio.google.com/apikey
- **Groq** (önerilir): https://console.groq.com/keys. Sorular Gemini ile üretilir; Gemini 2,5 sn içinde cevap
  vermezse Groq'a da sorulur ve önce gelen kullanılır (Gemini yoğun saatlerde yavaşlayabilir).

Kurulum betiği sorar; elle eklemek için `setx GEMINI_API_KEY "..."` ve `setx GROQ_API_KEY "..."`, sonra yeni pencere.
Anahtarlar sadece Windows kullanıcı ortam değişkeninde durur; hiçbir dosyaya yazılmaz.

## Kullanım
1. Masaüstündeki **FM27 Basın Modu** kısayolu: modu açar (BepInEx + sesli uygulama) ya da kapatır (FM normal açılır).
   FM kapalıyken açarken eklentinin yeni sürümünü de kurar.
2. FM'yi aç. Basın toplantısına / röportaja gir: soru gelir ve okunur.
3. **F8**'e bas, cevabını söyle, tekrar **F8**. Uygulama cevabını uygun seçeneğe eşler ve seçer.
4. Maçı maç ekranında izlersen maç sonu soruları o maçtaki anlara dayanır.

## Ayarlar
`app\settings.ini` (örnek: `app\settings.example.ini`): bas-konuş tuşu, mikrofon, hoparlör, okuma hızı, takip sorusu
olasılığı, saklanacak kayıt sayısı vb. Ortam değişkeni varsa o kazanır.

Yardımcı komutlar (`app` klasöründe):
- `start.bat check`: anahtarlar, yapay zekâ bağlantısı, mikrofon, hoparlör, ses.
- `start.bat devices`: mikrofon ve hoparlör listesi.
- `start.bat voices`: gazeteci seslerini dinle.
- `start.bat --text`: mikrofonsuz deneme (cevabı klavyeden yaz).

**Daha iyi sesler (isteğe bağlı, Google Chirp 3 HD):** kendi Google Cloud projende "Cloud Text-to-Speech API"yi aç,
yalnızca bu API ile sınırlı bir anahtar oluştur: `setx GOOGLE_TTS_API_KEY "..."`. Google'ın ücretsiz kotası aylık
1 milyon karakter; uygulama ayda 500 bin / günde 40 bin karakterde durur ve ücretsiz seslere geçer.

## Gizlilik ve disk
- Ekran görüntüsü alınmaz; yapay zekâya sadece metin (soru, seçenekler, maç özeti, cevabının yazısı) gider.
- Sesli cevabın: Groq anahtarı varsa yazıya dökülmesi için Groq'a gönderilir (Whisper; Türkçede çok daha doğru ve
  hızlı). İstemezsen `app\settings.ini` içinde `konusma_tanima = yerel` yap: ses bilgisayarından çıkmaz (daha az doğru).
  Groq'a ulaşılamazsa otomatik olarak bilgisayardaki modele geçilir. Anahtarlar sadece ortam değişkeninde.
- Otomatik temizlik: son 30 maç, 50 toplantı ve 15 uygulama kaydı tutulur; eski geçici dosyalar silinir.

## Sorun giderme
- **Gösterge "uygulama kapalı" diyor:** kısayolla uygulamayı başlat (pencere açık kalmalı).
- **Soru oyunun kendi sorusu kaldı:** yapay zekâ süre sınırında cevap vermedi (Groq anahtarı ekle; `start.bat check`).
- **F8 çalışmıyor / başka tuş:** `settings.ini` → `bas_konus_tusu`.
- **Yanlış mikrofon:** `start.bat devices`, sonra `settings.ini` → `mikrofon`.
- **Log:** `BepInEx\LogOutput.log` (eklenti), `app\logs\live_*.log` (uygulama).

## Geliştirme
`app` klasöründe testler: `.venv\Scripts\python -m pytest -q`. Eklentiyi derleme: `plugin\build.ps1` (oyun kapalıyken).
Belgeler: `docs/protocol.md` (eklenti-uygulama dosya protokolü), `docs/ui-map.md` (arayüz seçicileri),
`docs/press-questions.md` (gerçek basın toplantısı soru araştırması).
Repoyu klonladıktan sonra gizli anahtar engelini etkinleştir: `git config core.hooksPath .githooks`.

## Lisans
[PolyForm Noncommercial 1.0.0](LICENSE.md): kişisel ve ticari olmayan kullanım, değiştirme ve paylaşım serbest;
**ticari kullanım (kâr amaçlı satış, ücretli dağıtım vb.) yasak.** Football Manager, Sports Interactive / SEGA'nın
markasıdır; bu proje onlarla bağlantılı değildir.
