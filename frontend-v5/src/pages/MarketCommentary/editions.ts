/**
 * Market commentary editions published by tools/closing_bell (see its README): the nightly Closing Bell and,
 * since 3 Nov 2026, the morning Opening Bell (after the 9:00-9:08 pre-open).
 *
 * Files are static, served by the edge nginx from the site root (NOT under the /v5/ app base):
 *   /downloads/<kind>-bell/index.json                  { latest, editions: Edition[] }   newest first
 *   /downloads/<kind>-bell/<date>/<kind>-bell-<date>.mp4, poster.jpg, captions.vtt, transcript.json
 * No backend route: a missing or unreadable index.json is shown as an error, never replaced by sample data.
 */
import { useQuery } from "@tanstack/react-query";

export type EditionKind = "closing" | "opening";

export const editionsBase = (kind: EditionKind = "closing") => `/downloads/${kind}-bell/`;
export const EDITIONS_BASE = editionsBase("closing");

export type EditionLanguage = { code: string; label: string; video: string; captions: string; transcript: string };

export type Edition = {
  date: string;
  /** "opening" for the morning edition; older closing editions have no kind. */
  kind?: EditionKind;
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

export const fileUrl = (path: string, kind: EditionKind = "closing") => editionsBase(kind) + path;

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url, { cache: "no-cache" });
  if (r.status === 404) throw new Error("not-found");
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (await r.json()) as T;
}

/** The edition list of one show. No editions means none published yet (index.json absent). */
export function useEditions(kind: EditionKind = "closing") {
  return useQuery({
    queryKey: [`${kind}-bell`, "index"],
    queryFn: async (): Promise<EditionIndex> => {
      try {
        return await getJson<EditionIndex>(editionsBase(kind) + "index.json");
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

export function useTranscript(edition: Edition | undefined, lang: EditionLanguage | undefined, kind: EditionKind = "closing") {
  return useQuery({
    queryKey: [`${kind}-bell`, "transcript", edition?.date, lang?.code],
    queryFn: () => getJson<Transcript>(fileUrl(lang!.transcript, kind)),
    enabled: !!edition && !!lang,
    staleTime: 60 * 60 * 1000,
    retry: 1,
  });
}
