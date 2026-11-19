using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Encodings.Web;
using System.Text.Json;
using BepInEx;
using UnityEngine;
using UnityEngine.UIElements;

namespace FM27PressVoice;

/// Eklenti <-> app köprüsü (docs/protocol.md): durum yazar, komut okur, metin override'larını canlı tutar, tıklar.
internal static class Bridge
{
    static readonly JsonSerializerOptions Json = new()
    {
        IncludeFields = true,
        WriteIndented = true,
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };

    static string Dir => Path.Combine(Paths.BepInExRootPath, "fm27pressvoice");
    static string StatePath => Path.Combine(Dir, "press_state.json");
    static string QuestionPath => Path.Combine(Dir, "press_question.json");
    static string AnswerPath => Path.Combine(Dir, "press_answer.json");

    // --- UIDocument önbelleği ---
    static VisualElement _root;
    static float _nextRootSearch;

    // --- durum ---
    static long _seq;
    static string _lastWritten = "";
    static PressState _state;
    internal static bool InPress => _state != null;
    internal static VisualElement Root => _root != null && Ui.Attached(_root) ? _root : null;
    static PressRefs _refs;
    static string _prevQuestionRaw;
    static Applied _lastApplied;
    static string _overrideQid;
    static string _contextQid;
    static Dictionary<string, string> _context;

    // Arka plandaki ekranlardan toplanan bağlam (eleman adı -> JSON anahtarı)
    static readonly (string name, string key)[] ContextNames =
    {
        ("CurrentDateLabel", "date"),
        ("NextOpponentName", "next_opponent"),
        ("CompName", "next_competition"),
        ("NextMatchLocationLabel", "next_venue"),
        ("newsHeadlineText", "news_headline"),
        ("newsBodyText", "news_body"),
        ("SIText_headlinesubtitle", "news_subject"),
    };

    // --- metin override'ları: oyun metni geri yazarsa tekrar uygula ---
    sealed class TextOverride
    {
        public VisualElement Ve;
        public string Desired, DesiredClean, OriginalRaw, OriginalClean, Qid;
        public float NextApply;
    }
    static readonly List<TextOverride> _overrides = new();

    // --- tıklama doğrulama: etkisi görülmezse sıradaki buton/yöntem kombinasyonu denenir ---
    sealed class PendingClick
    {
        public string Qid; public int Cat, Opt, Step, HumanBefore; public float Deadline;
        public List<(string target, string method)> Order;
    }
    static PendingClick _click;
    static readonly (string target, string method)[] Combos =
        { ("outer", "submit"), ("inner", "submit"), ("outer", "invoke"), ("inner", "invoke"), ("outer", "navsubmit"), ("inner", "navsubmit") };
    const float ClickVerifySec = 2f;

    // --- tıklamadan sonra menajer balonundaki metni değiştirme ---
    static string _pendingHumanOriginal, _pendingHumanDisplay;
    static float _pendingHumanUntil;

    public static void Tick()
    {
        var root = GetRoot();
        if (root == null) { WriteInactive(); return; }

        var panel = PressReader.FindPanel(root, out var screen, out var hint);
        if (panel == null)
        {
            if (_click != null) ClickVerified("panel kapandı");
            if (_overrides.Count > 0) _overrides.Clear();
            _overrideQid = null;
            _prevQuestionRaw = null;
            WriteInactive();
            return;
        }

        var st = PressReader.Read(panel, screen, hint, n => OriginalTextOf(n.Ve, n.Text), out var refs);
        st.ready = !string.IsNullOrEmpty(st.game_question)
                   && st.game_question_raw == _prevQuestionRaw
                   && st.categories.Exists(c => c.options.Count > 0);
        _prevQuestionRaw = st.game_question_raw;
        _state = st; _refs = refs;

        // soru değiştiyse eski override'ları bırak
        _overrides.RemoveAll(o => o.Qid != null && o.Qid != st.question_id && o.Qid != "human");
        if (_overrideQid != st.question_id) _overrideQid = null;

        if (_contextQid != st.question_id)
        {
            _contextQid = st.question_id;
            try { _context = HarvestContext(root, panel); } catch (Exception e) { _context = null; Plugin.Instance.Log.LogWarning($"Bağlam okunamadı: {e.Message}"); }
        }
        st.context = _context;

        CheckClick(st, refs);
        ProcessCommands();
        ReplaceHumanBubble();

        st.override_question_id = _overrideQid;
        st.last_applied = _lastApplied;
        Write(st);
    }

