using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.RegularExpressions;
using FM27PressVoice;

// Kullanım: DumpReplay <ui_dump_N.txt | klasör>...   (--json: tam JSON, yoksa özet)
Console.OutputEncoding = System.Text.Encoding.UTF8;
bool full = args.Contains("--json");
string outDir = null; { int oi = Array.IndexOf(args, "--out"); if (oi >= 0) { outDir = args[oi + 1]; Directory.CreateDirectory(outDir); } }
var files = new List<string>();
foreach (var a in args.Where((a, i) => !a.StartsWith("--") && (i == 0 || args[i - 1] != "--out")))
    if (Directory.Exists(a)) files.AddRange(Directory.GetFiles(a, "ui_dump_*.txt").OrderBy(f => int.Parse(Regex.Match(Path.GetFileName(f), @"\d+").Value)));
    else files.Add(a);

var json = new JsonSerializerOptions { IncludeFields = true, WriteIndented = true, Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping };
var line = new Regex(@"^(?<ind> *)(?<type>\S+) name='(?<name>[^']*)' ?(?<cls>\.\S*)?(?: text='(?<text>.*)')?$");
int fail = 0;
foreach (var f in files)
{
    var root = new Node("<root>", new HashSet<string>(), null);
    var stack = new List<(int depth, Node node)> { (-1, root) };
    foreach (var raw in File.ReadLines(f))
    {
        var l = raw.TrimStart('\uFEFF');
        if (l.StartsWith("# UIDocument")) { stack.RemoveRange(1, stack.Count - 1); continue; }
        var m = line.Match(l);
        if (!m.Success) continue;
        int depth = m.Groups["ind"].Length / 2;
        var cls = new HashSet<string>((m.Groups["cls"].Value ?? "").Split('.', StringSplitOptions.RemoveEmptyEntries));
        string text = m.Groups["text"].Success ? m.Groups["text"].Value.Replace("\n", "\n") : null;
        var n = new Node(m.Groups["name"].Value, cls, text);
        while (stack[^1].depth >= depth) stack.RemoveAt(stack.Count - 1);
        n.Parent = stack[^1].node; n.Parent.Children.Add(n);
        stack.Add((depth, n));
    }

    var panel = PressReader.FindPanelNode(root, out var screen, out var hint);
    Console.WriteLine($"=== {Path.GetFileName(Path.GetDirectoryName(f))}/{Path.GetFileName(f)}");
    if (panel == null) { Console.WriteLine("  panel YOK"); fail++; continue; }
    var st = PressReader.ReadNode(panel, screen, hint, null, out _);
    if (outDir != null)
    {
        st.ready = !string.IsNullOrEmpty(st.game_question) && st.categories.Exists(c => c.options.Count > 0);
        File.WriteAllText(Path.Combine(outDir, "dump_" + Regex.Match(Path.GetFileName(f), @"\d+").Value + ".json"),
                          JsonSerializer.Serialize(st, json), new System.Text.UTF8Encoding(false));
    }
    if (full) { Console.WriteLine(JsonSerializer.Serialize(st, json)); continue; }
    Console.WriteLine($"  {st.screen} hint={st.event_hint} title='{st.title}' soru={st.question_index}/{st.question_total} rakip={st.opponent} lig={st.competition} hava={st.overall_mood} menajer={st.manager_name}");
    Console.WriteLine($"  gazeteci: {st.journalist?.name} | {st.journalist?.outlet} | {st.journalist?.mood} ({st.journalist?.mood_class})  kartlar={st.journalists?.Count} aktif={st.journalists?.FirstOrDefault(j => j.active)?.name}");
    Console.WriteLine($"  SORU: {st.game_question}");
    if (st.previous_npc_bubbles != null) Console.WriteLine($"  önceki balonlar: {st.previous_npc_bubbles.Count}");
    foreach (var c in st.categories)
    {
        Console.WriteLine($"  [{c.index}] {c.title} ({c.sentiment})");
        foreach (var o in c.options) Console.WriteLine($"       {o.index}{(o.enabled ? "" : " (kapalı)")}: {o.text}");
    }
    if (string.IsNullOrEmpty(st.game_question) || st.categories.Count == 0) fail++;
}
Console.WriteLine($"\n{files.Count} döküm, {fail} eksik okuma");
