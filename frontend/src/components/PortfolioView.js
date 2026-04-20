import React, { useState, useEffect, useRef, useMemo } from "react";
import axios from "axios";
import { Plus, Upload, Trash2, Pencil, FileText, File, FileSpreadsheet, Search, ArrowUpDown, Filter, Lock, ChevronDown, Calendar, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { toast } from "sonner";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";
import CasConnectButton from "@/components/CasConnectButton";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const ASSET_TYPES = [
  { value: "equity", label: "Equity (Stocks)" },
  { value: "mutual_fund", label: "Mutual Fund" },
  { value: "etf", label: "ETF" },
  { value: "bond", label: "Bonds" },
  { value: "gold", label: "Gold / SGB" },
  { value: "fd", label: "Fixed Deposit" },
  { value: "other", label: "Other" },
];

const SECTORS = ["IT","Banking","Pharma","FMCG","Auto","Energy","Metals","Realty","Telecom","Infrastructure","Financial Services","Healthcare","Media","Large Cap","Mid Cap","Small Cap","Flexi Cap","Multi Cap","Balanced","Index","ELSS","Debt","Gold","International","Other"];

const ASSET_LABELS = { equity: "Equity", mutual_fund: "Mutual Fund", etf: "ETF", bond: "Bond", gold: "Gold", fd: "FD", other: "Other" };

/**
 * Inline editor for a holding's buy_date.
 *
 * Click-to-edit: shows the date, or "—" + "Set" hint when missing.
 * Saves onBlur / Enter, cancels on Escape.
 */
const InlineBuyDateCell = ({ value, holdingId, onSaved }) => {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState((value || "").slice(0, 10));
  const [saving, setSaving] = useState(false);

  useEffect(() => { setDraft((value || "").slice(0, 10)); }, [value]);

  const commit = async () => {
    if (saving) return;
    if (draft === (value || "").slice(0, 10)) { setEditing(false); return; }
    setSaving(true);
    try {
      await axios.put(`${API}/portfolio/holdings/${holdingId}`,
        { buy_date: draft || null },
        { withCredentials: true }
      );
      toast.success("Buy date updated");
      onSaved && onSaved();
    } catch {
      toast.error("Couldn't save buy date");
    } finally {
      setSaving(false);
      setEditing(false);
    }
  };

  if (editing) {
    return (
      <div className="flex items-center gap-1">
        <input
          data-testid={`buy-date-input-${holdingId}`}
          type="date"
          value={draft}
          autoFocus
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") { setDraft((value || "").slice(0, 10)); setEditing(false); }
          }}
          className="h-7 text-xs bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded px-1.5 w-[130px]"
        />
        {saving && <Check className="w-3 h-3 text-emerald-500 animate-pulse" />}
      </div>
    );
  }

  const display = value ? String(value).slice(0, 10) : null;
  return (
    <button
      data-testid={`buy-date-cell-${holdingId}`}
      onClick={() => setEditing(true)}
      title="Click to edit buy date (affects LTCG/STCG calculations)"
      className="inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 transition-colors group"
    >
      <Calendar className="w-3 h-3 text-slate-400 group-hover:text-emerald-500" strokeWidth={2} />
      {display
        ? <span className="tabular-nums">{display}</span>
        : <span className="italic text-amber-600 dark:text-amber-400">Set date</span>}
    </button>
  );
};

const TAB_FILTERS = [
  { id: "all", label: "All" },
  { id: "equity", label: "Equity" },
  { id: "mutual_fund", label: "Mutual Funds" },
  { id: "etf", label: "ETFs" },
  { id: "gold", label: "Gold & SGB" },
  { id: "other_assets", label: "Other" },
];

