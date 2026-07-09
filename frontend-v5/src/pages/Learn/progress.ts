// Nivesh Learn — per-user progress + derived stats.
// Progress is stored in the browser keyed by the signed-in account (me.id), so
// each learner keeps their own pass/fail state. Server-side persistence is the
// planned follow-up; this MVP keeps it client-side.
import { safeGet, safeSet } from "@/lib/safe-storage";
import { COURSES, type LearnCourse, type LearnLesson } from "./courses";

export interface LearnProgress {
  pass: Record<string, boolean>;
  attempt: Record<string, "pass" | "fail">;
}

const key = (uid: string) => `nivesh_learn_prog_${uid}`;

export function loadProgress(uid: string): LearnProgress {
  return safeGet<LearnProgress>(key(uid)) ?? { pass: {}, attempt: {} };
}
export function saveProgress(uid: string, p: LearnProgress): void {
  safeSet(key(uid), p);
}

/** Globally-unique lesson key: course number + lesson id. */
export const lkey = (l: LearnLesson) => `${l._c}:${l.id}`;

export function courseLessons(c: LearnCourse): LearnLesson[] {
  return c.modules.flatMap((m) => m.lessons);
}
export function lessonPassed(p: LearnProgress, l: LearnLesson): boolean {
  return !!p.pass[lkey(l)];
}
export function lessonState(p: LearnProgress, l: LearnLesson): "pass" | "fail" | "todo" {
  const k = lkey(l);
  if (p.pass[k]) return "pass";
  if (p.attempt[k] === "fail") return "fail";
  return "todo";
}
export function courseStats(p: LearnProgress, c: LearnCourse) {
  const ls = courseLessons(c);
  const done = ls.filter((l) => lessonPassed(p, l)).length;
  return { done, total: ls.length, pct: ls.length ? Math.round((done / ls.length) * 100) : 0 };
}
export function courseComplete(p: LearnProgress, c: LearnCourse): boolean {
  const s = courseStats(p, c);
  return s.total > 0 && s.done === s.total;
}
export function courseUnlocked(p: LearnProgress, i: number, freeExplore: boolean): boolean {
  if (freeExplore || i === 0) return true;
  return courseComplete(p, COURSES[i - 1]);
}
export function overall(p: LearnProgress) {
  let done = 0, total = 0;
  COURSES.forEach((c) => { const s = courseStats(p, c); done += s.done; total += s.total; });
  const cc = COURSES.filter((c) => courseComplete(p, c)).length;
  let att = 0, ok = 0;
  Object.keys(p.attempt).forEach((k) => { att++; if (p.attempt[k] === "pass") ok++; });
  return {
    done, total, pct: total ? Math.round((done / total) * 100) : 0,
    courses: cc, ncourses: COURSES.length,
    passRate: att ? Math.round((ok / att) * 100) : 0, attempts: att,
  };
}
export function nextLessonRef(p: LearnProgress, freeExplore: boolean) {
  for (let i = 0; i < COURSES.length; i++) {
    if (!courseUnlocked(p, i, freeExplore)) continue;
    const c = COURSES[i];
    for (const l of courseLessons(c)) {
      if (!lessonPassed(p, l)) return { course: c.n, lesson: l.id, ct: c.title, lt: l.t };
    }
  }
  return null;
}
