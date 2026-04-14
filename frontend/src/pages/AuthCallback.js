import React, { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import axios from "axios";
import { useAuth } from "@/context/AuthContext";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const AuthCallback = () => {
  const navigate = useNavigate();
  const { setUser } = useAuth();
  const hasProcessed = useRef(false);

  useEffect(() => {
    if (hasProcessed.current) return;
    hasProcessed.current = true;

    const hash = window.location.hash;
    const sessionId = new URLSearchParams(hash.replace("#", "?")).get("session_id");

    if (!sessionId) {
      navigate("/", { replace: true });
      return;
    }

    const exchangeSession = async () => {
      try {
        const res = await axios.post(
          `${API}/auth/session`,
          { session_id: sessionId },
          { withCredentials: true }
        );
        setUser(res.data);
        navigate("/dashboard", { replace: true, state: { user: res.data } });
      } catch (err) {
        console.error("Auth exchange failed:", err);
        navigate("/", { replace: true });
      }
    };

    exchangeSession();
  }, [navigate, setUser]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#F8FAFC]">
      <div className="flex flex-col items-center gap-4">
        <div className="w-10 h-10 border-3 border-emerald-600 border-t-transparent rounded-full animate-spin" />
        <p className="text-slate-500 font-medium" style={{ fontFamily: "'Figtree', sans-serif" }}>
          Signing you in...
        </p>
      </div>
    </div>
  );
};

export default AuthCallback;
