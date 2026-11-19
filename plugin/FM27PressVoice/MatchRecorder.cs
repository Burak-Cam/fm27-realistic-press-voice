using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text.Encodings.Web;
using System.Text.Json;
using BepInEx;
using UnityEngine;
using UnityEngine.UIElements;

namespace FM27PressVoice;

/// Maç kaydı: maç ekranı açıkken anlatım satırlarını, skoru ve dakikayı kaydeder; ara ara istatistik/reyting
/// fotoğrafı alır. Çıktı: BepInEx\fm27pressvoice\matches\match_<zaman>_<ev>-<deplasman>.jsonl (app özetler).
///
/// PERFORMANS: maç ekranı tespiti kökün ilk 3 seviyesinde, saniyede bir (ucuz). Okunacak elemanlar maç başında
/// bir kez bulunur ve akılda tutulur; her 0,5 sn'de sadece 3 metin okunur. Tam fotoğraf (alt ağaç kopyası)
/// SnapshotSec'te bir. [Match] Enabled=false ile tamamen kapanır.
internal static class MatchRecorder
{
    static readonly JsonSerializerOptions Json = new() { Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };
    static string Dir => Path.Combine(Paths.BepInExRootPath, "fm27pressvoice", "matches");

    // maç ekranı panelleri (ui dökümünden: sadece maç ekranında görünür)
    const string ProtoPanel = "OverviewPrototype", HeaderPanel = "OverviewHeader";

    static VisualElement _proto, _header, _commentary, _time, _score, _home, _away, _mentality;
    static float _nextFind, _nextRead, _nextSnap, _lastSeen;
    static string _file, _lastComment, _lastScore, _lastTime, _teams;
    static int _lastMinute = -1;
    static bool _sawFullTime;

    public static void Tick(VisualElement root)
    {
        if (!Plugin.MatchEnabled.Value || root == null) return;
        float now = Time.unscaledTime;
        if (now < _nextRead) return;
        _nextRead = now + 0.5f;

        if (!Visible(_proto))
        {
            _proto = null;
            if (_file != null && now - _lastSeen > 8f) End("maç ekranı kapandı");
            if (now < _nextFind) return;
            _nextFind = now + 1f;
            FindPanels(root);
            if (_proto == null) return;
            CacheRefs();
        }
        _lastSeen = now;

        string time = Ui.Clean(Ui.GetText(_time)), score = Ui.Clean(Ui.GetText(_score));
        string comment = Ui.Clean(Ui.GetText(_commentary));
        string teams = $"{Ui.Clean(Ui.GetText(_home))}-{Ui.Clean(Ui.GetText(_away))}";
        int minute = Minute(time);

        // yeni maç: dosya yok, takımlar değişti ya da dakika başa döndü
        if (_file == null || teams != _teams || (minute >= 0 && _lastMinute >= 20 && minute + 15 < _lastMinute))
        {
            if (_file != null) End("yeni maç");
            Start(teams);
        }
        if (minute >= 0) _lastMinute = minute;

        if (score != _lastScore && !string.IsNullOrEmpty(score))
        {
            Append(new Dictionary<string, object> { ["type"] = "score", ["t"] = time, ["s"] = score });
            _lastScore = score;
        }
        if (comment != _lastComment && !string.IsNullOrEmpty(comment))
        {
            Append(new Dictionary<string, object> { ["type"] = "c", ["t"] = time, ["s"] = score, ["x"] = comment });
            _lastComment = comment;
        }
        bool fullTime = minute >= 90;
        if (now >= _nextSnap || (fullTime && !_sawFullTime))
        {
            _nextSnap = now + Plugin.MatchSnapshotSec.Value;
            if (fullTime) _sawFullTime = true;
            Snapshot(time);
        }
        _lastTime = time;
    }

    static bool Visible(VisualElement ve) => ve != null && Ui.Attached(ve) && Ui.HasClass(ve, "panel--visible");

    /// Kökün ilk 3 seviyesinde maç panellerini ara (basın paneli aramasıyla aynı maliyet).
    static void FindPanels(VisualElement root)
    {
        _proto = _header = null;
        Scan(root, 0);
    }

