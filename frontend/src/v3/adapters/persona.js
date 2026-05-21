import { useEffect, useState } from "react";
import { PERSONAS, getPersona } from "./personas";

// localStorage key — read by the persona switcher and onboarding.
const STORAGE_KEY = "v3.persona";

function readStored() {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function writeStored(id) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, id);
  } catch {
    /* ignore */
  }
}

export function usePersona() {
  const [id, setId] = useState(() => readStored() || "mf_focused");
  const persona = getPersona(id);

  useEffect(() => {
    if (id) writeStored(id);
  }, [id]);

  // Listen for storage from other tabs.
  useEffect(() => {
    function onStorage(e) {
      if (e.key === STORAGE_KEY && e.newValue) setId(e.newValue);
    }
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  return { persona, personaId: id, setPersona: setId, options: PERSONAS };
}
