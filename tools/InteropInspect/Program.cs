// Interop DLL'lerinde tip arar ve üyelerini listeler (oyun çalıştırmadan keşif).
// Kullanım: dotnet run -- <arama> [--members] [--exact] [--asm <dll adı parçası>]
//   ortam: FM_GAMEDIR (varsayılan Steam yolu)
using System.Reflection;

var gameDir = Environment.GetEnvironmentVariable("FM_GAMEDIR")
    ?? @"C:\Program Files (x86)\Steam\steamapps\common\Football Manager 27";
var interop = Path.Combine(gameDir, "BepInEx", "interop");
var core = Path.Combine(gameDir, "BepInEx", "core");
var rt = Path.GetDirectoryName(typeof(object).Assembly.Location)!;

if (args.Length == 0) { Console.WriteLine("arama metni ver"); return; }
string query = args[0];
bool members = args.Contains("--members");
bool exact = args.Contains("--exact");
bool inherited = args.Contains("--inherited");
bool strippedOnly = args.Contains("--stripped");   // sadece "Method unstripping failed" atan (oyunda ÇALIŞMAYAN) üyeleri işaretle
string asmFilter = null;
int ai = Array.IndexOf(args, "--asm"); if (ai >= 0 && ai + 1 < args.Length) asmFilter = args[ai + 1];

var paths = Directory.GetFiles(interop, "*.dll").Concat(Directory.GetFiles(core, "*.dll"))
    .Concat(Directory.GetFiles(rt, "*.dll")).GroupBy(Path.GetFileName).Select(g => g.First()).ToList();
using var mlc = new MetadataLoadContext(new PathAssemblyResolver(paths), "System.Private.CoreLib");

const BindingFlags F = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;
int shown = 0;
foreach (var file in Directory.GetFiles(interop, "*.dll"))
{
    if (asmFilter != null && !Path.GetFileName(file).Contains(asmFilter, StringComparison.OrdinalIgnoreCase)) continue;
    Assembly asm; Type[] types;
    try { asm = mlc.LoadFromAssemblyPath(file); types = asm.GetTypes(); }
    catch (ReflectionTypeLoadException e) { types = e.Types.Where(t => t != null).ToArray(); asm = null; }
    catch { continue; }
    foreach (var t in types)
    {
      try {
        bool hit = exact ? t.Name == query || t.FullName == query
                         : (t.FullName ?? t.Name).Contains(query, StringComparison.OrdinalIgnoreCase);
        if (!hit) continue;
        if (++shown > 200) { Console.WriteLine("... (200+ sonuç, aramayı daralt)"); return; }
        var chain = new List<string>();
        try { for (var b = t.BaseType; b != null; b = b.BaseType) chain.Add(b.FullName ?? b.Name); } catch { chain.Add("?"); }
        Console.WriteLine($"[{Path.GetFileName(file)}] {t.FullName}  :  {string.Join(" -> ", chain)}");
        if (!members) continue;
        var levels = new List<Type> { t };
        if (inherited) { try { for (var b = t.BaseType; b != null && b.FullName != "Il2CppSystem.Object" && b.FullName != "Il2CppInterop.Runtime.InteropTypes.Il2CppObjectBase"; b = b.BaseType) levels.Add(b); } catch { } }
        foreach (var lt in levels)
        {
            if (lt != t) Console.WriteLine($"  --- {lt.FullName}");
            try
            {
                foreach (var p in lt.GetProperties(F)) Console.WriteLine($"    prop  {Safe(() => p.PropertyType.Name)} {p.Name}");
                foreach (var f in lt.GetFields(F)) { if (f.Name.StartsWith("NativeFieldInfoPtr") || f.Name.StartsWith("NativeMethodInfoPtr")) continue; Console.WriteLine($"    field {Safe(() => f.FieldType.Name)} {f.Name}"); }
                foreach (var m in lt.GetMethods(F).Cast<MethodBase>().Concat(lt.GetConstructors(F)))
                {
                    if (m.IsSpecialName && m is not ConstructorInfo && !(m.Name.StartsWith("set_") || m.Name.StartsWith("get_"))) continue;
                    var ps = Safe(() => string.Join(", ", m.GetParameters().Select(x => x.ParameterType.Name + " " + x.Name)));
                    var ret = m is MethodInfo mi ? Safe(() => mi.ReturnType.Name) : "ctor";
                    var mark = IsStrippedStub(m) ? "  [STRIPPED: oyunda çalışmaz]" : "";
                    if (args.Contains("--il")) mark += "  IL=" + Safe(() => BitConverter.ToString(m.GetMethodBody()?.GetILAsByteArray() ?? Array.Empty<byte>()).Replace("-", "")[..Math.Min(160, (m.GetMethodBody()?.GetILAsByteArray()?.Length ?? 0) * 2)]);
                    if (strippedOnly && mark == "") continue;
                    Console.WriteLine($"    {(m.IsStatic ? "static " : "")}{ret} {m.Name}({ps}){mark}");
                }
            }
            catch (Exception e) { Console.WriteLine($"    (üye okunamadı: {e.GetType().Name})"); }
        }
      } catch { }
    }
}
if (shown == 0) Console.WriteLine("bulunamadı");

static string Safe(Func<string> f) { try { return f(); } catch { return "?"; } }

// Il2CppInterop, oyunda gövdesi olmayan ve yeniden üretemediği metotlara sadece
// `throw new NotSupportedException("Method unstripping failed")` koyar: ldstr, newobj, throw (11 bayt).
static bool IsStrippedStub(MethodBase m)
{
    try
    {
        var il = m.GetMethodBody()?.GetILAsByteArray();
        // ldstr(5) newobj(5) throw(1) [+ ret(1)]
        return il != null && il.Length <= 13 && il[0] == 0x72 && Array.IndexOf(il, (byte)0x7A, 10) >= 0;
    }
    catch { return false; }
}