    static void Scan(VisualElement ve, int depth)
    {
        if (depth > 3 || ve == null) return;
        int count;
        try { count = ve.childCount; } catch { return; }
        for (int i = 0; i < count; i++)
        {
            VisualElement c;
            try { c = ve[i]; } catch { continue; }
            if (c == null) continue;
            string name;
            try { name = c.name; } catch { name = null; }
            if (name == ProtoPanel && Ui.HasClass(c, "panel--visible")) _proto = c;
            else if (name == HeaderPanel && Ui.HasClass(c, "panel--visible")) _header = c;
            else Scan(c, depth + 1);
            if (_proto != null && _header != null) return;
        }
    }

    /// Maç başında bir kez: okunacak elemanları bul (alt ağaç kopyası; tek seferlik maliyet log'a yazılır).
    static void CacheRefs()
    {
        var sw = Stopwatch.StartNew();
        var proto = Ui.Build(_proto);
        var header = _header != null ? Ui.Build(_header) : null;
        var bar = proto.FindName("CommentaryBar");
        _commentary = bar?.Find(n => n.IsText)?.Ve;
        _score = proto.FindName("Score")?.Ve;
        _time = header?.FindName("time")?.Ve;
        _home = header?.FindName("ClubHomeTeamText")?.Ve;
        _away = header?.FindName("ClubAwayTeamText")?.Ve;
        _mentality = header?.FindName("StringValueHighlighted")?.Ve;
        Plugin.Instance.Log.LogInfo($"[maç] ekran bulundu ({sw.ElapsedMilliseconds} ms): anlatım={_commentary != null} " +
                                    $"skor={_score != null} dakika={_time != null} takımlar={_home != null}/{_away != null}");
    }

    /// Maç panellerindeki metinleri sırayla kaydet (istatistik, reyting, diziliş, olay dakikaları). Ayrıştırma app'te.
    static void Snapshot(string time)
    {
        var sw = Stopwatch.StartNew();
        var items = new List<string[]>();
        void Collect(VisualElement panel)
        {
            if (panel == null || !Ui.Attached(panel)) return;
            foreach (var n in Ui.Build(panel).FindAll(n => n.IsText))
            {
                var t = n.Clean;
                if (!string.IsNullOrEmpty(t)) items.Add(new[] { n.Name ?? "", t });
            }
        }
        Collect(_header);
        Collect(_proto);
        Append(new Dictionary<string, object> { ["type"] = "snap", ["t"] = time, ["mentality"] = Ui.Clean(Ui.GetText(_mentality)),
                                                ["items"] = items });
        if (sw.ElapsedMilliseconds > 30)
            Plugin.Instance.Log.LogInfo($"[maç] fotoğraf {items.Count} metin, {sw.ElapsedMilliseconds} ms");
    }

    static void Start(string teams)
    {
        _teams = teams;
        _lastComment = _lastScore = _lastTime = null;
        _lastMinute = -1;
        _sawFullTime = false;
        _nextSnap = 0;
        Directory.CreateDirectory(Dir);
        string safe = string.Concat(teams.Split(Path.GetInvalidFileNameChars()));
        _file = Path.Combine(Dir, $"match_{DateTime.Now:yyyyMMdd_HHmmss}_{safe}.jsonl");
        Append(new Dictionary<string, object> { ["type"] = "start", ["teams"] = teams, ["time"] = DateTime.Now.ToString("s") });
        Plugin.Instance.Log.LogInfo($"[maç] kayıt başladı: {Path.GetFileName(_file)}");
    }

    static void End(string why)
    {
        Append(new Dictionary<string, object> { ["type"] = "end", ["why"] = why, ["t"] = _lastTime, ["s"] = _lastScore,
                                                ["time"] = DateTime.Now.ToString("s") });
        Plugin.Instance.Log.LogInfo($"[maç] kayıt bitti ({why}): {Path.GetFileName(_file)}");
        _file = null;
        _commentary = _time = _score = _home = _away = _mentality = null;
    }

    static void Append(Dictionary<string, object> obj)
    {
        if (_file == null) return;
        try { File.AppendAllText(_file, JsonSerializer.Serialize(obj, Json) + "\n"); }
        catch (Exception e) { Plugin.Instance.Log.LogWarning($"[maç] yazılamadı: {e.Message}"); }
    }

    static int Minute(string t)
    {
        if (string.IsNullOrEmpty(t)) return -1;
        int i = t.IndexOf(':');
        return i > 0 && int.TryParse(t.Substring(0, i), out var m) ? m : -1;
    }
}
