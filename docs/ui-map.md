# FM27 basın ekranları – UI Toolkit seçici haritası

Kaynak: `BepInEx\fm27pressvoice\20261119_030306\` (v0.0.3 dökümleri, class + gerçek tip var).
Gösterim: `Tip name='...' .class` — "name" `ve.name`, class `GetClassesForIteration()`.
Tüm metinler rich text içerir (`<color=..><link="0"><style="Norml">Galatasaray</style></link></color>'da`) → regex ile `<...>` sil.

## 1. Ekran türünü belirleme (MainUIDocument altında açık/görünür Panel)

| Ekran | Panel (name) | Başlık | Sayaç |
|---|---|---|---|
| Basın toplantısı (TD tanıtımı, maç öncesi, maç sonu; muhtemelen transfer) | `PressConferenceCard` (.panel--visible) | `PressInfo` altındaki ilk SIText: "Basın Toplantısı" | `SIText name='FinishedText'` → "Soru (2/6)" |
| Maç öncesi saha kenarı röportajı | `TunnelInterviewPanel` (.panel--open) | `SIText name='PanelTitleText'` → "Röportaj" | YOK |
| Maç sonu saha kenarı röportajı | `PostMatchTunnelInterviewPanel` (.panel--visible) | `PanelTitleText` → "Maç Sonrası Röportaj" | YOK |

- Toplantı türünü (tanıtım / maç öncesi / maç sonu) panel adı AYIRMIYOR → soru içeriğinden + oyun bağlamından (maç verisi, adım 6) çıkar.
- Ortak kök: `SIStyleSetter .fullscreen-meeting-with-larger-speakto`.
- Basın toplantısı başlık satırı: `PressInfo` → "Basın Toplantısı" | `"10"` + `"Gazeteci"` (gazeteci sayısı).
  Genel ruh hali: başlıktaki `SIText name='text' .body-language-*-text-colour` (ör. "Belirsiz", "Biraz Olumlu").
- Röportaj başlığı altında: rakip kulüp (`BottomInfo` içindeki SIText) + `SIText name='CompetitionName'` (lig).
- Çıkış butonu: `SIButton name='continue-button'` → `SIText name='continue-text'` ("Basın Toplantısından Çık" / "Kulübeye Git" /
  "Maç Hakkındaki Düşünceler"). Bunu TIKLAMA (toplantıyı bitirir).

## 2. Soru soran gazeteci (üst şerit, `VisualElement name='TopBar' .meetings-statement-container`)

İki dal var: `SIVisible name='IsStaff'` ve `SIVisible name='IsJournalist'`. Gazeteci sorusunda dolu olan **IsJournalist**
(IsStaff dalındaki metinler boş ''). Dolu dal içinde:
- Ad: `NameAndHierarhy` → ilk `SIText name='text' .heading-md`
- Yayın organı: `NameAndHierarhy` → `SIText name='text' .body-md.global-text-secondary`
- Ruh hali: "Ruh Hali:" etiketinden sonraki `SIText name='text' .body-language-<seviye>-text-colour`
  (seviye class'ı: `slightly-positive`, `slightly-negative`, `neutral` ...; metin: "Kısmen Olumlu", "Üzgün", "Olumsuz"...)
- **Soru metni**: `MessageActionsStreamedObjectList name='SpeechBubbleList'` → ... → `VisualElement name='BubbleBackground'
  .speech-background-type-reply` → `SIText name='text' .body-md.global-text-primary`.
  - Balon animasyonla akar (`.speakto-messages---processing`); ilk karede metin boş olabilir → metin dolup sabitlenene
    kadar bekle (2 ardışık okuma aynı).
  - Liste sanallaştırılmış (VirtualisedList); takip sorusunda birden fazla balon olabilir → SON balonu al.
  - `HumanBubbleVisible` = menajerin (bizim) balonu; `NPCBubbleVisible` = gazeteci.

## 3. Gazeteci kartları (sadece basın toplantısı; röportajda tek kart)

`WrappedObjectList name='Journalists'` → her `TemplateContainer .wrapped-object-list-item`:
- Aktif (soruyu soran) kart: `.meeting-tiles--background-active` (diğerleri `--background-inactive`)
- `VisualElement name='NonPlayerInfo'` → `SIText name='Name'`, `SIText name='Publication'`, ruh hali `SIText name='text'`
  (`.body-language-*-text-colour`).

## 4. Cevap paneli (`BindingExpect name='SpeakToContainerExpect'` → `ComponentElement name='SingleNPCPanel'`)

- Menajer: `PrimarySender` → `SIText name='Name'` (Mehmet Demir), `SIText name='Job'` (Menajer).
- Kategoriler: `StreamedObjectList name='NewsResponseOptionalButtons'` → her öğe `BindingExpect name='SpeakToOptionalActionButton'`:
  - Başlık: `SIVisible name='Header'` → `SIText name='GroupTitle'` + anlam class'ı
    `.speakto-header-positive | -neutral | -negative`.
  - Seçenekler: `StreamedObjectList name='SubActions'` → her `BindingExpect name='SpeakToMeetingAnswerActionButton'` →
    dış `SIButton name='StandardButton'` → `templateToInstantiate` → iç `SIButton name='StandardButton'
    .speakto-body-header-suggestion-button--action-secondary` → `SIText name='text' .label-md.global-text-primary` (seçenek cümlesi).
  - Hangi StandardButton'a tıklanacağı (dış/iç) adım 5'te denenecek.
- İlk öğe olarak GroupTitle'sız, devre dışı (`.unity-disabled`) bir "opsiyonel eylem" butonu gelebilir
  (`.speakto-optional-interaction-button`, büyüteç ikonu, metin boş) → kategori sayma, atla. "Ek Eylemler" ile ilişkili olabilir.

### Kategori kuralları (gözlenen)
- Adlar değişken: Olumlu/Nötr/Olumsuz, Hemfikir Ol/Nötr/Görüşe Karşı Çık, İkna Et/Nötr/Önemseme.
- Class eşlemesi 1:1 değil: "İkna Et" de `neutral` çıktı (aynı ekranda iki neutral grup).
- Sıra değişken (Olumsuz önce gelebilir), bazı kategoriler olmayabilir (TD tanıtımında Olumsuz yoktu).
- Seçenek sayısı değişken (1–4).
→ LLM'e her kategori için {ad, class, seçenekler[]} ver; eşlemeyi sıraya göre yapma.

## 5. Zamanlama / sayaç
- "Soru (x/y)": y toplantı sırasında artabilir (oyunun kendi takip sorusu 5→6 yaptı).
- 2 sn aralıklı tarama hızlı cevaplarda soru kaçırıyor → canlı modda sayaç + soru metni değişimini her karede (ucuz) izle,
  tam ağaç yürüyüşünü sadece ilgili panelde yap.

## Açık noktalar
- Oyuncu transfer/tanıtım toplantısı dökümü yok (muhtemelen `PressConferenceCard`).
- Açılır kutulu soru ve gazetecinin tekrar sorması ekranları görülmedi.
- `.speakto-optional-interaction-button` / "Ek Eylemler" ne işe yarıyor.
