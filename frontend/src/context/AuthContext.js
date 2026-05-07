import React, { createContext, useContext, useState, useCallback, useEffect } from "react";
import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const AuthContext = createContext(null);

export const useAuth = () => useContext(AuthContext);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [authError, setAuthError] = useState(null);
  // Seed from build-time env so the Google button renders even if the
  // /auth/google-client-id endpoint is slow, blocked, or unreachable.
  const [googleClientId, setGoogleClientId] = useState(
    process.env.REACT_APP_GOOGLE_CLIENT_ID || null
  );

  // Fetch Google Client ID from backend on mount (overrides env if it differs)
  useEffect(() => {
    let cancelled = false;
    axios.get(`${API}/auth/google-client-id`, { timeout: 8000 })
      .then(res => { if (!cancelled && res.data?.client_id) setGoogleClientId(res.data.client_id); })
      .catch(err => {
        // Visible warning so we can diagnose; we still have the env fallback
        // eslint-disable-next-line no-console
        console.warn("[auth] google-client-id fetch failed:", err?.message || err);
      });
    return () => { cancelled = true; };
  }, []);

  const checkAuth = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/auth/me`, { withCredentials: true });
      setUser(res.data);
      setAuthError(null);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    checkAuth();
  }, [checkAuth]);

  const loginWithGoogle = async (credential) => {
    try {
      setAuthError(null);
      const res = await axios.post(
        `${API}/auth/google`,
        { credential },
        { withCredentials: true }
      );
      setUser(res.data);
      return res.data;
    } catch (err) {
      const detail = err.response?.data?.detail || "Login failed";
      setAuthError(detail);
      throw new Error(detail);
    }
  };

  const logout = async () => {
    try {
      await axios.post(`${API}/auth/logout`, {}, { withCredentials: true });
    } catch {
      // ignore
    }
    setUser(null);
    setAuthError(null);
  };

  return (
    <AuthContext.Provider value={{
      user, setUser, loading, logout, checkAuth,
      loginWithGoogle, authError, setAuthError,
      googleClientId,
    }}>
      {children}
    </AuthContext.Provider>
  );
};
