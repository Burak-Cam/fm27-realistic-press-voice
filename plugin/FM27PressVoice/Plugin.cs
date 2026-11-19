using System;
using BepInEx;
using BepInEx.Configuration;
using BepInEx.Unity.IL2CPP;
using Il2CppInterop.Runtime.Injection;
using UnityEngine;

namespace FM27PressVoice;

[BepInPlugin("fm27pressvoice", "FM27 Press Voice", "0.3.1")]
public class Plugin : BasePlugin
{
    internal static Plugin Instance;

    // UiDump (keşif aracı)
    internal static ConfigEntry<bool> DumpEnabled;
    internal static ConfigEntry<string> TriggerText;
    internal static ConfigEntry<float> IntervalSec;
    internal static ConfigEntry<int> MaxDumps;
    internal static ConfigEntry<string> MatchTriggerText;
    internal static ConfigEntry<int> MatchMaxDumps;
    internal static ConfigEntry<float> MatchDumpEverySec;

    // Bridge (docs/protocol.md)
    internal static ConfigEntry<bool> BridgeEnabled;
    internal static ConfigEntry<float> PollSec;
    internal static ConfigEntry<bool> ReplaceQuestion;
    internal static ConfigEntry<bool> ReplaceAnswerText;
    internal static ConfigEntry<bool> AutoClick;
    internal static ConfigEntry<string> ClickTarget;
    internal static ConfigEntry<string> ClickMethod;

    // Oyun içi gösterge
    internal static ConfigEntry<bool> OverlayEnabled;
    internal static ConfigEntry<bool> OverlayBadge;
    internal static ConfigEntry<float> OverlayBadgeSeconds;

    public override void Load()
    {
        Instance = this;
        DumpEnabled = Config.Bind("UiDump", "Enabled", true, "Basın ekranlarında UI ağacını dosyaya dök (keşif).");
        TriggerText = Config.Bind("UiDump", "TriggerText", "Soru (|Röportaj",
            "Ekrandaki herhangi bir metin bunlardan birini içeriyorsa UI ağacı dosyaya dökülür (| ile ayır).");
        IntervalSec = Config.Bind("UiDump", "IntervalSec", 2f, "Kontrol aralığı (saniye).");
        MaxDumps = Config.Bind("UiDump", "MaxDumps", 200, "Oturum başına en fazla dosya sayısı.");
        MatchTriggerText = Config.Bind("UiDump", "MatchTriggerText", "Topla Oynama|xG",
            "Maç/istatistik ekranı tetikleri (| ile ayır). Ayrı sınır ve aralıkla dökülür (dosya adı *_mac.txt).");
        MatchMaxDumps = Config.Bind("UiDump", "MatchMaxDumps", 12, "Oturum başına en fazla maç ekranı dökümü.");
        MatchDumpEverySec = Config.Bind("UiDump", "MatchDumpEverySec", 45f, "İki maç ekranı dökümü arası en az süre (saniye).");

        BridgeEnabled = Config.Bind("Bridge", "Enabled", true, "Basın ekranını oku, press_state.json yaz, app komutlarını uygula.");
        PollSec = Config.Bind("Bridge", "PollSec", 0.25f, "Basın ekranı kontrol aralığı (saniye).");
        ReplaceQuestion = Config.Bind("Bridge", "ReplaceQuestion", true, "press_question.json gelince soru balonunu değiştir.");
        ReplaceAnswerText = Config.Bind("Bridge", "ReplaceAnswerText", true, "Seçilen seçeneğin/menajer balonunun metnini kullanıcının cevabıyla değiştir.");
        AutoClick = Config.Bind("Bridge", "AutoClick", true, "press_answer.json gelince seçeneği otomatik tıkla.");
        ClickTarget = Config.Bind("Bridge", "ClickTarget", "outer",
            new ConfigDescription("Seçenekteki iç içe iki butondan hangisi tıklanır.", new AcceptableValueList<string>("outer", "inner")));
        ClickMethod = Config.Bind("Bridge", "ClickMethod", "submit",
            new ConfigDescription("İlk denenecek tıklama yöntemi (başarısızsa diğerleri denenir).",
                new AcceptableValueList<string>("submit", "invoke", "navsubmit")));

        OverlayEnabled = Config.Bind("Overlay", "Enabled", true, "Basın ekranında üstte durum şeridi göster (app ne yapıyor).");
        OverlayBadge = Config.Bind("Overlay", "ShowBadge", true, "Oyun açılınca sol altta kısa süre 'Sesli Basın' rozeti göster.");
        OverlayBadgeSeconds = Config.Bind("Overlay", "BadgeSeconds", 12f, "Rozetin açılışta görünme süresi (sn). App açılıp kapanınca da kısa süre görünür.");

        ClassInjector.RegisterTypeInIl2Cpp<Ticker>();
        var go = new GameObject("FM27PressVoiceTicker");
        UnityEngine.Object.DontDestroyOnLoad(go);
        go.hideFlags = HideFlags.HideAndDontSave;
        go.AddComponent<Ticker>();

        Log.LogInfo("FM27PressVoice yüklendi.");
    }
}

public class Ticker : MonoBehaviour
{
    public Ticker(IntPtr ptr) : base(ptr) { }

    static float _nextDump, _nextBridge;
    static int _bridgeErrors;

    void Update()
    {
        float now = Time.unscaledTime;

        if (Plugin.BridgeEnabled.Value)
        {
            try { Bridge.Frame(); }
            catch (Exception e) { LogLimited(e); }

            if (now >= _nextBridge)
            {
                _nextBridge = now + Plugin.PollSec.Value;
                try { Bridge.Tick(); }
                catch (Exception e) { LogLimited(e); }
            }
        }

        try { Overlay.Tick(); }
        catch (Exception e) { LogLimited(e); }

        if (Plugin.DumpEnabled.Value && now >= _nextDump)
        {
            _nextDump = now + Plugin.IntervalSec.Value;
            try { UiDumper.Tick(); }
            catch (Exception e) { Plugin.Instance.Log.LogError(e); }
        }
    }

    // Her karede aynı hata log'u doldurmasın.
    static void LogLimited(Exception e)
    {
        if (++_bridgeErrors <= 20) Plugin.Instance.Log.LogError(e);
        else if (_bridgeErrors == 21) Plugin.Instance.Log.LogError("Bridge hataları susturuldu (20+).");
    }
}
