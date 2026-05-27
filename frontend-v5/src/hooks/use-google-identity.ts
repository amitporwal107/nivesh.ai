/**
 * useGoogleIdentity — lazy-load Google Identity Services and expose a
 * promise-based credential prompt.
 *
 * Why a custom hook (not @react-oauth/google):
 * - Zero extra dependency
 * - Plays nicely with our credential → /api/auth/google → session cookie flow
 * - Falls back gracefully when window.google isn't reachable (mock mode)
 *
 * Usage:
 *   const { ready, signIn } = useGoogleIdentity();
 *   const credential = await signIn();   // Google ID token
 *   await googleSignIn.mutateAsync(credential);
 */
import { useEffect, useRef, useState } from "react";
import { useGoogleClientId } from "./use-auth";
import { apiConfig } from "@/services/api/config";

interface GISWindow extends Window {
  google?: {
    accounts: {
      id: {
        initialize(opts: {
          client_id: string;
          callback: (resp: { credential?: string }) => void;
          auto_select?: boolean;
          ux_mode?: "popup" | "redirect";
        }): void;
        prompt(): void;
      };
    };
  };
}

const SCRIPT_URL = "https://accounts.google.com/gsi/client";

let scriptPromise: Promise<void> | null = null;

function loadScript(): Promise<void> {
  if (scriptPromise) return scriptPromise;
  scriptPromise = new Promise((resolve, reject) => {
    if ((window as GISWindow).google?.accounts?.id) return resolve();
    const tag = document.createElement("script");
    tag.src = SCRIPT_URL;
    tag.async = true;
    tag.defer = true;
    tag.onload = () => resolve();
    tag.onerror = () => reject(new Error("Failed to load Google Identity Services"));
    document.head.appendChild(tag);
  });
  return scriptPromise;
}

export interface UseGoogleIdentity {
  ready: boolean;
  loadError?: Error;
  signIn: () => Promise<string>;     // resolves with credential (ID token)
}

export function useGoogleIdentity(): UseGoogleIdentity {
  const { data: clientId, isPending: clientIdPending, error: clientIdError } = useGoogleClientId();
  const [ready, setReady] = useState(false);
  const [loadError, setLoadError] = useState<Error | undefined>();
  const callbackRef = useRef<((credential: string) => void) | null>(null);

  useEffect(() => {
    if (!clientId) return;
    // mock mode → don't touch network; declare ready and use a stub credential
    if (apiConfig.useMock) {
      setReady(true);
      return;
    }
    loadScript()
      .then(() => {
        const gis = (window as GISWindow).google?.accounts.id;
        if (!gis) throw new Error("Google Identity Services unavailable");
        gis.initialize({
          client_id: clientId,
          callback: (resp) => {
            if (resp.credential) callbackRef.current?.(resp.credential);
          },
          ux_mode: "popup",
        });
        setReady(true);
      })
      .catch((err) => setLoadError(err));
  }, [clientId]);

  const signIn = async (): Promise<string> => {
    if (apiConfig.useMock) return "mock-credential";
    return new Promise<string>((resolve) => {
      callbackRef.current = (credential) => {
        callbackRef.current = null;
        resolve(credential);
      };
      const gis = (window as GISWindow).google?.accounts.id;
      gis?.prompt();
    });
  };

  return {
    ready: ready && !clientIdPending,
    loadError: loadError ?? (clientIdError as Error | undefined),
    signIn,
  };
}
