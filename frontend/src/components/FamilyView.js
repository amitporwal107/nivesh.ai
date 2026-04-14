import React, { useState, useEffect } from "react";
import axios from "axios";
import { Users, Plus, Trash2, Upload, TrendingUp, TrendingDown, PieChart } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { motion } from "framer-motion";
import { toast } from "sonner";
import { PieChart as RPieChart, Pie, Cell, ResponsiveContainer, Tooltip, BarChart, Bar, XAxis, YAxis, CartesianGrid } from "recharts";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;
const COLORS = ["#059669", "#3B82F6", "#F59E0B", "#8B5CF6", "#EF4444", "#EC4899", "#14B8A6", "#F97316"];
const RELATIONSHIPS = ["Self", "Spouse", "Child", "Parent", "Sibling", "Other"];

const fmt = (val) => {
  if (Math.abs(val) >= 10000000) return `₹${(val / 10000000).toFixed(2)} Cr`;
  if (Math.abs(val) >= 100000) return `₹${(val / 100000).toFixed(2)} L`;
  if (Math.abs(val) >= 1000) return `₹${(val / 1000).toFixed(1)}K`;
  return `₹${val.toFixed(0)}`;
};

const FamilyView = ({ onRefresh }) => {
  const [portfolios, setPortfolios] = useState([]);
  const [familyAnalytics, setFamilyAnalytics] = useState(null);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [newPortfolio, setNewPortfolio] = useState({ name: "", member_name: "", relationship: "Self" });
  const [loading, setLoading] = useState(true);

  useEffect(() => { fetchAll(); }, []);

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [pfRes, anRes] = await Promise.all([
        axios.get(`${API}/portfolios`, { withCredentials: true }),
        axios.get(`${API}/portfolio/analytics`, { withCredentials: true }),
      ]);
      setPortfolios(pfRes.data);
      setFamilyAnalytics(anRes.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleCreate = async (e) => {
    e.preventDefault();
    try {
      await axios.post(`${API}/portfolios`, newPortfolio, { withCredentials: true });
      toast.success("Portfolio created");
      setShowCreateDialog(false);
      setNewPortfolio({ name: "", member_name: "", relationship: "Self" });
      fetchAll();
      onRefresh();
    } catch {
      toast.error("Failed to create portfolio");
    }
  };

  const handleDelete = async (id, name) => {
    if (!window.confirm(`Delete "${name}" and all its holdings?`)) return;
    try {
      await axios.delete(`${API}/portfolios/${id}`, { withCredentials: true });
      toast.success("Portfolio deleted");
      fetchAll();
      onRefresh();
    } catch {
      toast.error("Failed to delete");
    }
  };

  const rPos = familyAnalytics ? familyAnalytics.total_returns >= 0 : true;

  return (
    <div data-testid="family-view">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl sm:text-3xl font-medium tracking-tight text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>
            Family Portfolios
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">{portfolios.length} member{portfolios.length !== 1 ? "s" : ""}</p>
        </div>
        <Button data-testid="create-portfolio-button" onClick={() => setShowCreateDialog(true)} className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl">
          <Plus className="w-4 h-4 mr-2" /> Add Member
        </Button>
      </div>

      {/* Family Summary */}
      {familyAnalytics && familyAnalytics.holdings_count > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
          {[
            { label: "Family Invested", value: fmt(familyAnalytics.total_invested) },
            { label: "Family Value", value: fmt(familyAnalytics.current_value) },
            { label: "Family Returns", value: `${rPos ? "+" : ""}${fmt(Math.abs(familyAnalytics.total_returns))}`, color: rPos ? "text-emerald-600" : "text-red-500", sub: `${rPos ? "+" : ""}${familyAnalytics.returns_pct.toFixed(1)}%` },
            { label: "Total Holdings", value: `${familyAnalytics.holdings_count}` },
          ].map((kpi, i) => (
            <motion.div key={kpi.label} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.05 }}>
              <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl shadow-none">
                <CardContent className="p-5">
                  <p className="text-[10px] font-bold tracking-[0.15em] uppercase text-slate-400 mb-2">{kpi.label}</p>
                  <p className={`text-xl font-semibold ${kpi.color || "text-slate-900 dark:text-white"}`} style={{ fontFamily: "'Outfit', sans-serif" }}>{kpi.value}</p>
                  {kpi.sub && <p className={`text-xs ${kpi.color || "text-slate-500"}`}>{kpi.sub}</p>}
                </CardContent>
              </Card>
            </motion.div>
          ))}
        </div>
      )}

      {/* Portfolio Cards */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {[1, 2].map(i => <div key={i} className="bg-white dark:bg-slate-800 rounded-2xl border border-slate-100 dark:border-slate-700 h-48 animate-pulse" />)}
        </div>
      ) : portfolios.length === 0 ? (
        <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl shadow-none">
          <CardContent className="p-12 text-center">
            <Users className="w-12 h-12 text-slate-300 dark:text-slate-600 mx-auto mb-4" strokeWidth={1.5} />
            <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>No portfolios yet</h3>
            <p className="text-sm text-slate-500 dark:text-slate-400 mb-6">Create portfolios for family members and upload their CAS statements.</p>
            <Button onClick={() => setShowCreateDialog(true)} className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl">
              <Plus className="w-4 h-4 mr-2" /> Create First Portfolio
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {portfolios.map((pf, i) => (
            <motion.div key={pf.portfolio_id} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: i * 0.06 }}>
              <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl shadow-none hover:shadow-lg hover:border-slate-200 dark:hover:border-slate-600 transition-all duration-300">
                <CardContent className="p-6">
                  <div className="flex items-start justify-between mb-4">
                    <div>
                      <h3 className="text-base font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>{pf.name}</h3>
                      <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{pf.member_name} &middot; {pf.relationship}</p>
                    </div>
                    <button data-testid={`delete-portfolio-${pf.portfolio_id}`} onClick={() => handleDelete(pf.portfolio_id, pf.name)} className="p-1.5 rounded-lg hover:bg-red-50 dark:hover:bg-red-900/20 text-slate-400 hover:text-red-500 transition-colors">
                      <Trash2 className="w-4 h-4" strokeWidth={1.5} />
                    </button>
                  </div>
                  <div className="flex items-center gap-2 text-sm">
                    <span className="text-slate-400 dark:text-slate-500">{pf.holdings_count || 0} holdings</span>
                  </div>
                  <div className="mt-4 flex items-center gap-2">
                    <span className={`text-xs font-medium px-2 py-1 rounded-full ${
                      pf.relationship === "Self" ? "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400" :
                      pf.relationship === "Spouse" ? "bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400" :
                      "bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400"
                    }`}>{pf.relationship}</span>
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          ))}
        </div>
      )}

      {/* Create Dialog */}
      <Dialog open={showCreateDialog} onOpenChange={setShowCreateDialog}>
        <DialogContent className="sm:max-w-md rounded-2xl">
          <DialogHeader>
            <DialogTitle className="text-xl font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>Add Family Member</DialogTitle>
            <DialogDescription className="text-sm text-slate-500">Create a portfolio for a family member to track their investments separately.</DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreate} className="space-y-4 mt-2">
            <div>
              <label className="text-xs font-medium text-slate-500 mb-1 block">Portfolio Name *</label>
              <Input data-testid="portfolio-name-input" value={newPortfolio.name} onChange={e => setNewPortfolio({ ...newPortfolio, name: e.target.value })} placeholder="e.g. Wife's Investments" required className="rounded-xl" />
            </div>
            <div>
              <label className="text-xs font-medium text-slate-500 mb-1 block">Member Name *</label>
              <Input data-testid="member-name-input" value={newPortfolio.member_name} onChange={e => setNewPortfolio({ ...newPortfolio, member_name: e.target.value })} placeholder="e.g. Priya Sharma" required className="rounded-xl" />
            </div>
            <div>
              <label className="text-xs font-medium text-slate-500 mb-1 block">Relationship</label>
              <Select value={newPortfolio.relationship} onValueChange={v => setNewPortfolio({ ...newPortfolio, relationship: v })}>
                <SelectTrigger data-testid="relationship-select" className="rounded-xl"><SelectValue /></SelectTrigger>
                <SelectContent>
                  {RELATIONSHIPS.map(r => <SelectItem key={r} value={r}>{r}</SelectItem>)}
                </SelectContent>
              </Select>
            </div>
            <div className="flex justify-end gap-3 pt-2">
              <Button type="button" variant="outline" onClick={() => setShowCreateDialog(false)} className="rounded-xl">Cancel</Button>
              <Button data-testid="save-portfolio-button" type="submit" className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl">Create Portfolio</Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default FamilyView;
