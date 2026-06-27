/**
 * Firebase init — ONLY used for the email/password beta login.
 *
 * Config comes from VITE_FIREBASE_* env (a Web app registered in the Firebase
 * project), baked at build time. We use only Firebase Auth — NOT Firestore: the
 * app's data still comes from the niveshcopilot.com backend. The flow is:
 *   signInWithEmailAndPassword() → getIdToken() → POST /api/auth/firebase,
 * which mints the same session cookie the Google login uses.
 */
import { initializeApp, getApps, type FirebaseApp } from "firebase/app";
import { getAuth, type Auth } from "firebase/auth";

const config = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY as string | undefined,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN as string | undefined,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID as string | undefined,
  appId: import.meta.env.VITE_FIREBASE_APP_ID as string | undefined,
};

/** True only when the build was given a Firebase web config. */
export function firebaseConfigured(): boolean {
  return Boolean(config.apiKey && config.projectId && config.appId);
}

let app: FirebaseApp | null = null;

export function firebaseAuth(): Auth {
  if (!firebaseConfigured()) {
    throw new Error("Firebase is not configured (VITE_FIREBASE_* missing for this build)");
  }
  if (!app) app = getApps()[0] ?? initializeApp(config as Record<string, string>);
  return getAuth(app);
}
