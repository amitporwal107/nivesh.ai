/**
 * The Nivesh Copilot user guide: one 16:43 video in five languages (the Closing Bell voices), plus the written guide.
 *
 *   videos + captions + poster   /downloads/promo/nivesh-copilot-da8691abbb/   (published on the staging host's
 *                                 /downloads; too large for git, built by the promo pipeline of 4–5 Nov 2026)
 *   written guide, per language  <BASE_URL>user-guide/<lang>.json              (frontend-v5/public/user-guide)
 *
 * Every language shares one picture and one timeline, so a section's time is the same in all five videos and the
 * playback position can carry over a language switch. Used by the /user-guide page and the homepage section.
 */
import { useQuery } from "@tanstack/react-query";

export const GUIDE_FILES = "/downloads/promo/nivesh-copilot-da8691abbb/";
export const GUIDE_DURATION_LABEL = "16:43";
export const GUIDE_RECORDED = "Recorded on Nivesh on 4–5 Nov 2026";

export type GuideLangCode = "en" | "hi" | "ta" | "mr" | "gu";

export interface GuideLang {
  code: GuideLangCode;
  /** The button label, in its own script. */
  label: string;
  /** The language's English name (aria labels, alt text). */
  name: string;
  /** The video's own closing line in this language: the disclaimer the narration speaks. */
  disclaimer: string;
}

export const GUIDE_LANGS: readonly GuideLang[] = [
  {
    code: "en", label: "English", name: "English",
    disclaimer: "For education and research only. These are ideas, not recommendations, and not investment advice. Broker connections are read-only, and nothing is ever sent to a broker.",
  },
  {
    code: "hi", label: "हिंदी", name: "Hindi",
    disclaimer: "सिर्फ़ शिक्षा और रिसर्च के लिए। ये आइडिया हैं, सिफ़ारिशें नहीं, और निवेश सलाह नहीं। ब्रोकर कनेक्शन रीड-ओनली हैं, और ब्रोकर को कभी कुछ नहीं भेजा जाता।",
  },
  {
    code: "ta", label: "தமிழ்", name: "Tamil",
    disclaimer: "கல்வி மற்றும் ஆய்வுக்காக மட்டுமே. இவை யோசனைகள், பரிந்துரைகள் அல்ல, முதலீட்டு ஆலோசனை அல்ல. ப்ரோக்கர் இணைப்புகள் read-only; எதுவும் ஒருபோதும் ப்ரோக்கருக்கு அனுப்பப்படுவதில்லை.",
  },
  {
    code: "mr", label: "मराठी", name: "Marathi",
    disclaimer: "फक्त शिक्षण आणि संशोधनासाठी. या कल्पना आहेत, शिफारसी नाहीत, आणि गुंतवणूक सल्ला नाही. ब्रोकर कनेक्शन्स रीड-ओन्ली आहेत, आणि ब्रोकरला कधीच काहीही पाठवलं जात नाही.",
  },
  {
    code: "gu", label: "ગુજરાતી", name: "Gujarati",
    disclaimer: "ફક્ત શિક્ષણ અને રિસર્ચ માટે. આ આઇડિયા છે, ભલામણો નહીં, અને રોકાણ સલાહ નથી. બ્રોકર કનેક્શન્સ read-only છે, અને બ્રોકરને ક્યારેય કંઈ મોકલાતું નથી.",
  },
];

export const langOf = (code: string | null | undefined): GuideLang => GUIDE_LANGS.find((l) => l.code === code) ?? GUIDE_LANGS[0];

export const guideVideoUrl = (code: GuideLangCode) => `${GUIDE_FILES}nivesh-copilot-${code}.mp4`;
export const guideCaptionsUrl = (code: GuideLangCode) => `${GUIDE_FILES}nivesh-copilot-${code}.vtt`;
export const GUIDE_POSTER = `${GUIDE_FILES}poster.jpg`;

/** The page's own path for a language: English is the plain URL, the others carry ?lang=. */
export const guidePagePath = (code: GuideLangCode) => (code === "en" ? "/user-guide" : `/user-guide?lang=${code}`);

/** The video's chapters (start second, from the build's timeline.json). */
export const GUIDE_CHAPTERS: readonly { key: string; title: string; t: number }[] = [
  { key: "Intro", title: "Introduction", t: 0 },
  { key: "The problem", title: "The problem every market participant faces", t: 16.5 },
  { key: "Trader deep-dive", title: "Trader mode, screen by screen", t: 160.8 },
  { key: "Investors, analysts, researchers, advisors", title: "For investors, analysts, researchers and advisors", t: 871.8 },
  { key: "Close", title: "From information to decisions", t: 965.8 },
];

export interface GuideSection {
  id: string;
  /** The chapter key (GUIDE_CHAPTERS[].key). */
  chapter: string;
  /** The screen or topic, as labelled in the video (English: the app's own screen names). */
  label: string;
  /** Start second in the video (the same in every language). */
  t: number;
  /** The narration for this section, in the guide's language. */
  text: string;
  /** The app view this section shows, below /app ("" = the Copilot chat home); absent for the problem and close. */
  app?: string;
}

export interface GuideText {
  lang: GuideLangCode;
  sections: GuideSection[];
}

export function fmtTime(t: number): string {
  const s = Math.max(0, Math.floor(t));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function useGuideText(code: GuideLangCode) {
  return useQuery({
    queryKey: ["user-guide", code],
    queryFn: async (): Promise<GuideText> => {
      const r = await fetch(`${import.meta.env.BASE_URL}user-guide/${code}.json`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return (await r.json()) as GuideText;
    },
    staleTime: 60 * 60 * 1000,
    retry: 1,
  });
}
