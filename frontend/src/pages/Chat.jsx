import React, { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import Sidebar from "@/components/Sidebar";
import UserProfileDropdown from "@/components/UserProfileDropdown";
import ChatView from "@/components/ChatView";
import NiveshCopilotDrawer from "@/components/NiveshCopilotDrawer";
import { Sparkles } from "lucide-react";
import axios from "axios";

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

/**
 * Standalone /chat and /chat/:threadId page.
 * Mirrors the Dashboard shell (Sidebar + top bar) but renders ChatView
 * as the sole content — no tab switching. The :threadId param is passed
 * down so ChatView can pre-select the right session on mount.
 */
const Chat = () => {
  const { user } = useAuth();
  const navigate = useNavigate();
  const { threadId } = useParams();
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [workspace, setWorkspace] = useState(null);

  const fetchWorkspace = useCallback(async () => {
    try {
      const res = await axios.get(`${API}/mfd/workspace`, { withCredentials: true });
      setWorkspace(res.data);
    } catch {
      // non-advisor users — silent
    }
  }, []);

  useEffect(() => {
    if (user) fetchWorkspace();
  }, [user, fetchWorkspace]);

  // Sidebar setActiveTab for Chat page: navigate to the right dashboard hash
  const handleNav = (tab) => {
    if (tab === "chat") return; // already here
    navigate(`/dashboard#${tab}`);
  };

  return (
    <div className="min-h-screen bg-[#F8FAFC] dark:bg-slate-950 flex overflow-x-hidden">
      <Sidebar
        activeTab="chat"
        setActiveTab={handleNav}
        workspaceType={workspace?.type}
        activeProfileName={null}
        onExitProfile={() => navigate("/dashboard#advisor")}
      />

      <main className="flex-1 ml-0 md:ml-64 min-h-screen min-w-0">
        <div className="sticky top-0 z-30 flex justify-between items-center gap-3 px-4 sm:px-6 lg:px-8 py-3 bg-[#F8FAFC]/80 dark:bg-slate-950/80 backdrop-blur-sm border-b border-slate-100 dark:border-slate-800">
          <div />
          <UserProfileDropdown user={user} activeTab="chat" setActiveTab={handleNav} />
        </div>

        <div className="p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto">
          <ChatView
            initialSessionId={threadId}
            onNavigateToPlanBoard={() => navigate("/dashboard#plan_board")}
          />
        </div>
      </main>

      {!copilotOpen && (
        <button
          onClick={() => setCopilotOpen(true)}
          aria-label="Open Nivesh Copilot"
          className="fixed bottom-6 right-6 z-40 flex items-center gap-2 pl-4 pr-5 py-3 rounded-full bg-gradient-to-r from-emerald-600 to-emerald-700 hover:from-emerald-700 hover:to-emerald-800 text-white shadow-lg hover:shadow-xl transition-all hover:-translate-y-0.5"
        >
          <Sparkles className="w-5 h-5" />
          <span className="text-sm font-semibold tracking-wide hidden sm:inline">Nivesh Copilot</span>
        </button>
      )}
      <NiveshCopilotDrawer
        open={copilotOpen}
        onClose={() => setCopilotOpen(false)}
        onNavigateToPlanBoard={() => { setCopilotOpen(false); navigate("/dashboard#plan_board"); }}
      />
    </div>
  );
};

export default Chat;
