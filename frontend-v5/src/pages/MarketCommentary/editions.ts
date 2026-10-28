/**
 * Closing Bell editions — the nightly market-wrap videos published by tools/closing_bell (see its README).
 *
 * Files are static, served by the edge nginx from the site root (NOT under the /v5/ app base):
 *   /downloads/closing-bell/index.json                 { latest, editions: Edition[] }   newest first
 *   /downloads/closing-bell/<date>/closing-bell-<date>.mp4, poster.jpg, captions.vtt, transcript.json
 * No backend route: a missing or unreadable index.json is shown as an error, never replaced by sample data.
 */
import { useQuery } from "@tanstack/react-query";

export const EDITIONS_BASE = "/downloads/closing-bell/";

export type EditionLanguage = { code: string; label: string; video: string; captions: string; transcript: string };

export type Edition = {
  date: string;
  day_long: string;
  title: string;
  duration_s: number;
  duration_label: string;
  headlines: { kicker: string; big: string; small: string }[];
  segments: { tag: string; title: string }[];
  files: { video: string; poster: string; captions: string; transcript: string };
  /** Narration languages (English first). Older editions without it are English only (`files`). */
  languages?: EditionLanguage[];
  published_at: string;
  music: string;
  disclaimer: string;
};

export type EditionIndex = { latest: string | null; updated_at?: string; editions: Edition[] };

export type Transcript = {
  date: string;
  lang?: string;
  cue_count: number;
  sections: { tag: string; title: string; start: string; cues: { t: string; text: string; sup: string }[] }[];
};

export const fileUrl = (path: string) => EDITIONS_BASE + path;

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url, { cache: "no-cache" });
  if (r.status === 404) throw new Error("not-found");
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (await r.json()) as T;
}

/** The edition list. `null` data means none published yet (index.json absent). */
export function useEditions() {
  return useQuery({
    queryKey: ["closing-bell", "index"],
    queryFn: async (): Promise<EditionIndex> => {
      try {
        return await getJson<EditionIndex>(EDITIONS_BASE + "index.json");
      } catch (e) {
        if ((e as Error).message === "not-found") return { latest: null, editions: [] };
        throw e;
      }
    },
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });
}

/** The edition's languages; editions published before the language versions are English only. */
export function languagesOf(edition: Edition): EditionLanguage[] {
  if (edition.languages && edition.languages.length) return edition.languages;
  return [{ code: "en", label: "English", video: edition.files.video, captions: edition.files.captions, transcript: edition.files.transcript }];
}

export function useTranscript(edition: Edition | undefined, lang: EditionLanguage | undefined) {
  return useQuery({
    queryKey: ["closing-bell", "transcript", edition?.date, lang?.code],
    queryFn: () => getJson<Transcript>(fileUrl(lang!.transcript)),
    enabled: !!edition && !!lang,
    staleTime: 60 * 60 * 1000,
    retry: 1,
  });
}
