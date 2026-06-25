import { useCallback, useEffect, useState } from "react";
import { Capacitor } from "@capacitor/core";
import { Button } from "@/components/ui/button";
import { readDeviceLog, clearDeviceLog, deviceLogUri, LOG_FILE } from "@/lib/device-log";

/**
 * /debug-logs — on-device log viewer for debugging the native app.
 * Shows the persistent log file with Copy / Share / Clear so the exact error
 * (e.g. a Google sign-in failure) can be retrieved without a computer.
 */
export default function DebugLogsPage() {
  const [text, setText] = useState("Loading…");
  const [uri, setUri] = useState<string | null>(null);
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    setText((await readDeviceLog()) || "(log is empty — trigger the error, then reload)");
    setUri(await deviceLogUri());
  }, []);

  useEffect(() => { void load(); }, [load]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setNote("Copied to clipboard ✓");
    } catch {
      setNote("Copy failed — long-press the text to select it manually.");
    }
  };

  const share = async () => {
    try {
      const { Share } = await import("@capacitor/share");
      // Prefer sharing the file itself; fall back to sharing the text.
      if (uri) {
        await Share.share({ title: "Nivesh debug log", url: uri });
      } else {
        await Share.share({ title: "Nivesh debug log", text });
      }
    } catch (e) {
      setNote("Share unavailable: " + (e instanceof Error ? e.message : String(e)));
    }
  };

  const clear = async () => {
    await clearDeviceLog();
    setNote("Cleared.");
    void load();
  };

  return (
    <div className="min-h-screen bg-bg px-5 py-6 max-w-[760px] mx-auto">
      <h1 className="font-display text-2xl tracking-tightish">Debug logs</h1>
      <p className="text-[12.5px] text-ink-2 mt-1">
        Platform: <span className="font-mono">{Capacitor.getPlatform()}</span>
        {uri && <> · file: <span className="font-mono break-all">{uri}</span></>}
        {!uri && <> · file: <span className="font-mono">{LOG_FILE}</span> (in-memory on web)</>}
      </p>

      <div className="flex flex-wrap gap-2 mt-4">
        <Button variant="accent" size="sm" onClick={copy}>Copy</Button>
        <Button variant="outline" size="sm" onClick={share}>Share</Button>
        <Button variant="outline" size="sm" onClick={() => void load()}>Reload</Button>
        <Button variant="ghost" size="sm" onClick={clear}>Clear</Button>
      </div>
      {note && <div className="font-mono text-[11px] text-accent mt-2">{note}</div>}

      <pre className="mt-4 p-3 rounded-md bg-surface-1 border border-hairline text-[11px] leading-relaxed whitespace-pre-wrap break-words overflow-auto max-h-[70vh]">
        {text}
      </pre>
    </div>
  );
}
