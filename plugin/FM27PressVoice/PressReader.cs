using System;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using UnityEngine.UIElements;

namespace FM27PressVoice;

/// docs/ui-map.md'ye göre basın ekranını okur.
internal static class PressReader
{
    static readonly (string panel, string screen, string hint)[] Panels =
    {
        ("PressConferenceCard", "press_conference", null),
        ("TunnelInterviewPanel", "tunnel_interview", "pre_match"),
        ("PostMatchTunnelInterviewPanel", "post_match_tunnel_interview", "post_match"),
    };

    static readonly Regex Counter = new(@"\((\d+)\s*/\s*(\d+)\)", RegexOptions.Compiled);
    const string OptionInnerClass = "speakto-body-header-suggestion-button--action-secondary";

    /// Kökten (sığ) açık basın panelini bulur. Panel'ler MainUIDocument altında derinlik ~2'de.
    public static VisualElement FindPanel(VisualElement root, out string screen, out string hint)
    {
        screen = null; hint = null;
        return FindPanelRec(root, 0, ref screen, ref hint);
    }

    static VisualElement FindPanelRec(VisualElement ve, int depth, ref string screen, ref string hint)
    {
        if (depth > 4 || ve == null) return null;
        int count;
        try { count = ve.childCount; } catch { return null; }
        for (int i = 0; i < count; i++)
        {
            VisualElement c;
            try { c = ve[i]; } catch { continue; }
            if (c == null) continue;
            string name;
            try { name = c.name; } catch { name = null; }
            foreach (var p in Panels)
            {
                if (name == p.panel && (Ui.HasClass(c, "panel--visible") || Ui.HasClass(c, "panel--open")))
                {
                    screen = p.screen; hint = p.hint;
                    return c;
                }
            }
            var r = FindPanelRec(c, depth + 1, ref screen, ref hint);
            if (r != null) return r;
        }
        return null;
    }

    /// Çevrimdışı (döküm) ağaçta panel arar.
    public static Node FindPanelNode(Node root, out string screen, out string hint)
    {
        string s = null, h = null;
        var found = root.Find(n =>
        {
            foreach (var p in Panels)
                if (n.Name == p.panel && (n.Has("panel--visible") || n.Has("panel--open"))) { s = p.screen; h = p.hint; return true; }
            return false;
        });
        screen = s; hint = h;
        return found;
    }

    public static PressState Read(VisualElement panelVe, string screen, string hint,
                                  Func<Node, string> textOf, out PressRefs refs)
        => ReadNode(Ui.Build(panelVe), screen, hint, textOf, out refs);

