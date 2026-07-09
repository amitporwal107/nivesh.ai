// Nivesh Learn — Learning Centre.
// A route behind RequireAuth (forces sign-up/login), so the learner is the real
// Nivesh account from useMe(); progress is stored per account. Views: home
// dashboard -> course -> lesson (Core / personalized Hook / pass-to-progress Quiz).
// Content + logic ported from the verified prototype; styled with app tokens.
import { useEffect, useMemo, useState } from "react";
import { GraduationCap, ArrowRight, RotateCcw, Check, X, Lock, ChevronRight, Volume2, Square } from "lucide-react";
import { useMe } from "@/hooks/use-auth";
import { safeGet, safeSet } from "@/lib/safe-storage";
import { cn } from "@/lib/utils";
import { COURSES, DEMO, type LearnCourse, type LearnLesson } from "./courses";
import { HINDI } from "./hindi";
import {
  type LearnProgress, loadProgress, saveProgress, lkey, courseLessons,
  lessonState, courseStats, courseComplete, courseUnlocked, overall, nextLessonRef,
} from "./progress";

// Stamp the owning course number onto each lesson once (used for the progress key).
COURSES.forEach((c) => c.modules.forEach((m) => m.lessons.forEach((l) => { l._c = c.n; })));

type View = { v: "home" | "course" | "lesson"; c?: number; l?: string };

/* ---- small presentational pieces ---- */
function Ring({ pct, size = 44, big = false }: { pct: number; size?: number; big?: boolean }) {
  return (
    <div
      className="relative grid place-items-center rounded-full shrink-0"
      style={{ width: size, height: size, background: `conic-gradient(rgb(var(--accent)) ${pct * 3.6}deg, rgb(var(--line)/0.12) 0)` }}
      role="img" aria-label={`${pct}% complete`}
    >
      <div className="absolute inset-[5px] rounded-full bg-surface-1 grid place-items-center leading-none">
        <span className="text-center">
          <b className={cn("tabular-nums font-bold", big ? "text-[26px]" : "text-[15px]")}>{pct}</b>
          {big && <small className="block text-[10px] text-ink-3 font-mono uppercase tracking-[.1em] mt-0.5">complete</small>}
        </span>
      </div>
    </div>
  );
}

const PILL: Record<string, string> = {
  pass: "text-pos bg-accent/10 border-pos/30",
  fail: "text-neg bg-neg/10 border-neg/30",
  prog: "text-warm bg-warm/10 border-warm/30",
  lock: "text-ink-3 bg-surface-2 border-hairline",
  start: "text-accent bg-accent/10 border-accent/30",
};
function Pill({ tone, children }: { tone: keyof typeof PILL; children: React.ReactNode }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 font-mono text-[10.5px] uppercase tracking-[.08em] px-2 py-1 rounded-full border whitespace-nowrap", PILL[tone])}>
      {children}
    </span>
  );
}

function Bar({ pct }: { pct: number }) {
  return (
    <div className="h-1.5 rounded-full overflow-hidden bg-[rgb(var(--line)/0.09)]">
      <i className="block h-full rounded-full bg-accent transition-[width] duration-500" style={{ width: `${pct}%` }} />
    </div>
  );
}