    /// Her karede çağrılır: override'ları ucuzca kontrol edip gerekirse yeniden uygular.
    public static void Frame()
    {
        if (_overrides.Count == 0) return;
        float now = Time.unscaledTime;
        for (int i = _overrides.Count - 1; i >= 0; i--)
        {
            var o = _overrides[i];
            if (now < o.NextApply) continue;
            o.NextApply = now + 0.1f;
            if (!Ui.Attached(o.Ve)) { _overrides.RemoveAt(i); continue; }
            var cur = Ui.Clean(Ui.GetText(o.Ve));
            if (cur == o.DesiredClean) continue;
            if (string.IsNullOrEmpty(cur) || cur == o.OriginalClean)
                Ui.SetText(o.Ve, o.Desired);          // oyun geri yazdı (veya henüz dolmadı) -> tekrar uygula
            else
                _overrides.RemoveAt(i);               // eleman başka içerik için yeniden kullanıldı -> bırak
        }
    }

    /// Override edilmiş eleman için her zaman ORİJİNAL metni raporla (geçişte metin boş/ara değer olsa bile
    /// question_id sabit kalsın). Eleman başka içerik için yeniden kullanılırsa Frame() override'ı zaten kaldırır.
    static string OriginalTextOf(VisualElement ve, string current)
    {
        if (ve == null) return current;
        foreach (var o in _overrides)
        {
            if (o.Ve == null || o.Ve.Pointer != ve.Pointer) continue;
            var c = Ui.Clean(current);
            if (string.IsNullOrEmpty(c) || c == o.DesiredClean || c == o.OriginalClean) return o.OriginalRaw;
        }
        return current;
    }

    static void AddOverride(VisualElement ve, string desired, string qid)
    {
        if (ve == null) return;
        _overrides.RemoveAll(o => o.Ve.Pointer == ve.Pointer);
        var orig = Ui.GetText(ve);
        _overrides.Add(new TextOverride
        {
            Ve = ve, Desired = desired, DesiredClean = Ui.Clean(desired),
            OriginalRaw = orig, OriginalClean = Ui.Clean(orig), Qid = qid,
        });
        Ui.SetText(ve, desired);
    }

    // ---------------- komutlar ----------------
    static void ProcessCommands()
    {
        var q = ReadCommand<QuestionCommand>(QuestionPath);
        if (q != null)
        {
            if (q.question_id != _state.question_id)
                SetApplied(q.question_id, false, "question", $"bayat question_id (güncel {_state.question_id})");
            else if (!Plugin.ReplaceQuestion.Value)
                SetApplied(q.question_id, false, "question", "ReplaceQuestion kapalı");
            else if (_refs.QuestionText == null)
                SetApplied(q.question_id, false, "question", "soru elemanı bulunamadı");
            else
            {
                AddOverride(_refs.QuestionText, q.text, q.question_id);
                _overrideQid = q.question_id;
                SetApplied(q.question_id, true, "question", "soru metni değiştirildi");
            }
        }

        var a = ReadCommand<AnswerCommand>(AnswerPath);
        if (a != null) ApplyAnswer(a);
    }

