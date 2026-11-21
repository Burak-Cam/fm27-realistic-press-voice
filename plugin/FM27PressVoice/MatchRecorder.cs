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
    static bool _sawFullTime, _ftCaptured, _htCaptured, _wasVisible;
    static float _lastTimeChange;
    static string _lastFile;
    static readonly HashSet<string> SkipPanels = new() { "GameWorldBackground", "Watermark", "GameVersion" };

    // DÜDÜK İZLEME (v0.4.2): devre arası / maç sonu istatistik ekranı (gol, asist, dakika, penaltı, kart, şut, topla
    // oynama...) bu yöntemin en önemli verisi. v0.4.1 kaçırdı: düdükte saat geri döner (47:59->45:00, 95:17->90:00) ve
    // maç paneli hemen kapanır; "saat 5 sn dursun" tetiği hiç çalışmadı, geç alınan kayıtta takım konuşması/Portal vardı.
    // Şimdi düdük belirtisi görülünce 150 sn izleme penceresi açılır. Panel kontrolü 0,2 sn'de bir (ekranda 2 sn bile
    // kalmayan kullanıcıyı kaçırmamak için); görünen panel kümesi değişince hemen, sonra +0,4 / +1 / +2 sn'de tekrar
    // çekilir (animasyonla geç dolan içerik). İçerik bir öncekiyle aynıysa dosyaya yazılmaz. Panel adını bilmeye gerek yok.
    const float WatchSec = 150f, WatchCheckSec = 0.2f;
    const int WatchMaxCaptures = 40;
    static readonly float[] RecaptureDelays = { 0.4f, 1f, 2f };
    static float _watchUntil, _nextWatch, _changeAt;
    static int _recaptureIdx;
    static string _watchTag, _lastPanelSig;
    static int _watchCount, _watchChecks, _lastCaptureHash;
    static double _watchTicks, _watchMaxMs;

    public static void Tick(VisualElement root)
    {
        if (!Plugin.MatchEnabled.Value || root == null) return;
        float now = Time.unscaledTime;
        if (now < _watchUntil && now >= _nextWatch)
        {
            _nextWatch = now + WatchCheckSec;
            WatchTick(root, now);
        }
        if (now < _nextRead) return;
        _nextRead = now + 0.5f;

        if (!Visible(_proto))
        {
            _proto = null;
            if (_wasVisible && _file != null)               // maç paneli az önce kapandı
            {
                _wasVisible = false;
                StartWatch(PhaseFor(_lastMinute), now);
            }
            // kayıt sadece maç sonunda biter; devre arasında ekrandan çıkmak maçı bölmez (uzun süre kapalıysa biter)
            if (_file != null && ((now - _lastSeen > 8f && _lastMinute >= 85) || now - _lastSeen > 600f))
                End("maç ekranı kapandı");
            if (now < _nextFind) return;
            _nextFind = now + 1f;
            FindPanels(root);
            if (_proto == null) return;
            CacheRefs();
        }
        _lastSeen = now;
        _wasVisible = true;

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
        // düdük: saat uzatmadan normal süreye geri döndü (47:59 -> 45:00, 95:17 -> 90:00)
        if (minute >= 0 && _lastMinute >= 45 && minute < _lastMinute && minute + 15 >= _lastMinute)
            StartWatch(PhaseFor(_lastMinute), now);
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
        if (time != _lastTime) _lastTimeChange = now;
        if (minute >= 90 && !_ftCaptured && now - _lastTimeChange > 3f)
        {
            _ftCaptured = true;                             // süre durdu: maç bitti olabilir
            StartWatch("mac_sonu", now);
        }
        if (minute >= 45 && minute <= 50 && !_htCaptured && now - _lastTimeChange > 3f)
        {
            _htCaptured = true;                             // ilk yarı bitmiş olabilir
            StartWatch("devre_arasi", now);
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

    static string PhaseFor(int minute) => minute >= 85 ? "mac_sonu" : minute >= 44 && minute <= 60 ? "devre_arasi" : null;

    static void StartWatch(string tag, float now)
    {
        if (tag == null) return;
        if (tag == _watchTag && now < _watchUntil) return;      // aynı aşama zaten izleniyor
        _watchTag = tag;
        _watchUntil = now + WatchSec;
        _lastPanelSig = null;
        _recaptureIdx = RecaptureDelays.Length;
        _nextWatch = 0f;
        _watchCount = _watchChecks = _lastCaptureHash = 0;
        _watchTicks = _watchMaxMs = 0;
        Plugin.Instance.Log.LogInfo($"[maç] düdük izleme başladı: {tag} (dakika {_lastMinute})");
    }

    /// İzleme penceresinde: görünen panel adları değiştiyse ya da son değişimin tekrar çekim zamanı geldiyse kaydet.
    static void WatchTick(VisualElement root, float now)
    {
        if (now + WatchCheckSec >= _watchUntil)              // pencere bitiyor: maliyeti raporla (genel kullanıcılar için ölçü)
        {
            Plugin.Instance.Log.LogInfo($"[maç] düdük izleme bitti: {_watchTag}, {_watchCount} çekim, panel kontrolü " +
                                        $"{_watchChecks} kez, ort. {(_watchChecks > 0 ? _watchTicks / _watchChecks : 0):F2} ms, en fazla {_watchMaxMs:F2} ms");
            _watchUntil = 0f;
            return;
        }
        if (_watchCount >= WatchMaxCaptures) return;
        var sw = Stopwatch.StartNew();
        var names = new List<string>();
        VisiblePanels(root, 0, names);
        double ms = sw.Elapsed.TotalMilliseconds;
        _watchChecks++; _watchTicks += ms; if (ms > _watchMaxMs) _watchMaxMs = ms;
        string sig = string.Join(",", names);
        bool changed = sig != _lastPanelSig;
        bool recapture = !changed && _recaptureIdx < RecaptureDelays.Length && now - _changeAt >= RecaptureDelays[_recaptureIdx];
        if (!changed && !recapture) return;
        if (changed) { _lastPanelSig = sig; _changeAt = now; _recaptureIdx = 0; }
        else _recaptureIdx++;
        if (CaptureAll(root, $"{_watchTag}_ekrani_{_watchCount + 1}", skipIfSame: true)) _watchCount++;
    }

    static void VisiblePanels(VisualElement ve, int depth, List<string> names)
    {
        if (ve == null || depth > 6) return;
        int count;
        try { count = ve.childCount; } catch { return; }
        for (int i = 0; i < count; i++)
        {
            VisualElement c;
            try { c = ve[i]; } catch { continue; }
            if (c == null) continue;
            if (Ui.HasClass(c, "panel") && Ui.HasClass(c, "panel--visible"))
            {
                string name;
                try { name = c.name ?? ""; } catch { name = ""; }
                if (!SkipPanels.Contains(name)) names.Add(name);
            }
            else VisiblePanels(c, depth + 1, names);
        }
    }

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

    /// Görünen tüm panellerin metinlerini bir kez kaydet (maç sonu ekranı: golcüler, istatistikler). Tek seferlik maliyet.
    /// skipIfSame: içerik son çekimle aynıysa yazma. Yazıldıysa true.
    static bool CaptureAll(VisualElement root, string where, bool skipIfSame = false)
    {
        var sw = Stopwatch.StartNew();
        var panels = new Dictionary<string, List<string[]>>();
        void Walk(VisualElement ve, int depth)
        {
            if (ve == null || depth > 6) return;
            int count;
            try { count = ve.childCount; } catch { return; }
            for (int i = 0; i < count; i++)
            {
                VisualElement c;
                try { c = ve[i]; } catch { continue; }
                if (c == null) continue;
                string name;
                try { name = c.name ?? ""; } catch { name = ""; }
                if (Ui.HasClass(c, "panel") && Ui.HasClass(c, "panel--visible"))
                {
                    if (SkipPanels.Contains(name)) continue;
                    var items = new List<string[]>();
                    foreach (var n in Ui.Build(c).FindAll(n => n.IsText))
                    {
                        var t = n.Clean;
                        if (!string.IsNullOrEmpty(t)) items.Add(new[] { n.Name ?? "", t });
                    }
                    if (items.Count > 0) panels[name] = items;
                }
                else Walk(c, depth + 1);
            }
        }
        Walk(root, 0);
        var target = _file ?? _lastFile;
        if (target == null || panels.Count == 0) return false;
        var body = JsonSerializer.Serialize(panels, Json);
        int hash = body.GetHashCode();
        if (skipIfSame && hash == _lastCaptureHash) return false;
        _lastCaptureHash = hash;
        var line = JsonSerializer.Serialize(new Dictionary<string, object> { ["type"] = "screen", ["where"] = where,
                                                                             ["panels"] = panels }, Json);
        try { File.AppendAllText(target, line + "\n"); } catch { return false; }
        Plugin.Instance.Log.LogInfo($"[maç] {where} kaydedildi: {panels.Count} panel, {sw.ElapsedMilliseconds} ms");
        return true;
    }

    static void Start(string teams)
    {
        _teams = teams;
        _lastComment = _lastScore = _lastTime = null;
        _lastMinute = -1;
        _sawFullTime = _ftCaptured = _htCaptured = false;
        _watchUntil = 0f; _watchTag = null;
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
        _lastFile = _file;                                  // izleme penceresi kayda _lastFile üzerinden devam eder
        _file = null;
        _wasVisible = false;
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