/** Render a Hook line, filling {tokens} from DEMO (mint chip) or marking them personalized (dashed chip). */
function Hook({ text }: { text: string }) {
  const nodes: React.ReactNode[] = [];
  const re = /\{(\w+)\}/g;
  let last = 0, m: RegExpExecArray | null, i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    const k = m[1];
    const v = DEMO[k];
    nodes.push(
      v != null ? (
        <span key={i++} className="font-semibold rounded px-1.5 py-0.5 text-accent bg-accent/10 ring-1 ring-accent/25 tabular-nums whitespace-nowrap">{v}</span>
      ) : (
        <span key={i++} title="Personalized from your portfolio in-app" className="italic rounded px-1.5 py-0.5 text-ink-3 border border-dashed border-hairline-2 whitespace-nowrap">{k.replace(/_/g, " ")}</span>
      )
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return <>{nodes}</>;
}

const card = "rounded-md bg-surface-1 border border-hairline";

export default function LearnPage() {
  const { data: me } = useMe();
  const uid = String(me?.id ?? me?.email ?? "anon");

  const [prog, setProg] = useState<LearnProgress>(() => loadProgress(uid));
  const [freeExplore, setFreeExplore] = useState<boolean>(() => safeGet<boolean>("nivesh_learn_explore") ?? false);
  const [view, setView] = useState<View>({ v: "home" });
  const [sel, setSel] = useState<number | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const [lang, setLang] = useState<"en" | "hi">(() => safeGet<"en" | "hi">("nivesh_learn_lang") ?? "en");
  const [speaking, setSpeaking] = useState(false);

  const persist = (p: LearnProgress) => { setProg(p); saveProgress(uid, p); };
  const toExplore = (on: boolean) => { setFreeExplore(on); safeSet("nivesh_learn_explore", on); };

  // Narration via the browser Speech API (no external dependency). hi-IN / en-IN
  // voice availability varies by device; when absent the button is simply a no-op.
  const stopSpeak = () => { if (typeof window !== "undefined" && window.speechSynthesis) window.speechSynthesis.cancel(); setSpeaking(false); };
  const speak = (text: string, l: "en" | "hi") => {
    if (typeof window === "undefined" || !window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim());
    u.lang = l === "hi" ? "hi-IN" : "en-IN";
    u.rate = 0.98;
    u.onend = () => setSpeaking(false);
    u.onerror = () => setSpeaking(false);
    setSpeaking(true);
    window.speechSynthesis.speak(u);
  };
  const setLanguage = (l: "en" | "hi") => { setLang(l); safeSet("nivesh_learn_lang", l); stopSpeak(); };

  const goHome = () => { stopSpeak(); setView({ v: "home" }); };
  const goCourse = (n: number) => { stopSpeak(); setView({ v: "course", c: n }); };
  const goLesson = (n: number, id: string) => { stopSpeak(); setSel(null); setSubmitted(false); setView({ v: "lesson", c: n, l: id }); };
  useEffect(() => () => { if (typeof window !== "undefined" && window.speechSynthesis) window.speechSynthesis.cancel(); }, []);

  const o = useMemo(() => overall(prog), [prog]);
  const nx = useMemo(() => nextLessonRef(prog, freeExplore), [prog, freeExplore]);

  const firstName = (me?.name ?? "there").split(/\s+/)[0];

  /* ---------------- HOME ---------------- */
  function Home() {
    return (
      <div className="animate-[fadeIn_.35s_ease]">
        <div className="mb-5">
          <div className="font-mono text-[10px] uppercase tracking-[.18em] text-ink-3">Nivesh Learn · Learning Centre</div>
          <h1 className="font-display text-[34px] tracking-tightish leading-[1.05] mt-1">Welcome back, {firstName}.</h1>
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-[auto_1fr_1fr_1fr] gap-3.5">
          <div className={cn(card, "flex items-center gap-4 p-4 col-span-2 lg:col-span-1")}>
            <Ring pct={o.pct} size={68} big />
            <div>
              <div className="font-mono text-[11px] uppercase tracking-[.06em] text-ink-3">Overall</div>
              <div className="text-[13px] text-ink-2 max-w-[16ch]">{o.pct === 100 ? "Every course passed. Respect." : "Keep going — one lesson at a time."}</div>
            </div>
          </div>
          {([["Lessons passed", `${o.done}`, `/ ${o.total}`], ["Courses complete", `${o.courses}`, `/ ${o.ncourses}`], ["Quiz pass rate", o.attempts ? `${o.passRate}%` : "—", ""]] as const).map(([k, v, sub]) => (
            <div key={k} data-testid={"stat-" + k.toLowerCase().replace(/\s+/g, "-")} className={cn(card, "p-4 flex flex-col justify-center gap-0.5")}>
              <span className="font-mono text-[11px] uppercase tracking-[.06em] text-ink-3">{k}</span>
              <span className="text-[26px] font-bold tabular-nums tracking-tightish">{v} {sub && <small className="text-[14px] text-ink-3 font-semibold">{sub}</small>}</span>
            </div>
          ))}
        </div>

        {nx ? (
          <div className={cn(card, "p-4 mt-4 flex gap-4 items-center flex-wrap")}>
            <div className="flex-1 min-w-[200px]">
              <div className="font-mono text-[10px] uppercase tracking-[.18em] text-ink-3">Continue where you left off</div>
              <div className="font-display text-[20px] mt-1">{nx.lt}</div>
              <div className="text-[13px] text-ink-3">{nx.ct} · Lesson {nx.lesson}</div>
            </div>
            <button onClick={() => goLesson(nx.course, nx.lesson)} className="inline-flex items-center gap-2 rounded-md bg-accent text-on-accent px-4 py-2.5 text-[14px] font-semibold hover:opacity-90">Resume <ArrowRight className="h-4 w-4" /></button>
          </div>
        ) : (
          <div className={cn(card, "p-4 mt-4")}><b>🎉 You've passed every unlocked lesson.</b> {freeExplore ? "" : "New courses unlock as you complete the track."}</div>
        )}

        <SectionHead title="Your learning path" right={<ExploreSwitch />} />
        <div className="flex gap-2.5 overflow-x-auto pb-3 pt-1">
          {COURSES.map((c, i) => {
            const st = courseStats(prog, c); const done = courseComplete(prog, c); const active = nx?.course === c.n;
            return (
              <button key={c.n} onClick={() => goCourse(c.n)} className={cn("shrink-0 w-[150px] p-3 rounded-xl border bg-surface-1 flex flex-col gap-2 text-left", done ? "border-pos/40" : active ? "border-accent ring-[3px] ring-accent/15" : "border-hairline")}>
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[11px] text-ink-3">STEP {i + 1}</span>
                  {done ? <Pill tone="pass"><Check className="h-3 w-3" />Pass</Pill> : courseUnlocked(prog, i, freeExplore) ? null : <Lock className="h-3.5 w-3.5 text-ink-3" />}
                </div>
                <h4 className="text-[13px] leading-[1.25] font-medium">{c.title}</h4>
                <Bar pct={st.pct} />
              </button>
            );
          })}
        </div>

        <SectionHead title="All courses" />
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {COURSES.map((c, i) => <CourseCard key={c.n} c={c} i={i} />)}
        </div>
      </div>
    );
  }

  function ExploreSwitch() {
    return (
      <button data-testid="explore-switch" role="switch" aria-checked={freeExplore} onClick={() => toExplore(!freeExplore)} className="inline-flex items-center gap-2 text-[13px] text-ink-2">
        <span>Explore all</span>
        <span className={cn("relative w-[38px] h-[22px] rounded-full transition-colors", freeExplore ? "bg-accent" : "bg-[rgb(var(--line)/0.14)]")}>
          <span className={cn("absolute top-0.5 left-0.5 w-[18px] h-[18px] rounded-full bg-surface-1 shadow transition-transform", freeExplore && "translate-x-4")} />
        </span>
      </button>
    );
  }

  function CourseCard({ c, i }: { c: LearnCourse; i: number }) {
    const st = courseStats(prog, c); const unlocked = courseUnlocked(prog, i, freeExplore); const done = courseComplete(prog, c);
    const pill = done ? <Pill tone="pass"><Check className="h-3 w-3" />Passed</Pill>
      : !unlocked ? <Pill tone="lock"><Lock className="h-3 w-3" />Locked</Pill>
      : st.done > 0 ? <Pill tone="prog">{st.done}/{st.total}</Pill>
      : <Pill tone="start">Start</Pill>;
    return (
      <div data-testid={`course-${c.n}`} data-locked={!unlocked} className={cn(card, "relative p-[18px] flex flex-col gap-3", !unlocked && "opacity-70", unlocked && "hover:-translate-y-0.5 transition-transform")}>
        <div className="flex items-start gap-3">
          <span className={cn("shrink-0 w-[34px] h-[34px] rounded-[10px] grid place-items-center font-mono text-[13px] font-semibold", unlocked ? "bg-accent/10 text-accent" : "bg-surface-2 text-ink-3")}>{i + 1}</span>
          <div className="flex-1">
            <h3 className="text-[17px] leading-[1.2] tracking-tightish font-semibold">{c.title}</h3>
            <div className="text-[12.5px] text-ink-3 mt-0.5 tabular-nums">{c.level} · {courseLessons(c).length} lessons · ~{c.min} min</div>
          </div>
          {pill}
        </div>
        <p className="text-[13.5px] text-ink-2 leading-[1.45]">{c.promise}</p>
        <Bar pct={st.pct} />
        <div className="flex items-center justify-between gap-2.5 mt-auto pt-1">
          <span className="text-[12px] text-ink-3">Prereq: {c.prereq}</span>
          {unlocked ? (
            <button data-testid={`course-cta-${c.n}`} onClick={() => goCourse(c.n)} className="after:absolute after:inset-0 after:rounded-md inline-flex items-center gap-1.5 rounded-md border border-hairline-2 px-3 py-1.5 text-[13px] font-semibold hover:bg-surface-2">{st.done > 0 ? "Continue" : "Start"} <ArrowRight className="h-3.5 w-3.5" /></button>
          ) : (
            <span className="text-[12px] text-ink-3">Finish step {i}</span>
          )}
        </div>
      </div>
    );
  }

  /* ---------------- COURSE ---------------- */
  function CourseView({ n }: { n: number }) {
    const c = COURSES.find((x) => x.n === n)!;
    const i = COURSES.findIndex((x) => x.n === n);
    const unlocked = courseUnlocked(prog, i, freeExplore);
    const st = courseStats(prog, c);
    return (
      <div className="animate-[fadeIn_.35s_ease]">
        <Crumb items={[{ label: "Learning Centre", onClick: goHome }, { label: c.title }]} />
        <div className="flex gap-[18px] items-start flex-wrap">
          <span className="shrink-0 w-[44px] h-[44px] rounded-[10px] grid place-items-center font-mono text-[16px] font-semibold bg-accent/10 text-accent">{i + 1}</span>
          <div className="flex-1 min-w-[220px]">
            <div className="font-mono text-[10px] uppercase tracking-[.18em] text-ink-3">Course {i + 1} · {c.level}</div>
            <h1 className="font-display text-[clamp(26px,4vw,36px)] tracking-tightish leading-[1.05]">{c.title}</h1>
            <p className="text-[15px] text-ink-2 max-w-[60ch] mt-2">{c.promise}</p>
            <div className="flex gap-3.5 items-center flex-wrap mt-3">
              <span className="text-[13px] text-ink-3">{courseLessons(c).length} lessons · ~{c.min} min · Prereq: {c.prereq}</span>
              {courseComplete(prog, c) ? <Pill tone="pass"><Check className="h-3 w-3" />Course passed</Pill> : <Pill tone="prog">{st.done} / {st.total} passed</Pill>}
            </div>
            <div className="mt-3 max-w-[320px]"><Bar pct={st.pct} /></div>
          </div>
        </div>

        {!unlocked && (
          <div className="flex items-center gap-2.5 mt-3.5 px-4 py-3 rounded-md bg-warm/10 text-warm text-[13.5px] font-medium">
            <Lock className="h-4 w-4 shrink-0" /> Complete <b className="mx-1">{COURSES[i - 1].title}</b> to unlock — or turn on <b className="mx-1">Explore all</b> on the home screen.
          </div>
        )}

        {c.modules.map((mod, mi) => (
          <div key={mi} className="mt-6">
            {c.modules.length > 1 && <div className="font-mono text-[11px] uppercase tracking-[.12em] text-ink-3 mb-2 px-0.5">{mod.title}</div>}
            <div className="flex flex-col rounded-md overflow-hidden border border-hairline">
              {mod.lessons.map((l, li) => {
                const s = lessonState(prog, l);
                return (
                  <button key={l.id} data-testid={`lesson-${c.n}-${l.id}`} disabled={!unlocked} onClick={() => unlocked && goLesson(c.n, l.id)}
                    className={cn("flex items-center gap-3.5 px-4 py-3.5 bg-surface-1 text-left border-hairline w-full", li > 0 && "border-t", !unlocked ? "opacity-55 cursor-default" : "hover:bg-surface-2")}>
                    <span className={cn("shrink-0 w-[26px] h-[26px] rounded-full grid place-items-center text-[13px] border", s === "pass" ? "bg-accent/10 border-transparent text-pos" : s === "fail" ? "bg-neg/10 border-transparent text-neg" : "border-hairline-2 text-ink-3")}>
                      {s === "pass" ? <Check className="h-3.5 w-3.5" /> : s === "fail" ? "!" : ""}
                    </span>
                    <span className="flex-1 min-w-0"><b className="text-[14.5px] font-semibold"><span className="font-mono text-[11px] text-ink-4 mr-2">{l.id}</span>{l.t}</b></span>
                    {s === "pass" && <Pill tone="pass"><Check className="h-3 w-3" />Passed</Pill>}
                    {s === "fail" && <Pill tone="fail">Retry</Pill>}
                    <span className="text-[12px] text-ink-3 tabular-nums shrink-0">{l.min} min</span>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    );
  }

  /* ---------------- LESSON ---------------- */
  function LessonView({ n, id }: { n: number; id: string }) {
    const c = COURSES.find((x) => x.n === n)!;
    let l: LearnLesson | undefined;
    c.modules.forEach((m) => m.lessons.forEach((x) => { if (x.id === id) l = x; }));
    if (!l) return <CourseView n={n} />;
    const lesson = l;
    const flat = courseLessons(c);
    const idx = flat.findIndex((x) => x.id === id);
    const prev = idx > 0 ? flat[idx - 1] : null;
    const next = idx < flat.length - 1 ? flat[idx + 1] : null;
    const s = lessonState(prog, lesson);
    const passed = s === "pass";
    const showResult = passed || submitted;
    const ok = passed || sel === lesson.q.a;
    const hi = HINDI[lkey(lesson)];
    const useHi = lang === "hi" && !!hi;
    const title = lang === "hi" && hi ? hi.t : lesson.t;
    const transcript = lang === "hi" && hi ? hi.core : lesson.core;

    const submit = () => {
      if (sel == null) return;
      const p: LearnProgress = { pass: { ...prog.pass }, attempt: { ...prog.attempt } };
      const correct = sel === lesson.q.a;
      p.attempt[lkey(lesson)] = correct ? "pass" : "fail";
      if (correct) p.pass[lkey(lesson)] = true;
      persist(p); setSubmitted(true);
    };

    return (
      <div className="animate-[fadeIn_.35s_ease] max-w-[720px]">
        <Crumb items={[{ label: "Learning Centre", onClick: goHome }, { label: c.title, onClick: () => goCourse(c.n) }, { label: `Lesson ${lesson.id}` }]} />
        <div className="font-mono text-[10px] uppercase tracking-[.18em] text-ink-3">Lesson {lesson.id} · {c.title}</div>
        <h1 className="font-display text-[clamp(26px,4vw,34px)] tracking-tightish leading-[1.08] mt-1.5" lang={useHi ? "hi" : "en"}>{title}</h1>
        <div className="flex gap-3 items-center mt-2.5 text-[13px] text-ink-3">
          <span>~{lesson.min} min read</span><span>·</span>
          {passed ? <Pill tone="pass"><Check className="h-3 w-3" />Passed</Pill> : s === "fail" ? <Pill tone="fail">Not passed</Pill> : <Pill tone="prog">In progress</Pill>}
        </div>

        <Block tag="Core" tone="core" hint={lang === "hi" ? "पाठ · transcript" : "the transcript this lesson teaches"}>
          <div className="flex items-center gap-2 mb-3 flex-wrap">
            <div className="inline-flex rounded-md border border-hairline-2 overflow-hidden text-[12.5px] font-semibold" role="group" aria-label="Transcript language">
              {(["en", "hi"] as const).map((lc) => (
                <button key={lc} data-testid={`lang-${lc}`} aria-pressed={lang === lc} onClick={() => setLanguage(lc)}
                  className={cn("px-3 py-1.5", lang === lc ? "bg-accent text-on-accent" : "bg-surface-1 text-ink-2 hover:bg-surface-2")}>
                  {lc === "en" ? "English" : "हिन्दी"}
                </button>
              ))}
            </div>
            <button data-testid="listen" onClick={() => (speaking ? stopSpeak() : speak(transcript, useHi ? "hi" : "en"))}
              className="inline-flex items-center gap-1.5 rounded-md border border-hairline-2 px-3 py-1.5 text-[12.5px] font-semibold hover:bg-surface-2" aria-pressed={speaking}>
              {speaking ? <><Square className="h-3.5 w-3.5" /> {lang === "hi" ? "रोकें" : "Stop"}</> : <><Volume2 className="h-3.5 w-3.5" /> {lang === "hi" ? "सुनें" : "Listen"}</>}
            </button>
            {useHi && <span className="font-mono text-[10px] uppercase tracking-[.1em] px-2 py-1 rounded-full bg-warm/10 text-warm border border-warm/30" title="Auto-translated — pending human review">ऑटो-अनुवाद · beta</span>}
            {lang === "hi" && !hi && <span className="text-[12px] text-ink-3">हिन्दी अनुवाद जल्द आ रहा है — फ़िलहाल English दिखाया गया है।</span>}
          </div>
          <div data-testid="transcript" lang={useHi ? "hi" : "en"} className="text-[16.5px] leading-[1.68] max-w-[65ch] [&_b]:font-semibold" dangerouslySetInnerHTML={{ __html: transcript }} />
        </Block>

        {lesson.hook && (
          <Block tag="Hook" tone="hook" hint="personalized from your portfolio">
            <div className="p-[18px] rounded-md border border-accent/25 bg-gradient-to-b from-accent/10 to-transparent">
              <p className="text-[16px] leading-[1.7]"><Hook text={lesson.hook} /></p>
              <div className="flex items-center gap-1.5 mt-3 text-[12px] text-ink-3">◆ Sample data shown — in the app these fields come from your real holdings.</div>
            </div>
          </Block>
        )}

        <Block tag="Quiz" tone="quiz" hint="pass to complete the lesson">
          <div className={cn(card, "p-5")}>
            <div className="text-[16.5px] font-semibold leading-[1.4] mb-3.5">{lesson.q.q}</div>
            <div className="flex flex-col gap-2.5">
              {lesson.q.opts.map((opt, k) => {
                const state = showResult ? (k === lesson.q.a ? "correct" : k === sel ? "wrong" : "idle") : k === sel ? "sel" : "idle";
                return (
                  <button key={k} data-testid={`opt-${k}`} disabled={showResult} onClick={() => !showResult && setSel(k)}
                    className={cn("flex items-center gap-3 px-4 py-3.5 rounded-md border text-left text-[14.5px]",
                      state === "correct" && "border-pos bg-accent/10", state === "wrong" && "border-neg bg-neg/10",
                      state === "sel" && "border-accent bg-accent/10", state === "idle" && "border-hairline-2 hover:border-[rgb(var(--line)/0.3)]")}>
                    <span className={cn("shrink-0 w-[22px] h-[22px] rounded-full grid place-items-center text-[11px] font-mono border",
                      state === "correct" ? "bg-pos border-pos text-on-accent" : state === "wrong" ? "bg-neg border-neg text-white" : state === "sel" ? "bg-accent border-accent text-on-accent" : "border-hairline-2 text-ink-3")}>
                      {state === "correct" ? <Check className="h-3 w-3" /> : state === "wrong" ? <X className="h-3 w-3" /> : String.fromCharCode(65 + k)}
                    </span>
                    <span>{opt}</span>
                  </button>
                );
              })}
            </div>

            {showResult && (
              <div data-testid="quiz-result" data-ok={ok} className={cn("mt-4 p-3.5 rounded-md border flex gap-3 items-start text-[14.5px] leading-[1.55]", ok ? "bg-accent/10 border-pos/30" : "bg-neg/10 border-neg/30")} role="status">
                <span className="text-[18px] leading-[1.3]">{ok ? <Check className="h-4 w-4 text-pos" /> : <X className="h-4 w-4 text-neg" />}</span>
                <div><b className="block mb-0.5">{ok ? "Passed — nicely done." : "Not passed yet."}</b>{lesson.q.exp}</div>
              </div>
            )}

            <div className="flex gap-2.5 mt-4 flex-wrap">
              {passed ? (
                <>
                  <Pill tone="pass"><Check className="h-3 w-3" />Lesson passed</Pill>
                  {next ? <button data-testid="next-lesson" onClick={() => goLesson(c.n, next.id)} className="inline-flex items-center gap-1.5 rounded-md bg-accent text-on-accent px-3.5 py-2 text-[13px] font-semibold hover:opacity-90">Next lesson <ArrowRight className="h-3.5 w-3.5" /></button>
                    : <button onClick={() => goCourse(c.n)} className="inline-flex items-center gap-1.5 rounded-md bg-accent text-on-accent px-3.5 py-2 text-[13px] font-semibold hover:opacity-90">Back to course <ArrowRight className="h-3.5 w-3.5" /></button>}
                </>
              ) : submitted ? (
                <button onClick={() => { setSubmitted(false); setSel(null); }} className="inline-flex items-center gap-1.5 rounded-md border border-hairline-2 px-3.5 py-2 text-[13px] font-semibold hover:bg-surface-2"><RotateCcw className="h-3.5 w-3.5" />Try again</button>
              ) : (
                <>
                  <button data-testid="quiz-submit" onClick={submit} disabled={sel == null} className="inline-flex items-center gap-1.5 rounded-md bg-accent text-on-accent px-4 py-2 text-[14px] font-semibold hover:opacity-90 disabled:opacity-50">Submit answer</button>
                  <span className="text-[12.5px] text-ink-3 self-center">Answer correctly to pass the lesson.</span>
                </>
              )}
            </div>
          </div>
        </Block>

        <div className="flex justify-between gap-3 mt-8 pt-5 border-t border-hairline">
          {prev ? <button onClick={() => goLesson(c.n, prev.id)} className="inline-flex items-center gap-1.5 rounded-md border border-hairline-2 px-3 py-1.5 text-[13px] font-semibold hover:bg-surface-2">← {prev.id}</button> : <span />}
          {next ? <button onClick={() => goLesson(c.n, next.id)} className="inline-flex items-center gap-1.5 rounded-md border border-hairline-2 px-3 py-1.5 text-[13px] font-semibold hover:bg-surface-2">{next.id} →</button>
            : <button onClick={() => goCourse(c.n)} className="inline-flex items-center gap-1.5 rounded-md border border-hairline-2 px-3 py-1.5 text-[13px] font-semibold hover:bg-surface-2">Finish course →</button>}
        </div>

        <div className="mt-10 px-4 py-3.5 rounded-md bg-[rgb(var(--line)/0.04)] text-ink-3 text-[12.5px] leading-[1.5]">
          Education, not investment advice. Examples use sample data to illustrate how the lesson applies to a portfolio.
        </div>
      </div>
    );
  }

  return (
    <div className="px-6 py-8 lg:px-10 lg:py-10 max-w-[1100px] mx-auto w-full">
      {view.v === "home" && <Home />}
      {view.v === "course" && view.c != null && <CourseView n={view.c} />}
      {view.v === "lesson" && view.c != null && view.l != null && <LessonView n={view.c} id={view.l} />}
    </div>
  );
}

/* ---- shared bits used across views ---- */
function SectionHead({ title, right }: { title: string; right?: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-3.5 mt-[34px] mb-3.5 flex-wrap">
      <h2 className="font-display text-[24px] tracking-tightish">{title}</h2>
      {right && <div className="ml-auto flex items-center gap-2.5">{right}</div>}
    </div>
  );
}
function Crumb({ items }: { items: { label: string; onClick?: () => void }[] }) {
  return (
    <div className="flex items-center gap-2 text-[13px] text-ink-3 mb-3.5 flex-wrap">
      {items.map((it, i) => (
        <span key={i} className="flex items-center gap-2">
          {it.onClick ? <button onClick={it.onClick} className="text-ink-2 font-semibold hover:text-accent">{it.label}</button> : <span>{it.label}</span>}
          {i < items.length - 1 && <ChevronRight className="h-3.5 w-3.5" />}
        </span>
      ))}
    </div>
  );
}
const TAG: Record<string, string> = {
  core: "bg-[rgb(var(--line)/0.07)] text-ink-2",
  hook: "bg-accent/10 text-accent",
  quiz: "bg-accent/10 text-accent",
};
function Block({ tag, tone, hint, children }: { tag: string; tone: keyof typeof TAG; hint: string; children: React.ReactNode }) {
  return (
    <div className="mt-6">
      <div className="flex items-center gap-2.5 mb-3">
        <span className={cn("font-mono text-[10.5px] uppercase tracking-[.12em] px-2 py-1 rounded-full font-medium", TAG[tone])}>{tag}</span>
        <span className="text-[12px] text-ink-3">{hint}</span>
      </div>
      {children}
    </div>
  );
}