    static void ApplyAnswer(AnswerCommand a)
    {
        if (a.question_id != _state.question_id)
        { SetApplied(a.question_id, false, "answer", $"bayat question_id (güncel {_state.question_id})"); return; }
        if (a.category_index < 0 || a.category_index >= _refs.Options.Count)
        { SetApplied(a.question_id, false, "answer", $"geçersiz category_index {a.category_index}"); return; }
        var opts = _refs.Options[a.category_index];
        if (a.option_index < 0 || a.option_index >= opts.Count)
        { SetApplied(a.question_id, false, "answer", $"geçersiz option_index {a.option_index}"); return; }

        var o = opts[a.option_index];
        var originalOption = Ui.Clean(Ui.GetText(o.Text));
        var detail = new List<string>();

        if (Plugin.ReplaceAnswerText.Value && !string.IsNullOrWhiteSpace(a.display_text))
        {
            AddOverride(o.Text, a.display_text, a.question_id);
            _pendingHumanOriginal = originalOption;
            _pendingHumanDisplay = a.display_text;
            _pendingHumanUntil = Time.unscaledTime + 15f;
            detail.Add("seçenek metni değiştirildi");
        }

        bool ok = true;
        if (a.click && Plugin.AutoClick.Value)
        {
            var order = new List<(string, string)> { (Plugin.ClickTarget.Value, Plugin.ClickMethod.Value) };
            foreach (var c in Combos) if (!order.Contains(c)) order.Add(c);
            _click = new PendingClick
            {
                Qid = a.question_id, Cat = a.category_index, Opt = a.option_index, Step = -1, Order = order,
                HumanBefore = CountHumanTexts(_refs),
            };
            ok = NextClick();
            detail.Add(ok ? $"tıklandı ({_click?.Order[_click.Step].target}/{_click?.Order[_click.Step].method}), doğrulanıyor" : "hiçbir tıklama yöntemi çalıştırılamadı");
        }
        else detail.Add("tıklama yok (AutoClick kapalı veya click=false)");

        SetApplied(a.question_id, ok, "answer", string.Join("; ", detail));
    }

    static int CountHumanTexts(PressRefs r)
    {
        int n = 0;
        if (r != null) foreach (var h in r.HumanBubbleTexts) if (!string.IsNullOrEmpty(Ui.Clean(Ui.GetText(h)))) n++;
        return n;
    }

    /// Sıradaki kombinasyonu dener (çağrılamayanları atlar). false = kombinasyon kalmadı.
    static bool NextClick()
    {
        while (_click != null && ++_click.Step < _click.Order.Count)
        {
            if (_refs == null || _click.Cat >= _refs.Options.Count || _click.Opt >= _refs.Options[_click.Cat].Count) break;
            var o = _refs.Options[_click.Cat][_click.Opt];
            var (target, method) = _click.Order[_click.Step];
            var ve = target == "inner" ? o.Inner : o.Outer;
            if (ve == null || !ClickOnce(ve, method)) continue;
            _click.Deadline = Time.unscaledTime + ClickVerifySec;
            Plugin.Instance.Log.LogInfo($"Tıklama denendi: {target}/{method}");
            return true;
        }
        if (_click != null) SetApplied(_click.Qid, false, "answer", "tıklamaların hiçbiri etki etmedi; seçimi elle yap");
        _click = null;
        return false;
    }

    static void CheckClick(PressState st, PressRefs refs)
    {
        if (_click == null) return;
        if (st.question_id != _click.Qid) { ClickVerified("soru değişti"); return; }
        if (CountHumanTexts(refs) > _click.HumanBefore) { ClickVerified("menajer balonu belirdi"); return; }
        if (Time.unscaledTime < _click.Deadline) return;
        Plugin.Instance.Log.LogWarning($"Tıklama etkisiz: {_click.Order[_click.Step].target}/{_click.Order[_click.Step].method}, sıradaki deneniyor");
        NextClick();
    }

    static void ClickVerified(string why)
    {
        var (target, method) = _click.Order[_click.Step];
        SetApplied(_click.Qid, true, "answer", $"tıklama doğrulandı ({why}): {target}/{method}");
        if (Plugin.ClickTarget.Value != target || Plugin.ClickMethod.Value != method)
        {
            Plugin.ClickTarget.Value = target;   // çalışan kombinasyonu ayara kaydet (BepInEx cfg'yi yazar)
            Plugin.ClickMethod.Value = method;
            Plugin.Instance.Log.LogInfo($"Çalışan tıklama ayara kaydedildi: ClickTarget={target}, ClickMethod={method}");
        }
        _click = null;
    }

    /// Tek yöntemle tıklar. false = bu eleman/yöntem için çağrılamadı (tip uymuyor veya hata).
    static bool ClickOnce(VisualElement ve, string method)
    {
        try
        {
            switch (method)
            {
                case "submit":
                    var sib = ve.TryCast<SI.Bindable.SIButton>();
                    if (sib == null) return false;
                    sib.Submit();
                    return true;
                case "invoke":
                    var b = ve.TryCast<Button>();
                    if (b?.clickable == null) return false;
                    b.clickable.Invoke(null);
                    return true;
                case "navsubmit":
                    var ev = NavigationSubmitEvent.GetPooled();
                    ev.target = ve.Cast<IEventHandler>(); // interop'ta arayüzler sınıf
                    ve.SendEvent(ev);
                    ev.Dispose();
                    return true;
            }
        }
        catch (Exception e)
        {
            Plugin.Instance.Log.LogWarning($"Tıklama yöntemi '{method}' hata: {e.Message}");
        }
        return false;
    }

