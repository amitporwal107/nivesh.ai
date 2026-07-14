/**
 * use-auth — wired to auth service.
 *
 * `useMe()` is the canonical "am I logged in?" hook. Hooks that need a user
 * call `useMe()` rather than reading from Zustand directly — the cookie is
 * the source of truth, not local storage.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { authService } from "@/services";

export function useMe() {
  return useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => authService.me(),
    retry: false,            // a 401 is data, not failure
    staleTime: 5 * 60_000,   // prevent parallel fetches from multiple mounted consumers
    // Loop-breaker: if /auth/me ever errors (contract drift, transient 5xx),
    // do NOT let newly-mounted consumers (Sidebar/Topbar/RequireAuth re-render)
    // re-fire the errored query. Without this, RequireAuth's pending-gate
    // unmount/remount churn re-triggers the fetch ~15×/s, hammering the API
    // and never recovering. Refetch-on-mount off means a failed `me` degrades
    // gracefully (children still render) instead of wedging the whole app.
    refetchOnMount: false,
  });
}

export function useGoogleSignIn() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (credential: string) => authService.googleSignIn(credential),
    onSuccess: (user) => {
      // Seed the `me` cache with the authoritative user from the login response.
      // useMe() uses retry:false + refetchOnMount:false, and the pre-login
      // /auth/me 401 stays in error state *during* any refetch — so a bare
      // invalidate lets RequireAuth read the stale error and bounce to /login
      // before the refetch lands. setQueryData clears the error synchronously.
      qc.setQueryData(["auth", "me"], user);
    },
  });
}

export function useLogout() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  return useMutation({
    mutationFn: () => authService.logout(),
    onSuccess: () => {
      qc.clear();
      // Land on the public homepage ("/" → /v5/), not the login wall. The
      // homepage is the crawlable, purpose-explaining public surface.
      navigate("/");
    },
    onError: () => {
      // Clear cache and navigate even on error — cookie may already be gone
      qc.clear();
      navigate("/");
    },
  });
}

export function useGoogleClientId() {
  return useQuery({
    queryKey: ["auth", "googleClientId"],
    queryFn: () => authService.googleClientId(),
    staleTime: Infinity,
  });
}

export function useMagicLink() {
  return useMutation({
    mutationFn: (email: string) => authService.magicLink(email),
  });
}

export function useRequestOtp() {
  return useMutation({
    mutationFn: (email: string) => authService.requestOtp(email),
  });
}

export function useVerifyOtp() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ email, code }: { email: string; code: string }) =>
      authService.verifyOtp(email, code),
    onSuccess: (user) => {
      // Seed `me` synchronously so RequireAuth doesn't read the pre-login 401
      // during a refetch and bounce back to /login — same as useGoogleSignIn.
      qc.setQueryData(["auth", "me"], user);
    },
  });
}