    /// textOf: override edilmiş elemanlar için orijinal metni döndürmek üzere (Bridge sağlar); null = ham metin.
    public static PressState ReadNode(Node root, string screen, string hint,
                                      Func<Node, string> textOf, out PressRefs refs)
    {
        refs = new PressRefs();
        textOf ??= n => n.Text;
        var st = new PressState { active = true, screen = screen, event_hint = hint };

        string T(Node n) => n == null ? null : textOf(n);
        string C(Node n) => Ui.Clean(T(n));

        // --- başlık ---
        var counter = root.FindName("FinishedText");
        if (counter != null)
        {
            var m = Counter.Match(C(counter) ?? "");
            if (m.Success)
            {
                st.question_index = int.Parse(m.Groups[1].Value);
                st.question_total = int.Parse(m.Groups[2].Value);
            }
        }
        var titleNode = root.FindName("PanelTitleText");
        if (titleNode == null)
        {
            var pressInfo = root.FindName("PressInfo");
            titleNode = pressInfo?.Find(n => n.IsText && !string.IsNullOrEmpty(n.Text));
        }
        st.title = C(titleNode);
        st.competition = NullIfEmpty(C(root.FindName("CompetitionName")));
        var bottomInfo = root.FindName("BottomInfo");
        if (bottomInfo != null)
            st.opponent = NullIfEmpty(C(bottomInfo.Find(n => n.IsText && n.Name != "CompetitionName" && !string.IsNullOrEmpty(n.Text))));
        var header = root.Find(n => n.Has("fullscreen-experience-header"));
        if (header != null)
            st.overall_mood = NullIfEmpty(C(header.Find(n => n.IsText && n.ClassWithPrefix("body-language-") != null)));

        // --- soru soran (üst şerit): IsJournalist, boşsa IsStaff ---
        Node branch = null; Journalist asker = null;
        foreach (var bn in new[] { "IsJournalist", "IsStaff" })
        {
            var b = root.FindName(bn);
            if (b == null) continue;
            var nh = b.FindName("NameAndHierarhy");
            var nameNode = nh?.Find(n => n.IsText && n.Has("heading-md"));
            var name = C(nameNode);
            if (string.IsNullOrEmpty(name)) continue;
            branch = b;
            asker = new Journalist
            {
                name = name,
                outlet = NullIfEmpty(C(nh.Find(n => n.IsText && n.Has("body-md") && n.Has("global-text-secondary")))),
                active = true,
            };
            var moodNode = b.Find(n => n.IsText && MoodClass(n) != null);
            asker.mood = NullIfEmpty(C(moodNode));
            asker.mood_class = moodNode == null ? null : MoodClass(moodNode);
            break;
        }
        st.journalist = asker;

        // --- soru balonları ---
        if (branch != null)
        {
            var list = branch.FindName("SpeechBubbleList");
            if (list != null)
            {
                var npcTexts = new List<Node>();
                foreach (var npc in list.FindAll(n => n.Name == "NPCBubbleVisible", descendIntoMatches: false))
                {
                    var t = npc.Find(n => n.IsText && n.Name == "text" && !string.IsNullOrEmpty(T(n)));
                    if (t != null) npcTexts.Add(t);
                }
                foreach (var hb in list.FindAll(n => n.Name == "HumanBubbleVisible", descendIntoMatches: false))
                {
                    var t = hb.Find(n => n.IsText && n.Name == "text");
                    if (t != null) refs.HumanBubbleTexts.Add(t.Ve);
                }
                if (npcTexts.Count > 0)
                {
                    var last = npcTexts[^1];
                    refs.QuestionText = last.Ve;
                    st.game_question_raw = T(last);
                    st.game_question = Ui.Clean(st.game_question_raw);
                    if (npcTexts.Count > 1)
                    {
                        st.previous_npc_bubbles = new List<string>();
                        for (int i = 0; i < npcTexts.Count - 1; i++) st.previous_npc_bubbles.Add(C(npcTexts[i]));
                    }
                }
            }
        }

        // --- gazeteci kartları ---
        var jl = root.FindName("Journalists");
        if (jl != null)
        {
            st.journalists = new List<Journalist>();
            foreach (var item in jl.FindAll(n => n.Has("wrapped-object-list-item"), descendIntoMatches: false))
            {
                var info = item.FindName("NonPlayerInfo");
                if (info == null) continue;
                var moodNode = info.Find(n => n.IsText && MoodClass(n) != null);
                st.journalists.Add(new Journalist
                {
                    name = NullIfEmpty(C(info.FindName("Name"))),
                    outlet = NullIfEmpty(C(info.FindName("Publication"))),
                    mood = NullIfEmpty(C(moodNode)),
                    mood_class = moodNode == null ? null : MoodClass(moodNode),
                    active = item.Find(n => n.Has("meeting-tiles--background-active")) != null,
                });
            }
        }

        // --- yönetici adı ---
        var sender = root.FindName("PrimarySender");
        st.manager_name = NullIfEmpty(C(sender?.Find(n => n.IsText && n.Name == "Name")));

        // --- cevap kategorileri ---
        st.categories = new List<Category>();
        var catList = root.FindName("NewsResponseOptionalButtons");
        if (catList != null)
        {
            foreach (var item in catList.FindAll(n => n.Name == "SpeakToOptionalActionButton", descendIntoMatches: false))
            {
                var gt = item.Find(n => n.Name == "GroupTitle" && n.IsText);
                if (gt == null || string.IsNullOrEmpty(gt.Text)) continue; // başlıksız opsiyonel eylem butonu
                var cat = new Category
                {
                    index = st.categories.Count,
                    title = C(gt),
                    sentiment = gt.ClassWithPrefix("speakto-header-", "speakto-header-base")?.Substring("speakto-header-".Length),
                };
                var optRefs = new List<OptionRef>();
                foreach (var ab in item.FindAll(n => n.Name == "SpeakToMeetingAnswerActionButton", descendIntoMatches: false))
                {
                    var outer = ab.Find(n => n.Name == "StandardButton");
                    var inner = ab.Find(n => n.Has(OptionInnerClass)) ?? outer;
                    var text = (inner ?? ab).Find(n => n.IsText && n.Name == "text" && !string.IsNullOrEmpty(n.Text))
                               ?? ab.Find(n => n.IsText && n.Name == "text");
                    if (outer == null || text == null) continue;
                    cat.options.Add(new Option
                    {
                        index = cat.options.Count,
                        text = C(text),
                        enabled = !outer.Has("unity-disabled") && !(inner?.Has("unity-disabled") ?? false),
                    });
                    optRefs.Add(new OptionRef { Outer = outer.Ve, Inner = inner?.Ve, Text = text.Ve });
                }
                st.categories.Add(cat);
                refs.Options.Add(optRefs);
            }
        }

        st.question_id = Hash($"{st.screen}|{asker?.name}|{st.game_question}|{st.question_index}");
        return st;
    }

    static string MoodClass(Node n)
    {
        var c = n.ClassWithPrefix("body-language-");
        if (c == null || !c.EndsWith("-text-colour", StringComparison.Ordinal)) return null;
        return c.Substring("body-language-".Length, c.Length - "body-language-".Length - "-text-colour".Length);
    }

    static string NullIfEmpty(string s) => string.IsNullOrEmpty(s) ? null : s;

    static string Hash(string s)
    {
        using var sha = SHA1.Create();
        var b = sha.ComputeHash(Encoding.UTF8.GetBytes(s ?? ""));
        var sb = new StringBuilder();
        for (int i = 0; i < 6; i++) sb.Append(b[i].ToString("x2"));
        return sb.ToString();
    }
}
