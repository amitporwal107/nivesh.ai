/**
 * useGoogleIdentity — lazy-load Google Identity Services and expose a
 * promise-based credential flow.
 *
 * Uses google.accounts.id.renderButton() for reliable sign-in across
 * all browsers (works even when third-party cookies are blocked, unlike
 * prompt()/One Tap which silently fails).
 *
 * Usage:
 *   const { ready, signIn, renderButton } = useGoogleIdentity();
 *   // Option A: render Google's own button into a container ref
 *   renderButton(containerRef.current);
 *   // Option B: programmatic sign-in (falls back to popup)
 *   const credential = await signIn();
 */
import { useEffect, useRef, useState, useCallback } from "react";
import { useGoogleClientId } from "./use-auth";
import { apiConfig } from "@/services/api/config";

interface GISAccounts {
  id: {
    initialize(opts: {
      client_id: string;
      callback: (resp: { credential?: string }) => void;
      auto_select?: boolean;
      ux_mode?: "popup" | "redirect";
      use_fedcm_for_prompt?: boolean;
    }): void;
    prompt(cb?: (notification: { isNotDisplayed: () => boolean; isSkippedMoment: () => boolean; getNotDisplayedReason: () => string }) => void): void;
    renderButton(parent: HTMLElement, opts: {
      type?: "standard" | "icon";
      theme?: "outline" | "filled_blue" | "filled_black";
      size?: "large" | "medium" | "small";
      text?: "signin_with" | "signup_with" | "continue_with";
      shape?: "rectangular" | "pill" | "circle" | "square";
      width?: number;
    }): void;
  };
}

interface GISWindow extends Window {
  google?: { accounts: GISAccounts };
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
  signIn: () => Promise<string>;
  /** Render Google's native sign-in button into a DOM element */
  renderButton: (container: HTMLElement | null) => void;
}

export function useGoogleIdentity(onCredential?: (credential: string) => void): UseGoogleIdentity {
  const { data: clientId, isPending: clientIdPending, error: clientIdError } = useGoogleClientId();
  const [ready, setReady] = useState(false);
  const [loadError, setLoadError] = useState<Error | undefined>();
  const callbackRef = useRef<((credential: string) => void) | null>(null);
  const onCredentialRef = useRef(onCredential);
  onCredentialRef.current = onCredential;

  useEffect(() => {
    if (!clientId) return;
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
            if (resp.credential) {
              // Notify both the signIn() promise and the onCredential callback
              callbackRef.current?.(resp.credential);
              onCredentialRef.current?.(resp.credential);
            }
          },
          ux_mode: "popup",
          use_fedcm_for_prompt: true,
        });
        setReady(true);
      })
      .catch((err) => setLoadError(err));
  }, [clientId]);

  const signIn = useCallback(async (): Promise<string> => {
    if (apiConfig.useMock) return "mock-credential";
    return new Promise<string>((resolve, reject) => {
      callbackRef.current = (credential) => {
        callbackRef.current = null;
        resolve(credential);
      };
      const gis = (window as GISWindow).google?.accounts.id;
      // Try prompt first; if it fails (cookies blocked), the user can use
      // the rendered Google button as fallback.
      gis?.prompt((notification) => {
        if (notification.isNotDisplayed() || notification.isSkippedMoment()) {
          // prompt() silently failed — reject so the UI can show an error
          callbackRef.current = null;
          reject(new Error(
            "Google One Tap blocked by browser. Please use the Google button below or check popup/cookie settings."
          ));
        }
      });
    });
  }, []);

  const renderButton = useCallback((container: HTMLElement | null) => {
    if (!container || !ready) return;
    const gis = (window as GISWindow).google?.accounts.id;
    if (!gis) return;
    // Clear any previous render
    container.innerHTML = "";
    gis.renderButton(container, {
      type: "standard",
      theme: "filled_black",
      size: "large",
      text: "continue_with",
      shape: "rectangular",
      width: 400,
    });
  }, [ready]);

  return {
    ready: ready && !clientIdPending,
    loadError: loadError ?? (clientIdError as Error | undefined),
    signIn,
    renderButton,
  };
}
