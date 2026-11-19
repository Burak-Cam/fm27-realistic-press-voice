using System;
using System.IO;
using System.Text.Json;
using BepInEx;
using UnityEngine;
using UnityEngine.UIElements;

namespace FM27PressVoice;

/// Oyun içi durum göstergesi. App'in yazdığı app_status.json'u okur:
///  - basın ekranında üst ortada büyük şerit: "Gazeteci soruyu hazırlıyor...", "Cevap için F8'e bas", "Kayıt..." vb.
///  - diğer ekranlarda sol altta küçük rozet: modun açık olduğunu ve app'in çalışıp çalışmadığını gösterir.
/// FM'nin kendi arayüzü gibi UI Toolkit kullanır (IMGUI bu oyunda stripped: GUI.DrawTexture "Method unstripping failed").
/// Kullanılan API'ler tools/InteropInspect --stripped ile kontrol edildi.
internal static class Overlay
{
    static string StatusPath => Path.Combine(Paths.BepInExRootPath, "fm27pressvoice", "app_status.json");
    const long AliveMs = 4000;   // app her ~1 sn'de yazar; bu kadar süre yazmazsa kapalı say
    const string ElementName = "FM27PressVoiceOverlay";

    static float _nextRead, _nextFront;
    static float _badgeUntil = -1f;   // rozet bu zamana kadar görünür (açılışta ve app açılıp kapanınca)
    static bool? _lastAlive;
    static DateTime _lastWrite;
    static string _phase = "", _text = "";
    static long _timeMs;
    static int _readErrors;
    static bool _failed;

    static Label _label;
    static string _shownText;
    static int _shownMode = -1;   // 0 gizli, 1 rozet, 2 şerit
    static Color _shownBg;

    /// Ticker.Update'ten her karede çağrılır (dosyayı ve arayüzü seyrek günceller).
    public static void Tick()
    {
        if (_failed) return;
        if (!Plugin.OverlayEnabled.Value) { Hide(); return; }
        float now = Time.unscaledTime;
        if (now < _nextRead) return;
        _nextRead = now + 0.2f;
        ReadStatus();
        try { Render(now); }
        catch (Exception e)
        {
            _failed = true;   // bu oyunda çalışmıyorsa sessizce kapan (oyunu etkilemesin)
            Plugin.Instance.Log.LogError($"Gösterge kapatıldı: {e.GetType().Name}: {e.Message}");
            try { _label?.RemoveFromHierarchy(); } catch { }
        }
    }

    static void ReadStatus()
    {
        try
        {
            var path = StatusPath;
            if (!File.Exists(path)) { _timeMs = 0; return; }
            var mtime = File.GetLastWriteTimeUtc(path);
            if (mtime == _lastWrite) return;
            using var fs = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            using var doc = JsonDocument.Parse(fs);
            var r = doc.RootElement;
            _phase = r.TryGetProperty("phase", out var p) ? p.GetString() ?? "" : "";
            _text = r.TryGetProperty("text", out var t) ? t.GetString() ?? "" : "";
            _timeMs = r.TryGetProperty("time_ms", out var tm) ? tm.GetInt64() : 0;
            _lastWrite = mtime;
        }
        catch (Exception e)
        {
            // yarım yazılmış dosya: sonraki turda tekrar dene
            if (++_readErrors == 5) Plugin.Instance.Log.LogWarning($"app_status.json okunamıyor: {e.Message}");
        }
    }

    static bool AppAlive => _timeMs > 0 && DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - _timeMs < AliveMs;

