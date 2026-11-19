using System;
using System.IO;
using System.Text;
using BepInEx;
using UnityEngine;
using UnityEngine.UIElements;

namespace FM27PressVoice;

/// Basın toplantısı ekranının UI Toolkit ağacını dosyaya döker (keşif aracı).
/// UYARI: derlenmedi/test edilmedi; Unity 6 interop API'lerine göre düzeltilmesi gerekebilir.
internal static class UiDumper
{
    static string _last = "";
    static int _count;
    static bool _classErrLogged;
    static int _matchCount;
    static float _nextMatchDump;
    // Her oyun oturumu ayrı klasöre: eski dökümlerin üzerine yazılmaz.
    static readonly string _session = DateTime.Now.ToString("yyyyMMdd_HHmmss");

    public static void Tick()
    {
        if (_count >= Plugin.MaxDumps.Value) return;

        var docs = UnityEngine.Object.FindObjectsOfType<UIDocument>();
        var sb = new StringBuilder();
        bool triggered = false;
        string hit = null;
        // Birden çok tetik '|' ile ayrılır, ör. "Soru (|Röportaj"
        string[] trigger = Plugin.TriggerText.Value.Split('|', StringSplitOptions.RemoveEmptyEntries);
        string[] matchTrigger = Plugin.MatchTriggerText.Value.Split('|', StringSplitOptions.RemoveEmptyEntries);
        bool matchAllowed = _matchCount < Plugin.MatchMaxDumps.Value && UnityEngine.Time.unscaledTime >= _nextMatchDump;
        string[] all = new string[trigger.Length + (matchAllowed ? matchTrigger.Length : 0)];
        trigger.CopyTo(all, 0);
        if (matchAllowed) matchTrigger.CopyTo(all, trigger.Length);

        foreach (var d in docs)
        {
            var root = d.rootVisualElement;
            if (root == null) continue;
            sb.AppendLine($"# UIDocument '{d.name}'");
            Walk(root, 0, sb, all, ref triggered, ref hit);
        }

        if (!triggered) return;
        bool isMatch = Array.IndexOf(trigger, hit) < 0;   // maç ekranı tetiği
        var text = sb.ToString();
        if (text == _last) return;
        _last = text;
        _count++;
        if (isMatch) { _matchCount++; _nextMatchDump = UnityEngine.Time.unscaledTime + Plugin.MatchDumpEverySec.Value; }

        var dir = Path.Combine(Paths.BepInExRootPath, "fm27pressvoice", _session);
        Directory.CreateDirectory(dir);
        var file = Path.Combine(dir, isMatch ? $"ui_dump_{_count}_mac.txt" : $"ui_dump_{_count}.txt");
        File.WriteAllText(file, text, Encoding.UTF8);
        Plugin.Instance.Log.LogInfo($"UI dökümü yazıldı: {file}");
    }

    static void Walk(VisualElement ve, int depth, StringBuilder sb, string[] trigger, ref bool triggered, ref string hit)
    {
        string txt = null;
        var te = ve.TryCast<TextElement>();
        if (te != null)
        {
            txt = te.text;
            if (!triggered && !string.IsNullOrEmpty(txt))
                foreach (var t in trigger)
                    if (txt.Contains(t)) { triggered = true; hit = t; break; }
        }

        var classes = new StringBuilder();
        try
        {
            // Il2Cpp List<string>: foreach yok, Count + indeksle oku.
            var list = ve.GetClassesForIteration();
            if (list != null)
                for (int i = 0; i < list.Count; i++) classes.Append('.').Append(list[i]);
        }
        catch (Exception e)
        {
            if (!_classErrLogged) { _classErrLogged = true; Plugin.Instance.Log.LogWarning($"Class listesi okunamadı: {e}"); }
        }

        string typeName;
        try { typeName = ve.GetIl2CppType().Name; } catch { typeName = ve.GetType().Name; }

        sb.Append(' ', depth * 2)
          .Append(typeName)
          .Append(" name='").Append(ve.name).Append('\'')
          .Append(' ').Append(classes);
        if (txt != null) sb.Append(" text='").Append(txt.Replace("\n", "\\n")).Append('\'');
        sb.AppendLine();

        for (int i = 0; i < ve.childCount; i++)
            Walk(ve[i], depth + 1, sb, trigger, ref triggered, ref hit);
    }
}
