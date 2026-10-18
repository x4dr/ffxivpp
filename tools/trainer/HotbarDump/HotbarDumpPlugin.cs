// HotbarDump: a throwaway Dalamud dev plugin used to generate ground truth for
// the ffxivkeytrainer project.
//
// The trainer needs to know what ability sits in each hotbar slot, and that has
// to come out of HOTBAR.DAT, an undocumented binary. This plugin dumps the same
// information out of the running client so the two can be diffed.
//
// It has a main window and a config window on purpose: Dalamud warns when a
// plugin wires neither, and a visible window is the quickest proof that the
// plugin loaded and its services are alive.
//
// Commands:
//   /hbdump         dump the current job's action bar
//   /hbdump all     dump every hotbar addon it can find
//   /hbdump sheets  dump the ClassJob + Action sheets (once; then you can skip it)
//   /hbdump paths   print the output directory
//   /hbt            toggle the main window
//
// Output is JSON in the plugin config directory. See README.md.

using System.Runtime.CompilerServices;
using System.Text.Json;
using Dalamud.Bindings.ImGui;
using Dalamud.Game.Command;
using Dalamud.Game.Gui;
using Dalamud.IoC;
using Dalamud.Plugin;
using Dalamud.Plugin.Services;
using FFXIVClientStructs.FFXIV.Client.UI;
using FFXIVClientStructs.FFXIV.Component.GUI;
using FFXIVClientStructs.STD;
using Lumina.Excel.Sheets;

namespace HotbarDump;

[PluginInterface]
internal partial class Plugin : IDalamudPlugin {
    public string Name => "HotbarDump";

    public int Version => 1;

    [PluginService]
    internal IDalamudPluginInterface Ui { get; private set; } = null!;

    [PluginService]
    internal IGameGui GameGui { get; private set; } = null!;

    [PluginService]
    internal ICommandManager CommandManager { get; private set; } = null!;

    [PluginService]
    internal IObjectTable ObjectTable { get; private set; } = null!;

    [PluginService]
    internal IDataManager DataManager { get; private set; } = null!;

    [PluginService]
    internal IChatGui ChatGui { get; private set; } = null!;

    /// <summary>
    /// Addons that hold hotbar content. Hardcoded on purpose: the event enum
    /// names get renamed between API levels, and this plugin's whole purpose is
    /// to report what is actually there rather than assume it.
    /// </summary>
    /// <summary>
    /// Candidate addon names, tried against every struct known to hold slot
    /// data. These are hypotheses: the dump records which ones resolved and what
    /// action ids they contained, so the job bar gets identified from data
    /// rather than from the name we happened to guess for it.
    /// </summary>
    private static readonly string[] BarAddons = [
        "_ActionBar",      // confirmed to resolve
        "_ActionBarEx",    // confirmed to resolve
        "_ActionCross",    // name implied by AddonActionCross
        "_MainCross",      // name implied by AddonMainCross
        "_CrossHotBar",    // commonly cited name, did not resolve so far
        "_PetActionBar",
        "_ActionBar1",
        "_ActionBar2",
        "_ActionBar3",
        "_ActionBar4",
    ];

    private readonly CommandInfo dumpCommand;
    private readonly CommandInfo toggleCommand;

    // Held as fields so Dispose can unsubscribe the exact same delegates.
    // Unsubscribing with fresh lambdas silently fails and leaves callbacks
    // pointing at a dead plugin after a reload.
    private readonly System.Action openMainUi;
    private readonly System.Action openConfigUi;
    private readonly System.Action drawUi;

    private bool mainOpen;
    private bool configOpen;
    private string lastResult = "nothing run yet";

