using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using UnityEngine.UIElements;

namespace FM27PressVoice;

/// UI Toolkit ağacının yönetilen (managed) kopyası. Tur başına bir kez kurulur; sorgular interop çağrısı yapmadan
/// bu ağaç üzerinde çalışır. Class ve metin sadece istenince (lazy) okunur.
internal sealed class Node
{
    public VisualElement Ve;
    public string Name;
    public Node Parent;
    public readonly List<Node> Children = new();

    HashSet<string> _classes;
    string _text; bool _textRead;
    bool? _isText;

    public Node() { }

    /// Çevrimdışı düğüm (döküm dosyasından; testler için). Ve null kalır.
    public Node(string name, HashSet<string> classes, string text)
    {
        Name = name; _classes = classes; _text = text; _textRead = true; _isText = text != null;
    }

    public HashSet<string> Classes
    {
        get
        {
            if (_classes != null) return _classes;
            _classes = new HashSet<string>();
            try
            {
                var list = Ve.GetClassesForIteration();
                if (list != null) for (int i = 0; i < list.Count; i++) _classes.Add(list[i]);
            }
            catch { }
            return _classes;
        }
    }

    public bool Has(string cls) => Classes.Contains(cls);

    public string ClassWithPrefix(string prefix, string exclude = null)
    {
        foreach (var c in Classes)
            if (c.StartsWith(prefix, StringComparison.Ordinal) && c != exclude) return c;
        return null;
    }

    public bool IsText
    {
        get
        {
            if (_isText == null) { try { _isText = Ve.TryCast<TextElement>() != null; } catch { _isText = false; } }
            return _isText.Value;
        }
    }

    /// Ham metin (rich text etiketleriyle). Metin elemanı değilse null.
    public string Text
    {
        get
        {
            if (_textRead) return _text;
            _textRead = true;
            try { var te = Ve.TryCast<TextElement>(); _text = te?.text; } catch { _text = null; }
            return _text;
        }
    }

    public string Clean => Ui.Clean(Text);

    // ---- sorgular (alt ağaçta, derinlik öncelikli, kendisi dahil değil) ----
    public Node Find(Func<Node, bool> pred)
    {
        foreach (var c in Children)
        {
            if (pred(c)) return c;
            var r = c.Find(pred);
            if (r != null) return r;
        }
        return null;
    }

    public Node FindName(string name) => Find(n => n.Name == name);

    public List<Node> FindAll(Func<Node, bool> pred, bool descendIntoMatches = true, List<Node> acc = null)
    {
        acc ??= new List<Node>();
        foreach (var c in Children)
        {
            bool hit = pred(c);
            if (hit) acc.Add(c);
            if (!hit || descendIntoMatches) c.FindAll(pred, descendIntoMatches, acc);
        }
        return acc;
    }

    public Node Ancestor(Func<Node, bool> pred)
    {
        for (var p = Parent; p != null; p = p.Parent) if (pred(p)) return p;
        return null;
    }
}

internal static class Ui
{
    static readonly Regex Tags = new("<[^>]+>", RegexOptions.Compiled);
    static readonly Regex Ws = new(@"\s+", RegexOptions.Compiled);

    public static string Clean(string s)
    {
        if (string.IsNullOrEmpty(s)) return s ?? "";
        s = Tags.Replace(s, "");
        s = s.Replace("\\n", " ").Replace('\n', ' ');
        return Ws.Replace(s, " ").Trim();
    }

    /// VisualElement alt ağacını Node ağacına kopyalar.
    public static Node Build(VisualElement ve, Node parent = null, int depth = 0, int maxDepth = 120)
    {
        var n = new Node { Ve = ve, Parent = parent };
        try { n.Name = ve.name ?? ""; } catch { n.Name = ""; }
        if (depth >= maxDepth) return n;
        int count;
        try { count = ve.childCount; } catch { count = 0; }
        for (int i = 0; i < count; i++)
        {
            VisualElement c;
            try { c = ve[i]; } catch { continue; }
            if (c != null) n.Children.Add(Build(c, n, depth + 1, maxDepth));
        }
        return n;
    }

    public static bool HasClass(VisualElement ve, string cls)
    {
        try { return ve.ClassListContains(cls); } catch { return false; }
    }

    /// SIText ise SetText (oyunun stil hattından geçer), değilse TextElement.text.
    public static bool SetText(VisualElement ve, string text)
    {
        try
        {
            var si = ve.TryCast<SI.Bindable.SIText>();
            if (si != null) { si.SetText(text); return true; }
            var te = ve.TryCast<TextElement>();
            if (te != null) { te.text = text; return true; }
        }
        catch (Exception e) { Plugin.Instance.Log.LogWarning($"SetText hatası: {e.Message}"); }
        return false;
    }

    public static string GetText(VisualElement ve)
    {
        try { return ve.TryCast<TextElement>()?.text; } catch { return null; }
    }

    public static bool Attached(VisualElement ve)
    {
        try { return ve != null && ve.panel != null; } catch { return false; }
    }
}