    static void Render(float now)
    {
        var root = Bridge.Root;
        if (root == null) return;
        bool alive = AppAlive;
        float secs = Plugin.OverlayBadgeSeconds.Value;
        if (_badgeUntil < 0f) _badgeUntil = now + secs;                        // oyun arayüzü ilk yüklendi
        else if (_lastAlive.HasValue && _lastAlive.Value != alive) _badgeUntil = now + Mathf.Min(secs, 8f);   // app açıldı/kapandı
        _lastAlive = alive;

        int mode; string text; Color bg;
        if (Bridge.InPress)
        {
            mode = 2;
            text = "Sesli Basın  |  " + (alive ? _text : "Uygulama kapalı: masaüstünden 'FM27 Basın Modu' kısayolunu aç");
            bg = alive ? PhaseColor(_phase) : new Color(0.55f, 0.1f, 0.1f, 0.92f);
        }
        else if (Plugin.OverlayBadge.Value && now < _badgeUntil)
        {
            mode = 1;
            text = alive ? "Sesli Basın: hazır" : "Sesli Basın: uygulama kapalı";
            bg = alive ? new Color(0.1f, 0.35f, 0.15f, 0.8f) : new Color(0.45f, 0.1f, 0.1f, 0.8f);
        }
        else { Hide(); return; }

        if (_label == null) Create();
        if (_label.parent == null || _label.parent.Pointer != root.Pointer)
        {
            _label.RemoveFromHierarchy();
            root.Add(_label);
            _shownMode = -1;
        }
        if (now >= _nextFront) { _nextFront = now + 1f; _label.BringToFront(); }   // açılan ekranların üstünde kal

        if (mode != _shownMode) { ApplyLayout(mode); _shownMode = mode; }
        if (text != _shownText) { _label.text = text; _shownText = text; }
        if (bg != _shownBg) { _label.style.backgroundColor = new StyleColor(bg); _shownBg = bg; }
    }

    static void Create()
    {
        _label = new Label("Sesli Basın");
        _label.name = ElementName;
        _label.pickingMode = PickingMode.Ignore;               // tıklamaları engellemesin
        var s = _label.style;
        s.position = new StyleEnum<Position>(Position.Absolute);
        s.color = new StyleColor(Color.white);
        s.paddingLeft = new StyleLength(14f); s.paddingRight = new StyleLength(14f);
        s.paddingTop = new StyleLength(6f); s.paddingBottom = new StyleLength(6f);
        s.borderTopLeftRadius = new StyleLength(6f); s.borderTopRightRadius = new StyleLength(6f);
        s.borderBottomLeftRadius = new StyleLength(6f); s.borderBottomRightRadius = new StyleLength(6f);
        // isteğe bağlı görünüm: başarısız olursa göstergeyi kapatma
        Optional(() => s.unityTextAlign = new StyleEnum<TextAnchor>(TextAnchor.MiddleCenter));
        Optional(() => s.unityFontStyleAndWeight = new StyleEnum<FontStyle>(FontStyle.Bold));
        Optional(() => s.whiteSpace = new StyleEnum<WhiteSpace>(WhiteSpace.Normal));
    }

    static void ApplyLayout(int mode)
    {
        var s = _label.style;
        if (mode == 2)
        {   // üst ortada şerit: genişlik %50, sol %25
            s.top = new StyleLength(new Length(1.2f, LengthUnit.Percent));
            s.bottom = new StyleLength(StyleKeyword.Auto);
            s.left = new StyleLength(new Length(25f, LengthUnit.Percent));
            s.width = new StyleLength(new Length(50f, LengthUnit.Percent));
            s.fontSize = new StyleLength(22f);
        }
        else
        {   // sol altta küçük rozet
            s.top = new StyleLength(StyleKeyword.Auto);
            s.bottom = new StyleLength(new Length(0.6f, LengthUnit.Percent));
            s.left = new StyleLength(new Length(0.4f, LengthUnit.Percent));
            s.width = new StyleLength(StyleKeyword.Auto);
            s.fontSize = new StyleLength(14f);
        }
    }

    static void Hide()
    {
        if (_label == null || _shownMode == 0) return;
        try { _label.RemoveFromHierarchy(); } catch { }
        _shownMode = 0;
    }

    static void Optional(Action a)
    {
        try { a(); }
        catch (Exception e) { Plugin.Instance.Log.LogWarning($"Gösterge stili uygulanamadı (önemsiz): {e.Message}"); }
    }

    static Color PhaseColor(string phase) => phase switch
    {
        "recording" => new Color(0.75f, 0.1f, 0.1f, 0.92f),      // kırmızı: kayıt
        "waiting_key" => new Color(0.8f, 0.5f, 0.0f, 0.92f),     // turuncu: senin sıran
        "speaking" => new Color(0.1f, 0.3f, 0.6f, 0.92f),        // mavi: gazeteci konuşuyor
        "error" => new Color(0.55f, 0.1f, 0.1f, 0.92f),
        _ => new Color(0.12f, 0.12f, 0.14f, 0.9f),               // koyu: hazırlanıyor/işleniyor
    };
}
