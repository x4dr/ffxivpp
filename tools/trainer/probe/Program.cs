// Reflection probe: the answer to "does this type/member actually exist?".
//
// The Dalamud, Lumina and FFXIVClientStructs assemblies are all on disk, so
// there is no reason to guess at API names. Point this at a type and it prints
// the real members. See AGENTS.md - guessing names cost several build cycles.
//
//   dotnet run -c Release -- AtkResNode            # search FFXIVClientStructs
//   dotnet run -c Release -- CommandInfo Dalamud   # a specific assembly
//   dotnet run -c Release -- Icon                   # substring search
//
// DALAMUD_HOME overrides the assembly directory.

using System.Reflection;

var dal = Environment.GetEnvironmentVariable("DALAMUD_HOME")
    ?? $"{Environment.GetFolderPath(Environment.SpecialFolder.UserProfile)}"
       + "/.xlcore/dalamud/Hooks/15.0.3.7";

if (args.Length == 0) {
    Console.Error.WriteLine("usage: probe <TypeName> [Dalamud|Lumina|FFXIVClientStructs|all]");
    return 1;
}

// Load every assembly in the Dalamud folder so type resolution works.
var files = Directory.GetFiles(dal, "*.dll").ToList();
files.AddRange(Directory.GetFiles(Path.GetDirectoryName(typeof(object).Assembly.Location)!, "*.dll"));

using var mlc = new MetadataLoadContext(new PathAssemblyResolver(files.Distinct()));

var wanted = args[0];
var scope = args.Length > 1 ? args[1] : "all";
var assemblies = new[] { "FFXIVClientStructs", "Dalamud", "Lumina", "Lumina.Excel" };

int found = 0;
foreach (var name in assemblies) {
    if (scope != "all" && scope != name) continue;
    var path = Path.Combine(dal, name + ".dll");
    if (!File.Exists(path)) continue;

    Assembly asm;
    try { asm = mlc.LoadFromAssemblyPath(path); }
    catch (Exception ex) { Console.WriteLine($"[{name}] could not load: {ex.Message}"); continue; }

    Type[] types;
    try { types = asm.GetTypes(); }
    catch (ReflectionTypeLoadException ex) { types = ex.Types.Where(t => t is not null).ToArray()!; }

    foreach (var t in types.Where(t => t.IsPublic && t.Name.Contains(wanted, StringComparison.OrdinalIgnoreCase))) {
        Console.WriteLine($"\n=== {t.FullName}  ({name}) ===");
        found++;

        foreach (var f in t.GetFields(BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static)
                           .OrderBy(x => x.Name))
            // ToString() rather than Name: the element type of StdVector<T> is
            // the whole point when deciding between value and pointer storage.
            Console.WriteLine($"  field  {f.FieldType.ToString(),-60} {f.Name}");

        foreach (var p in t.GetProperties(BindingFlags.Public | BindingFlags.Instance)
                           .OrderBy(x => x.Name))
            Console.WriteLine($"  prop   {p.PropertyType.Name,-30} {p.Name} (set={p.CanWrite})");

        foreach (var c in t.GetConstructors())
            Console.WriteLine($"  ctor   ({string.Join(", ", c.GetParameters().Select(p => p.ParameterType.Name))})");

        foreach (var m in t.GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly)
                           .Where(m => !m.IsSpecialName)
                           .OrderBy(x => x.Name))
            Console.WriteLine($"  method {m.ReturnType.Name,-30} {m.Name}({string.Join(", ", m.GetParameters().Select(p => p.ParameterType.Name))})");
    }
}

if (found == 0) Console.WriteLine($"no public type matching '{wanted}' in {dal}");
return 0;