const PortfolioView = ({ holdings, onRefresh, portfolios = [] }) => {
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [showUploadDialog, setShowUploadDialog] = useState(false);
  const [editingHolding, setEditingHolding] = useState(null);
  const [formData, setFormData] = useState({ name: "", ticker: "", asset_type: "equity", quantity: "", buy_price: "", current_price: "", sector: "Other", buy_date: "", portfolio_id: "" });
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);
  const [uploadPortfolioId, setUploadPortfolioId] = useState("");
  const [uploadPassword, setUploadPassword] = useState("");
  const fileRef = useRef(null);

  // Filters & Sorting
  const [activeAssetTab, setActiveAssetTab] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [sortField, setSortField] = useState("name");
  const [sortDir, setSortDir] = useState("asc");
  const [filterPortfolio, setFilterPortfolio] = useState("all");

  // Autocomplete
  const [autoResults, setAutoResults] = useState([]);
  const [showAuto, setShowAuto] = useState(false);
  const [clearing, setClearing] = useState(false);
  const autoRef = useRef(null);
  const autoTimeout = useRef(null);

  const clearPortfolio = async () => {
    if (!window.confirm("Clear all holdings? This cannot be undone.")) return;
    setClearing(true);
    try {
      const res = await axios.delete(`${API}/portfolio/holdings-all`, { withCredentials: true });
      toast.success(res.data.message || "Portfolio cleared");
      onRefresh();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Failed to clear");
    } finally {
      setClearing(false);
    }
  };

  const searchInstruments = async (q) => {
    if (q.length < 2) { setAutoResults([]); return; }
    try {
      const res = await axios.get(`${API}/search/instruments?q=${encodeURIComponent(q)}`, { withCredentials: true });
      setAutoResults(res.data);
      setShowAuto(true);
    } catch { setAutoResults([]); }
  };

  const handleNameChange = (val) => {
    setFormData({ ...formData, name: val });
    clearTimeout(autoTimeout.current);
    autoTimeout.current = setTimeout(() => searchInstruments(val), 300);
  };

  const selectInstrument = (inst) => {
    setFormData({ ...formData, name: inst.name, ticker: inst.ticker, asset_type: inst.type, sector: inst.sector });
    setShowAuto(false);
    setAutoResults([]);
  };

  // Filter & sort holdings
  const filteredHoldings = useMemo(() => {
    let list = [...holdings];
    // Portfolio filter
    if (filterPortfolio === "__unassigned") list = list.filter(h => !(h.portfolio_id));
    else if (filterPortfolio !== "all") list = list.filter(h => (h.portfolio_id || "") === filterPortfolio);
    // Asset tab filter
    if (activeAssetTab === "equity") list = list.filter(h => h.asset_type === "equity");
    else if (activeAssetTab === "mutual_fund") list = list.filter(h => h.asset_type === "mutual_fund");
    else if (activeAssetTab === "etf") list = list.filter(h => h.asset_type === "etf");
    else if (activeAssetTab === "gold") list = list.filter(h => ["gold", "bond"].includes(h.asset_type));
    else if (activeAssetTab === "other_assets") list = list.filter(h => ["fd", "other"].includes(h.asset_type));
    // Search
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      list = list.filter(h => h.name.toLowerCase().includes(q) || (h.ticker || "").toLowerCase().includes(q) || (h.sector || "").toLowerCase().includes(q));
    }
    // Sort
    list.sort((a, b) => {
      let va, vb;
      if (sortField === "name") { va = a.name.toLowerCase(); vb = b.name.toLowerCase(); }
      else if (sortField === "value") { va = a.quantity * a.current_price; vb = b.quantity * b.current_price; }
      else if (sortField === "returns") { va = (a.current_price - a.buy_price) / (a.buy_price || 1); vb = (b.current_price - b.buy_price) / (b.buy_price || 1); }
      else if (sortField === "quantity") { va = a.quantity; vb = b.quantity; }
      else { va = a[sortField]; vb = b[sortField]; }
      if (va < vb) return sortDir === "asc" ? -1 : 1;
      if (va > vb) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    return list;
  }, [holdings, activeAssetTab, searchQuery, sortField, sortDir, filterPortfolio]);

  // Top gainers/losers for chart
  const moversData = useMemo(() => {
    const list = filteredHoldings.map(h => {
      const inv = h.quantity * h.buy_price;
      const cur = h.quantity * h.current_price;
      return { name: h.name.length > 18 ? h.name.slice(0, 18) + ".." : h.name, pct: inv > 0 ? parseFloat(((cur - inv) / inv * 100).toFixed(1)) : 0 };
    }).filter(h => h.pct !== 0).sort((a, b) => b.pct - a.pct);
    return { gainers: list.filter(h => h.pct > 0).slice(0, 8), losers: list.filter(h => h.pct < 0).slice(-8).reverse() };
  }, [filteredHoldings]);

  const resetForm = () => {
    setFormData({ name: "", ticker: "", asset_type: "equity", quantity: "", buy_price: "", current_price: "", sector: "Other", buy_date: "", portfolio_id: "" });
    setEditingHolding(null);
    setAutoResults([]);
    setShowAuto(false);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const payload = { ...formData, quantity: parseFloat(formData.quantity) || 0, buy_price: parseFloat(formData.buy_price) || 0, current_price: parseFloat(formData.current_price) || 0, portfolio_id: formData.portfolio_id === "__none" ? "" : formData.portfolio_id };
    try {
      if (editingHolding) {
        await axios.put(`${API}/portfolio/holdings/${editingHolding.holding_id}`, payload, { withCredentials: true });
        toast.success("Holding updated");
      } else {
        await axios.post(`${API}/portfolio/holdings`, payload, { withCredentials: true });
        toast.success("Holding added");
      }
      setShowAddDialog(false);
      resetForm();
      onRefresh();
    } catch { toast.error("Failed to save holding"); }
  };

  const handleEdit = (h) => {
    setEditingHolding(h);
    setFormData({ name: h.name, ticker: h.ticker || "", asset_type: h.asset_type, quantity: String(h.quantity), buy_price: String(h.buy_price), current_price: String(h.current_price), sector: h.sector || "Other", buy_date: h.buy_date || "", portfolio_id: h.portfolio_id || "" });
    setShowAddDialog(true);
  };

  const handleDelete = async (holdingId) => {
    try {
      await axios.delete(`${API}/portfolio/holdings/${holdingId}`, { withCredentials: true });
      toast.success("Holding deleted");
      onRefresh();
    } catch { toast.error("Failed to delete"); }
  };

  // Upload polling helper
  const startPolling = (taskId) => {
    toast.info("CAS PDF is being processed by AI. This may take 1-2 minutes...");
    setUploadResult({ message: "Processing CAS PDF with AI...", status: "processing" });
    const pollInterval = setInterval(async () => {
      try {
        const statusRes = await axios.get(`${API}/portfolio/upload-status/${taskId}`, { withCredentials: true });
        const task = statusRes.data;
        if (task.status === "completed") {
          clearInterval(pollInterval); setUploadResult(task); setUploading(false);
          toast.success(task.message || `${task.count} holdings imported`);
          onRefresh();
          // Auto-close dialog after 2 seconds
          setTimeout(() => { setShowUploadDialog(false); setUploadResult(null); setUploadPassword(""); }, 2000);
        } else if (task.status === "error") {
          clearInterval(pollInterval); setUploadResult({ message: task.message, status: "error" }); setUploading(false);
          toast.error(task.message);
        } else { setUploadResult({ message: task.message || "AI analyzing CAS...", status: "processing" }); }
      } catch {}
    }, 5000);
    setTimeout(() => { clearInterval(pollInterval); setUploading(false); }, 300000);
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true); setUploadResult(null);
    const isPdf = file.name.toLowerCase().endsWith(".pdf");
    try {
      let res;
      if (isPdf) {
        res = await axios.post(`${API}/portfolio/upload-raw`, file, {
          withCredentials: true,
          headers: { "Content-Type": "application/octet-stream", "X-Filename": file.name, "X-Portfolio-Id": (uploadPortfolioId === "__general" ? "" : uploadPortfolioId) || "", "X-Password": uploadPassword || "" },
          timeout: 120000,
        });
      } else {
        const form = new FormData(); form.append("file", file);
        res = await axios.post(`${API}/portfolio/upload`, form, { withCredentials: true, headers: { "Content-Type": "multipart/form-data" }, timeout: 30000 });
      }
      if (res.data.task_id && res.data.status === "processing") { startPolling(res.data.task_id); }
      else { setUploadResult(res.data); toast.success(res.data.message); setUploading(false); onRefresh(); setTimeout(() => { setShowUploadDialog(false); setUploadResult(null); setUploadPassword(""); }, 2000); }
    } catch (err) {
      if (isPdf && (!err.response || err.code === "ECONNABORTED")) {
        toast.info("Checking processing status...");
        await new Promise(r => setTimeout(r, 3000));
        try {
          const tr = await axios.get(`${API}/portfolio/upload-latest-task`, { withCredentials: true });
          if (tr.data?.task_id) { startPolling(tr.data.task_id); return; }
        } catch {}
      }
      toast.error(err.response?.data?.detail || "Upload failed");
      setUploading(false);
    } finally { if (fileRef.current) fileRef.current.value = ""; }
  };

  const toggleSort = (field) => {
    if (sortField === field) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortField(field); setSortDir("asc"); }
  };

  const pfName = (id) => portfolios.find(p => p.portfolio_id === id)?.name || "";

  return (
    <div data-testid="portfolio-view">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl sm:text-3xl font-medium tracking-tight text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>Portfolio</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">{holdings.length} total holdings</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <CasConnectButton
            variant="outline"
            className="rounded-xl border-emerald-200 dark:border-emerald-700 text-emerald-700 dark:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-900/20"
            label="CAS Connect"
            testId="header-cas-connect-btn"
            onSuccess={onRefresh}
          />
          <Button data-testid="add-holding-button" onClick={() => { resetForm(); setShowAddDialog(true); }} className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl">
            <Plus className="w-4 h-4 mr-2" />Add Holding
          </Button>
        </div>
      </div>

      {/* Filters Bar */}
      <div className="flex flex-col sm:flex-row gap-2 sm:gap-3 mb-4">
        <div className="relative flex-1">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <Input data-testid="search-holdings" value={searchQuery} onChange={e => setSearchQuery(e.target.value)} placeholder="Search by name, ticker, sector..." className="pl-10 rounded-xl border-slate-200 dark:border-slate-700 dark:bg-slate-800 dark:text-white" />
        </div>
        {portfolios.length > 0 && (
          <Select value={filterPortfolio} onValueChange={setFilterPortfolio}>
            <SelectTrigger data-testid="filter-portfolio" className="w-full sm:w-48 rounded-xl border-slate-200 dark:border-slate-700"><SelectValue placeholder="All Members" /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Members</SelectItem>
              {portfolios.map(p => <SelectItem key={p.portfolio_id} value={p.portfolio_id}>{p.name}</SelectItem>)}
              <SelectItem value="__unassigned">Unassigned</SelectItem>
            </SelectContent>
          </Select>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" className="rounded-xl border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300">
              <ArrowUpDown className="w-4 h-4 mr-2" />Sort
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent>
            <DropdownMenuItem onClick={() => toggleSort("name")}>Name {sortField === "name" && (sortDir === "asc" ? "A-Z" : "Z-A")}</DropdownMenuItem>
            <DropdownMenuItem onClick={() => toggleSort("value")}>Value {sortField === "value" && (sortDir === "asc" ? "Low-High" : "High-Low")}</DropdownMenuItem>
            <DropdownMenuItem onClick={() => toggleSort("returns")}>Returns % {sortField === "returns" && (sortDir === "asc" ? "Low-High" : "High-Low")}</DropdownMenuItem>
            <DropdownMenuItem onClick={() => toggleSort("quantity")}>Quantity</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        {holdings.length > 0 && (
          <Button
            variant="outline"
            onClick={clearPortfolio}
            disabled={clearing}
            className="rounded-xl border-red-200 dark:border-red-800 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 hover:text-red-600"
            data-testid="clear-portfolio-button"
          >
            <Trash2 className="w-4 h-4 mr-2" />{clearing ? "Clearing..." : "Clear All"}
          </Button>
        )}
      </div>

      {/* Asset Type Tabs */}

      {/* Latest CAS notice */}
      {holdings.length > 0 && (() => {
        const latest = holdings.reduce((max, h) => {
          const t = h.uploaded_at || h.created_at || "";
          return t > max ? t : max;
        }, "");
        const formatted = latest ? new Date(latest).toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
        return (
          <p className="text-[10px] text-slate-400 dark:text-slate-500 text-center -mt-2 mb-2">
            {formatted && <span>Last updated: <strong className="text-slate-500 dark:text-slate-400">{formatted}</strong> &middot; </span>}
            Only the latest uploaded CAS will be considered. Re-uploading replaces the previous portfolio.
          </p>
        );
      })()}

      <Tabs value={activeAssetTab} onValueChange={setActiveAssetTab} className="mb-6">
        <TabsList className="bg-slate-100 dark:bg-slate-800 rounded-xl p-1 overflow-x-auto w-full justify-start scrollbar-hide">
          {TAB_FILTERS.map(t => (
            <TabsTrigger key={t.id} value={t.id} data-testid={`tab-${t.id}`} className="rounded-lg text-xs data-[state=active]:bg-white dark:data-[state=active]:bg-slate-700 data-[state=active]:shadow-sm flex-shrink-0 whitespace-nowrap">
              {t.label}
              <span className="ml-1 text-[10px] text-slate-400">
                ({t.id === "all" ? holdings.length : holdings.filter(h => t.id === "gold" ? ["gold","bond"].includes(h.asset_type) : t.id === "other_assets" ? ["fd","other"].includes(h.asset_type) : h.asset_type === t.id).length})
              </span>
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {/* Holdings Table */}
      {filteredHoldings.length === 0 ? (
        <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl shadow-none">
          <CardContent className="p-12 text-center">
            <Upload className="w-12 h-12 text-slate-300 dark:text-slate-600 mx-auto mb-4" strokeWidth={1.5} />
            <h3 className="text-lg font-medium text-slate-900 dark:text-white mb-2" style={{ fontFamily: "'Outfit', sans-serif" }}>
              {searchQuery || activeAssetTab !== "all" ? "No holdings match your filters" : "No holdings yet"}
            </h3>
            <p className="text-sm text-slate-500 dark:text-slate-400 mb-6 max-w-md mx-auto">
              {searchQuery || activeAssetTab !== "all"
                ? "Try adjusting your search or filter."
                : "Upload your NSDL/CDSL CAS statement or connect Gmail to auto-import your portfolio."}
            </p>
            {!searchQuery && activeAssetTab === "all" && (
              <div className="flex flex-wrap items-center justify-center gap-3">
                <CasConnectButton
                  className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl"
                  label="Import via CAS Connect"
                  testId="empty-cas-connect-btn"
                  onSuccess={onRefresh}
                />
                <Button variant="outline" onClick={() => setShowAddDialog(true)} className="rounded-xl border-slate-200 dark:border-slate-700" data-testid="empty-add-btn">
                  <Plus className="w-4 h-4 mr-2" /> Add Manually
                </Button>
              </div>
            )}
            <p className="text-[10px] text-slate-400 dark:text-slate-500 mt-4">
              Only the latest uploaded CAS will be considered. Re-uploading replaces the previous portfolio.
            </p>
          </CardContent>
        </Card>
      ) : (
        <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl shadow-none overflow-hidden" data-testid="holdings-table">
          <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="border-slate-100 dark:border-slate-700 hover:bg-transparent">
                <TableHead className="text-[10px] font-bold tracking-[0.1em] uppercase text-slate-400 h-10 cursor-pointer" onClick={() => toggleSort("name")}>Name</TableHead>
                <TableHead className="text-[10px] font-bold tracking-[0.1em] uppercase text-slate-400 h-10">Type</TableHead>
                <TableHead className="text-[10px] font-bold tracking-[0.1em] uppercase text-slate-400 h-10 cursor-pointer" onClick={() => toggleSort("quantity")}>Qty</TableHead>
                <TableHead className="text-[10px] font-bold tracking-[0.1em] uppercase text-slate-400 h-10">Buy</TableHead>
                <TableHead className="text-[10px] font-bold tracking-[0.1em] uppercase text-slate-400 h-10">Buy Date</TableHead>
                <TableHead className="text-[10px] font-bold tracking-[0.1em] uppercase text-slate-400 h-10">CMP</TableHead>
                <TableHead className="text-[10px] font-bold tracking-[0.1em] uppercase text-slate-400 h-10 cursor-pointer" onClick={() => toggleSort("value")}>Value</TableHead>
                <TableHead className="text-[10px] font-bold tracking-[0.1em] uppercase text-slate-400 h-10 cursor-pointer" onClick={() => toggleSort("returns")}>P&L</TableHead>
                <TableHead className="text-[10px] font-bold tracking-[0.1em] uppercase text-slate-400 h-10">Sector</TableHead>
                {portfolios.length > 0 && <TableHead className="text-[10px] font-bold tracking-[0.1em] uppercase text-slate-400 h-10">Member</TableHead>}
                <TableHead className="w-16" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredHoldings.map(h => {
                const inv = h.quantity * h.buy_price;
                const cur = h.quantity * h.current_price;
                const pnl = cur - inv;
                const pnlPct = inv > 0 ? (pnl / inv) * 100 : 0;
                const pos = pnl >= 0;
                return (
                  <TableRow key={h.holding_id} className={`border-slate-50 dark:border-slate-700/50 hover:bg-slate-50/50 dark:hover:bg-slate-700/30 ${
                    (h.buy_price > 0 && Math.abs(h.buy_price - h.current_price) < 0.01) ? "bg-amber-50/40 dark:bg-amber-900/10" : ""
                  }`}>
                    <TableCell className="py-3">
                      <p className="text-sm font-medium text-slate-900 dark:text-white">{h.name}</p>
                      {h.ticker && <p className="text-[10px] text-slate-400">{h.ticker}</p>}
                    </TableCell>
                    <TableCell><span className="text-[10px] font-medium bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 px-2 py-0.5 rounded-full">{ASSET_LABELS[h.asset_type] || h.asset_type}</span></TableCell>
                    <TableCell className="text-sm text-slate-700 dark:text-slate-300">{h.quantity.toLocaleString(undefined, {maximumFractionDigits: 3})}</TableCell>
                    <TableCell className="text-sm text-slate-700 dark:text-slate-300">₹{h.buy_price.toLocaleString()}</TableCell>
                    <TableCell>
                      <InlineBuyDateCell
                        value={h.buy_date}
                        holdingId={h.holding_id}
                        onSaved={onRefresh}
                      />
                    </TableCell>
                    <TableCell className="text-sm text-slate-700 dark:text-slate-300">
                      <span className={`${(h.buy_price > 0 && Math.abs(h.buy_price - h.current_price) < 0.01) ? "text-amber-600 dark:text-amber-400" : ""}`}>
                        ₹{h.current_price.toLocaleString()}
                      </span>
                      {h.buy_price > 0 && Math.abs(h.buy_price - h.current_price) < 0.01 && (
                        <span className="block text-[9px] text-amber-500 font-medium">No live CMP</span>
                      )}
                    </TableCell>
                    <TableCell className="text-sm font-medium text-slate-900 dark:text-white">₹{cur.toLocaleString(undefined, {maximumFractionDigits: 0})}</TableCell>
                    <TableCell>
                      <p className={`text-sm font-medium ${pos ? "text-emerald-600" : "text-red-500"}`}>{pos ? "+" : ""}₹{Math.abs(pnl).toLocaleString(undefined, {maximumFractionDigits: 0})}</p>
                      <p className={`text-[10px] ${pos ? "text-emerald-500" : "text-red-400"}`}>{pos ? "+" : ""}{pnlPct.toFixed(1)}%</p>
                    </TableCell>
                    <TableCell className="text-xs text-slate-500 dark:text-slate-400">{h.sector}</TableCell>
                    {portfolios.length > 0 && <TableCell className="text-xs text-slate-400">{pfName(h.portfolio_id)}</TableCell>}
                    <TableCell>
                      <div className="flex gap-1">
                        <button onClick={() => handleEdit(h)} className="p-1 rounded hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-400 hover:text-slate-600"><Pencil className="w-3.5 h-3.5" /></button>
                        <button onClick={() => handleDelete(h.holding_id)} className="p-1 rounded hover:bg-red-50 dark:hover:bg-red-900/20 text-slate-400 hover:text-red-500"><Trash2 className="w-3.5 h-3.5" /></button>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          </div>
          <div className="px-4 sm:px-6 py-3 border-t border-slate-100 dark:border-slate-700 text-xs text-slate-400">
            Showing {filteredHoldings.length} of {holdings.length} holdings
          </div>
        </Card>
      )}

      {/* Top Movers Chart */}
      {(moversData.gainers.length > 0 || moversData.losers.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-6">
          {moversData.gainers.length > 0 && (
            <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl shadow-none" data-testid="gainers-chart">
              <CardContent className="p-6">
                <h3 className="text-base font-medium text-slate-900 dark:text-white mb-4" style={{ fontFamily: "'Outfit', sans-serif" }}>Top Gainers</h3>
                <div className="h-52">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={moversData.gainers} layout="vertical" margin={{ left: 0, right: 10 }}>
                      <XAxis type="number" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#94A3B8" }} tickFormatter={v => `${v}%`} />
                      <YAxis type="category" dataKey="name" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#64748B" }} width={110} />
                      <Tooltip formatter={v => [`${v}%`, "Return"]} contentStyle={{ borderRadius: 10, border: "1px solid #E2E8F0", fontSize: 12 }} />
                      <Bar dataKey="pct" radius={[0, 6, 6, 0]} barSize={14}>
                        {moversData.gainers.map((_, i) => <Cell key={i} fill="#10B981" fillOpacity={0.7 + i * 0.03} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>
          )}
          {moversData.losers.length > 0 && (
            <Card className="bg-white dark:bg-slate-800 border-slate-100 dark:border-slate-700 rounded-2xl shadow-none" data-testid="losers-chart">
              <CardContent className="p-6">
                <h3 className="text-base font-medium text-slate-900 dark:text-white mb-4" style={{ fontFamily: "'Outfit', sans-serif" }}>Top Losers</h3>
                <div className="h-52">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={moversData.losers} layout="vertical" margin={{ left: 0, right: 10 }}>
                      <XAxis type="number" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#94A3B8" }} tickFormatter={v => `${v}%`} />
                      <YAxis type="category" dataKey="name" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#64748B" }} width={110} />
                      <Tooltip formatter={v => [`${v}%`, "Return"]} contentStyle={{ borderRadius: 10, border: "1px solid #E2E8F0", fontSize: 12 }} />
                      <Bar dataKey="pct" radius={[0, 6, 6, 0]} barSize={14}>
                        {moversData.losers.map((_, i) => <Cell key={i} fill="#EF4444" fillOpacity={0.7 + i * 0.03} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* Add/Edit Dialog with Autocomplete */}
      <Dialog open={showAddDialog} onOpenChange={setShowAddDialog}>
        <DialogContent className="sm:max-w-lg rounded-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="text-xl font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>{editingHolding ? "Edit Holding" : "Add Holding"}</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="space-y-4 mt-2">
            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2 relative" ref={autoRef}>
                <label className="text-xs font-medium text-slate-500 mb-1 block">Name *</label>
                <Input data-testid="holding-name-input" value={formData.name} onChange={e => handleNameChange(e.target.value)} onFocus={() => formData.name.length >= 2 && searchInstruments(formData.name)} placeholder="Type to search stocks, MFs..." required className="rounded-xl" autoComplete="off" />
                {showAuto && autoResults.length > 0 && (
                  <div className="absolute z-50 top-full left-0 right-0 mt-1 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl shadow-lg max-h-48 overflow-y-auto">
                    {autoResults.map((inst, i) => (
                      <button key={i} type="button" onClick={() => selectInstrument(inst)} className="w-full text-left px-4 py-2.5 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 transition-colors flex items-center justify-between border-b border-slate-50 dark:border-slate-700/50 last:border-0">
                        <div>
                          <p className="text-sm text-slate-900 dark:text-white font-medium">{inst.name}</p>
                          <p className="text-[10px] text-slate-400">{inst.ticker} &middot; {inst.sector}</p>
                        </div>
                        <span className="text-[10px] font-medium bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 px-2 py-0.5 rounded-full">{ASSET_LABELS[inst.type] || inst.type}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <div>
                <label className="text-xs font-medium text-slate-500 mb-1 block">Ticker</label>
                <Input data-testid="holding-ticker-input" value={formData.ticker} onChange={e => setFormData({ ...formData, ticker: e.target.value })} placeholder="RELIANCE" className="rounded-xl" />
              </div>
              <div>
                <label className="text-xs font-medium text-slate-500 mb-1 block">Type *</label>
                <Select value={formData.asset_type} onValueChange={v => setFormData({ ...formData, asset_type: v })}>
                  <SelectTrigger className="rounded-xl"><SelectValue /></SelectTrigger>
                  <SelectContent>{ASSET_TYPES.map(t => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-xs font-medium text-slate-500 mb-1 block">Quantity *</label>
                <Input data-testid="holding-quantity-input" type="number" step="any" value={formData.quantity} onChange={e => setFormData({ ...formData, quantity: e.target.value })} required className="rounded-xl" />
              </div>
              <div>
                <label className="text-xs font-medium text-slate-500 mb-1 block">Buy Price *</label>
                <Input type="number" step="any" value={formData.buy_price} onChange={e => setFormData({ ...formData, buy_price: e.target.value })} required className="rounded-xl" />
              </div>
              <div>
                <label className="text-xs font-medium text-slate-500 mb-1 block">Current Price *</label>
                <Input type="number" step="any" value={formData.current_price} onChange={e => setFormData({ ...formData, current_price: e.target.value })} required className="rounded-xl" />
              </div>
              <div>
                <label className="text-xs font-medium text-slate-500 mb-1 block">Sector</label>
                <Select value={formData.sector} onValueChange={v => setFormData({ ...formData, sector: v })}>
                  <SelectTrigger className="rounded-xl"><SelectValue /></SelectTrigger>
                  <SelectContent>{SECTORS.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}</SelectContent>
                </Select>
              </div>
              {portfolios.length > 0 && (
                <div>
                  <label className="text-xs font-medium text-slate-500 mb-1 block">Portfolio</label>
                  <Select value={formData.portfolio_id} onValueChange={v => setFormData({ ...formData, portfolio_id: v })}>
                    <SelectTrigger className="rounded-xl"><SelectValue placeholder="Select member" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="__none">None</SelectItem>
                      {portfolios.map(p => <SelectItem key={p.portfolio_id} value={p.portfolio_id}>{p.name}</SelectItem>)}
                    </SelectContent>
                  </Select>
                </div>
              )}
            </div>
            <div className="flex justify-end gap-3 pt-2">
              <Button type="button" variant="outline" onClick={() => setShowAddDialog(false)} className="rounded-xl">Cancel</Button>
              <Button data-testid="save-holding-button" type="submit" className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl">{editingHolding ? "Update" : "Add"}</Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      {/* Upload Dialog with Portfolio & Password */}
      <Dialog open={showUploadDialog} onOpenChange={setShowUploadDialog}>
        <DialogContent className="sm:max-w-md rounded-2xl">
          <DialogHeader>
            <DialogTitle className="text-xl font-medium text-slate-900 dark:text-white" style={{ fontFamily: "'Outfit', sans-serif" }}>Import Portfolio</DialogTitle>
            <DialogDescription>Upload CAS statement, CSV, or Excel to import holdings.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 mt-4">
            {portfolios.length > 0 && (
              <div>
                <label className="text-xs font-medium text-slate-500 mb-1 block">Assign to Portfolio</label>
                <Select value={uploadPortfolioId} onValueChange={setUploadPortfolioId}>
                  <SelectTrigger data-testid="upload-portfolio-select" className="rounded-xl"><SelectValue placeholder="Select member" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="__general">None (General)</SelectItem>
                    {portfolios.map(p => <SelectItem key={p.portfolio_id} value={p.portfolio_id}>{p.name} ({p.relationship})</SelectItem>)}
                  </SelectContent>
                </Select>
              </div>
            )}
            <div>
              <label className="text-xs font-medium text-slate-500 mb-1 block flex items-center gap-1"><Lock className="w-3 h-3" />PDF Password (if any)</label>
              <Input data-testid="upload-password-input" type="password" value={uploadPassword} onChange={e => setUploadPassword(e.target.value)} placeholder="Leave empty if not password-protected" className="rounded-xl" />
            </div>
            <div className="grid grid-cols-3 gap-3">
              <button data-testid="upload-type-cas" onClick={() => { fileRef.current.accept = ".pdf"; fileRef.current.click(); }} disabled={uploading} className="flex flex-col items-center gap-2 p-4 rounded-xl border border-slate-200 dark:border-slate-700 hover:border-emerald-300 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 transition-all">
                <FileText className="w-8 h-8 text-red-500" strokeWidth={1.5} />
                <span className="text-xs font-medium text-slate-700 dark:text-slate-300">CAS PDF</span>
              </button>
              <button data-testid="upload-type-csv" onClick={() => { fileRef.current.accept = ".csv"; fileRef.current.click(); }} disabled={uploading} className="flex flex-col items-center gap-2 p-4 rounded-xl border border-slate-200 dark:border-slate-700 hover:border-emerald-300 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 transition-all">
                <File className="w-8 h-8 text-emerald-600" strokeWidth={1.5} />
                <span className="text-xs font-medium text-slate-700 dark:text-slate-300">CSV</span>
              </button>
              <button data-testid="upload-type-excel" onClick={() => { fileRef.current.accept = ".xlsx,.xls"; fileRef.current.click(); }} disabled={uploading} className="flex flex-col items-center gap-2 p-4 rounded-xl border border-slate-200 dark:border-slate-700 hover:border-emerald-300 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 transition-all">
                <FileSpreadsheet className="w-8 h-8 text-green-600" strokeWidth={1.5} />
                <span className="text-xs font-medium text-slate-700 dark:text-slate-300">Excel</span>
              </button>
            </div>
            {uploading && <div className="flex items-center justify-center gap-3 py-3"><div className="w-5 h-5 border-2 border-emerald-600 border-t-transparent rounded-full animate-spin" /><span className="text-sm text-slate-500">{uploadResult?.status === "processing" ? "AI analyzing CAS..." : "Processing..."}</span></div>}
            {uploadResult && uploadResult.status === "error" && <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl p-3"><p className="text-sm text-red-700 dark:text-red-400">{uploadResult.message}</p></div>}
            {uploadResult && uploadResult.count > 0 && <div className="bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800 rounded-xl p-3"><p className="text-sm font-medium text-emerald-800 dark:text-emerald-400">{uploadResult.message}</p></div>}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default PortfolioView;