    /// <summary>
    /// Where dumps go. Falls back to a literal path if the plugin's config
    /// directory is unavailable, because a diagnostic tool that cannot write its
    /// diagnostics is worse than useless.
    /// </summary>
    private string OutputDir {
        get {
            try {
                var configured = this.Ui?.ConfigDirectory?.FullName;
                if (!string.IsNullOrEmpty(configured)) return Path.Combine(configured, "dumps");
            }
            catch {
                // fall through to the fallback below
            }

            return Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                ".xlcore", "pluginConfigs", "HotbarDump", "dumps");
        }
    }

    public Plugin() {
        this.dumpCommand = new CommandInfo(OnDumpCommand) {
            HelpMessage = "Dump hotbars for offline analysis: /hbdump [all|sheets|paths]",
        };
        this.toggleCommand = new CommandInfo((_, _) => this.mainOpen = !this.mainOpen) {
            HelpMessage = "Toggle the HotbarDump window",
        };

        this.CommandManager.AddHandler("hbdump", this.dumpCommand);
        this.CommandManager.AddHandler("hbt", this.toggleCommand);

        this.openMainUi = () => this.mainOpen = true;
        this.openConfigUi = () => this.configOpen = true;
        this.drawUi = DrawUi;

        // Dalamud warns when a plugin wires neither of these.
        this.Ui.UiBuilder.OpenMainUi += this.openMainUi;
        this.Ui.UiBuilder.OpenConfigUi += this.openConfigUi;
        this.Ui.UiBuilder.Draw += this.drawUi;

        // Written on load. If this file does not appear, the plugin never
        // started and no command can possibly be working.
        Write("started.txt",
            $"loaded at {DateTime.Now:O}\n" +
            $"configDirectory = {this.Ui?.ConfigDirectory?.FullName ?? "<null>"}\n" +
            $"outputDir        = {OutputDir}\n" +
            $"services null?   ui={this.Ui is null} gameGui={this.GameGui is null} " +
            $"cmdManager={this.CommandManager is null} objectTable={this.ObjectTable is null} " +
            $"dataManager={this.DataManager is null} chatGui={this.ChatGui is null}\n");
    }

    public void Dispose() {
        this.Ui.UiBuilder.OpenMainUi -= this.openMainUi;
        this.Ui.UiBuilder.OpenConfigUi -= this.openConfigUi;
        this.Ui.UiBuilder.Draw -= this.drawUi;
        this.CommandManager.RemoveHandler("hbdump");
        this.CommandManager.RemoveHandler("hbt");
        GC.SuppressFinalize(this);
    }

    /// <summary>Never throws: used for the self-diagnostics themselves.</summary>
    private void Write(string name, string contents) {
        try {
            Directory.CreateDirectory(OutputDir);
            File.WriteAllText(Path.Combine(OutputDir, name), contents);
            this.lastResult = $"wrote {name}";
        }
        catch (Exception ex) {
            this.lastResult = $"could not write {name}: {ex.Message}";
            this.ChatGui?.Print($"[HotbarDump] {this.lastResult}");
        }
    }

    // ------------------------------------------------------------------ ui

    private void DrawUi() {
        if (this.mainOpen) {
            if (ImGui.Begin("HotbarDump##hbdumpmain", ref this.mainOpen)) {
                ImGui.TextUnformatted($"output: {OutputDir}");
                ImGui.TextUnformatted($"last:   {this.lastResult}");
                ImGui.Separator();

                if (ImGui.Button("Dump ClassJob + Action sheets")) Run("sheets");
                if (ImGui.Button("Dump this job's action bar")) Run("");
                if (ImGui.Button("Dump every bar addon")) Run("all");

                ImGui.Separator();
                if (ImGui.Button("Open config window")) this.configOpen = true;
            }

            ImGui.End();
        }

        if (this.configOpen) {
            if (ImGui.Begin("HotbarDump config##hbdumpconfig", ref this.configOpen)) {
                ImGui.TextUnformatted("No settings. This window exists so the plugin");
                ImGui.TextUnformatted("stops warning about a missing config screen.");
                ImGui.Separator();
                ImGui.TextUnformatted($"Dalamud API level: 15");
            }

            ImGui.End();
        }
    }

    // -------------------------------------------------------------- commands

    private void OnDumpCommand(string command, string arguments) {
        Write($"cmd-{DateTime.Now:HHmmss-fff}.txt", $"command='{command}' arguments='{arguments}'\n");
        Run(arguments);
    }

    private void Run(string arguments) {
        try {
            switch (arguments.Trim()) {
                case "all":
                    DumpBars(BarAddons);
                    break;
                case "sheets":
                    DumpSheets();
                    break;
                case "paths":
                    Say(OutputDir);
                    break;
                default:
                    // No argument, or "job": just the bars that carry job
                    // actions. _ClassActionBar was a guess and does not exist.
                    DumpBars(["_ActionBar", "_ActionCross", "_CrossHotBar", "_MainCross"]);
                    break;
            }
        }
        catch (Exception ex) {
            this.lastResult = $"failed: {ex.GetType().Name}: {ex.Message}";
            Say(this.lastResult);
            Write("last-error.txt", ex.ToString());
        }
    }

    private void Say(string message) => this.ChatGui?.Print($"[HotbarDump] {message}");

    // --------------------------------------------------------------- sheets

    /// <summary>
    /// Dumps the ClassJob sheet (to map a region index to a job) and the Action
    /// sheet (the name/icon lookup the trainer needs anyway).
    /// </summary>
    private void DumpSheets() {
        var jobRows = new List<object>();
        foreach (var row in this.DataManager.GetExcelSheet<ClassJob>()) {
            if (row.RowId == 0) continue;
            jobRows.Add(new {
                id = row.RowId,
                category = row.ClassJobCategory.RowId.ToString(),
                abbreviation = row.Abbreviation.ExtractText(),
                name = row.Name.ExtractText(),
            });
        }

        var actionRows = new List<object>();
        foreach (var row in this.DataManager.GetExcelSheet<Lumina.Excel.Sheets.Action>()) {
            actionRows.Add(new {
                id = row.RowId,
                name = row.Name.ExtractText(),
                icon = row.Icon,
            });
        }

        // Items land in the same hotbar records as abilities, so a resolver
        // needs both. xivapi has no rows for the ids this character uses, so
        // the game's own sheet is the only place they may exist.
        var itemRows = new List<object>();
        foreach (var row in this.DataManager.GetExcelSheet<Lumina.Excel.Sheets.Item>()) {
            itemRows.Add(new {
                id = row.RowId,
                name = row.Name.ExtractText(),
                icon = row.Icon,
            });
        }

        WriteJson("classjob.json", jobRows);
        WriteJson("actionmap.json", actionRows);
        WriteJson("itemmap.json", itemRows);
    }

    private void WriteJson(string name, object payload) {
        Write(name, JsonSerializer.Serialize(payload));
        Say($"wrote {Path.Combine(OutputDir, name)}");
    }

    // ------------------------------------------------------------------ bars

    private void DumpBars(string[] addonNames) {
        var player = this.ObjectTable.LocalPlayer;
        ClassJob? classJob = player is null ? null : player.ClassJob.Value;
        var jobInfo = classJob is null ? null : new {
            id = classJob.Value.RowId,
            category = classJob.Value.ClassJobCategory.RowId.ToString(),
            abbreviation = classJob.Value.Abbreviation.ExtractText(),
            name = classJob.Value.Name.ExtractText(),
        };

        var bars = new List<object>();
        var present = 0;
        foreach (var addonName in addonNames) {
            var bar = ReadAddon(addonName, jobInfo);
            if (bar is not null) present++;
            bars.Add(bar ?? (object)new { addon = addonName, present = false });
        }

        // Job id in the filename so one file per job can share a folder.
        var stamp = $"hotbar-{classJob?.RowId ?? 0}-{DateTime.Now:yyyyMMdd-HHmmss}.json";
        Write(stamp, JsonSerializer.Serialize(new { job = jobInfo, bars }));
        Say($"{present}/{addonNames.Length} addons present; wrote {Path.Combine(OutputDir, stamp)}");
    }

    /// <summary>
    /// Reads one addon by trying each struct that is known to hold slot data.
    ///
    /// Slot data lives in ActionBarSlotVector, not in the node tree. Walking
    /// nodes found 26 nodes and zero icons for every addon, which looked like
    /// an empty bar but is simply the wrong place to look -- the addon really
    /// is that small, because its slots are not nodes.
    ///
    /// Each typed lookup can throw if the addon exists under a different struct
    /// type, so every attempt is independent and a miss just moves on.
    /// </summary>
    private unsafe object? ReadAddon(string addonName, object? job) {
        foreach (var addonIndex in (int[])[0, 1]) {
            var bar = TryGet<AddonActionBar>(addonName, addonIndex);
            if (bar != null) {
                return Wrap(addonName, nameof(AddonActionBar), addonIndex, job,
                    bar->ActionBarSlotVector, bar->SlotCount, bar->ActionBarLayout);
            }

            var barEx = TryGet<AddonActionBarX>(addonName, addonIndex);
            if (barEx != null) {
                return Wrap(addonName, nameof(AddonActionBarX), addonIndex, job,
                    barEx->ActionBarSlotVector, barEx->SlotCount, barEx->ActionBarLayout);
            }

            var cross = TryGet<AddonActionCross>(addonName, addonIndex);
            if (cross != null) {
                return Wrap(addonName, nameof(AddonActionCross), addonIndex, job,
                    cross->ActionBarSlotVector, cross->SlotCount, ActionBarLayout.Layout1X12);
            }
        }

        return null;
    }

    private unsafe T* TryGet<T>(string addonName, int addonIndex) where T : unmanaged {
        try {
            return this.GameGui.GetAddonByName<T>(addonName, addonIndex);
        }
        catch {
            // Wrong struct type for this addon, or not loaded. Either way the
            // next candidate is the interesting one, not the exception.
            return null;
        }
    }

    /// <summary>
    /// ActionId is what the trainer actually needs: it is the same identifier
    /// HOTBAR.DAT stores, so a value found here can be searched for in the file
    /// to pin down its layout. Icons cannot do this job -- 405 is a placeholder
    /// across most of the Action sheet.
    /// </summary>
    private static unsafe object Wrap(
        string addonName, string structName, int addonIndex, object? job,
        StdVector<ActionBarSlot> vec, byte slotCount, ActionBarLayout layout) {
        // SlotCount is maintained separately from the vector, so clamp rather
        // than trust it: reading past the end would be a wild pointer walk.
        var count = (int)slotCount;
        if (count > vec.Count) count = vec.Count;
        if (count < 0) count = 0;

        var slots = new List<object>(count);

        // AsSpan() rather than the Item indexer: Get_Item is an explicit
        // interface implementation and is not callable by name.
        var span = vec.AsSpan();
        for (var i = 0; i < count; i++) {
            ref var slot = ref span[i];
            slots.Add(new {
                index = i,
                actionId = slot.ActionId,
                hotbarId = slot.HotbarId,
            });
        }

        return new {
            addon = addonName,
            structName,
            addonIndex,
            present = true,
            job,
            // 1X12 / 2X6 / 3X4 / 4X3 / 6X2 / 12X1 -- the bar's own geometry.
            layout = (int)layout,
            slotCount = count,
            slots,
        };
    }
}