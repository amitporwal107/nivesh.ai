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
    retry: false,          // a 401 is data, not failure
    staleTime: 5 * 60_000, // prevent parallel fetches from multiple mounted consumers
  });
}

export function useGoogleSignIn() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (credential: string) => authService.googleSignIn(credential),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["auth", "me"] }); },
  });
}

export function useLogout() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  return useMutation({
    mutationFn: () => authService.logout(),
    onSuccess: () => {
      qc.clear();
      navigate("/login");
    },
    onError: () => {
      // Clear cache and navigate even on error — cookie may already be gone
      qc.clear();
      navigate("/login");
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