    static void ReplaceHumanBubble()
    {
        if (_pendingHumanOriginal == null) return;
        if (Time.unscaledTime > _pendingHumanUntil) { _pendingHumanOriginal = null; return; }
        foreach (var hb in _refs.HumanBubbleTexts)
        {
            var cur = Ui.Clean(Ui.GetText(hb));
            if (!string.IsNullOrEmpty(cur) && cur == _pendingHumanOriginal)
            {
                AddOverride(hb, _pendingHumanDisplay, "human");
                _pendingHumanOriginal = null;
                Plugin.Instance.Log.LogInfo("Menajer balonu cevap metniyle değiştirildi.");
                return;
            }
        }
    }

    static Dictionary<string, string> HarvestContext(VisualElement root, VisualElement panel)
    {
        var tree = Ui.Build(root);
        var ctx = new Dictionary<string, string>();
        foreach (var (name, key) in ContextNames)
        {
            var n = tree.Find(x => x.Name == name && x.IsText && !string.IsNullOrWhiteSpace(x.Text)
                                   && x.Ancestor(a => a.Ve != null && a.Ve.Pointer == panel.Pointer) == null);
            if (n != null) ctx[key] = n.Clean;
        }
        return ctx.Count > 0 ? ctx : null;
    }

    static void SetApplied(string qid, bool ok, string action, string detail)
    {
        _lastApplied = new Applied { question_id = qid, ok = ok, action = action, detail = detail, time = Now() };
        if (ok) Plugin.Instance.Log.LogInfo($"[{action}] {detail}");
        else Plugin.Instance.Log.LogWarning($"[{action}] {detail}");
    }

    // ---------------- dosya G/Ç ----------------
    static T ReadCommand<T>(string path) where T : class
    {
        if (!File.Exists(path)) return null;
        try
        {
            var txt = File.ReadAllText(path);
            File.Delete(path);
            return JsonSerializer.Deserialize<T>(txt, Json);
        }
        catch (IOException) { return null; } // app hâlâ yazıyor -> sonraki tur
        catch (Exception e)
        {
            Plugin.Instance.Log.LogWarning($"Komut okunamadı ({Path.GetFileName(path)}): {e.Message}");
            try { File.Delete(path); } catch { }
            return null;
        }
    }

    static void WriteInactive()
    {
        _state = null; _refs = null;
        Write(new PressState { active = false, last_applied = _lastApplied });
    }

    static void Write(PressState st)
    {
        // seq/time hariç içerik aynıysa yazma
        st.seq = 0; st.time = null;
        var body = JsonSerializer.Serialize(st, Json);
        if (body == _lastWritten) return;
        _lastWritten = body;
        st.seq = ++_seq; st.time = Now();
        try
        {
            Directory.CreateDirectory(Dir);
            var tmp = StatePath + ".tmp";
            File.WriteAllText(tmp, JsonSerializer.Serialize(st, Json));
            File.Move(tmp, StatePath, true);
        }
        catch (IOException) { _lastWritten = ""; } // app okurken kilitli -> sonraki turda tekrar
        catch (Exception e) { Plugin.Instance.Log.LogWarning($"Durum yazılamadı: {e.Message}"); }
    }

    static string Now() => DateTime.Now.ToString("yyyy-MM-ddTHH:mm:ss");

    static VisualElement GetRoot()
    {
        if (_root != null && Ui.Attached(_root)) return _root;
        if (Time.unscaledTime < _nextRootSearch) return null;
        _nextRootSearch = Time.unscaledTime + 3f;
        _root = null;
        foreach (var d in UnityEngine.Object.FindObjectsOfType<UIDocument>())
        {
            if (d == null || d.name != "MainUIDocument") continue;
            _root = d.rootVisualElement;
            break;
        }
        return _root;
    }
}
