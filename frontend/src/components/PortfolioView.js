import React, { useState, useRef } from "react";
import axios from "axios";
import { Plus, Upload, Trash2, Pencil, FileText, FileSpreadsheet, File } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toast } from "sonner";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

const ASSET_TYPES = [
  { value: "equity", label: "Equity (Stocks)" },
  { value: "mutual_fund", label: "Mutual Fund" },
  { value: "etf", label: "ETF" },
  { value: "bond", label: "Bonds" },
  { value: "gold", label: "Gold" },
  { value: "fd", label: "Fixed Deposit" },
  { value: "other", label: "Other" },
];

const SECTORS = [
  "IT", "Banking", "Pharma", "FMCG", "Auto", "Energy", "Metals", "Realty",
  "Telecom", "Infrastructure", "Financial Services", "Healthcare", "Media", "Other",
];

const ASSET_LABELS = {
  equity: "Equity",
  mutual_fund: "Mutual Fund",
  etf: "ETF",
  bond: "Bond",
  gold: "Gold",
  fd: "FD",
  other: "Other",
};

const PortfolioView = ({ holdings, onRefresh }) => {
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [showUploadDialog, setShowUploadDialog] = useState(false);
  const [editingHolding, setEditingHolding] = useState(null);
  const [formData, setFormData] = useState({
    name: "", ticker: "", asset_type: "equity", quantity: "", buy_price: "", current_price: "", sector: "Other", buy_date: "",
  });
  const [uploading, setUploading] = useState(false);
  const [uploadResult, setUploadResult] = useState(null);
  const fileRef = useRef(null);

  const resetForm = () => {
    setFormData({ name: "", ticker: "", asset_type: "equity", quantity: "", buy_price: "", current_price: "", sector: "Other", buy_date: "" });
    setEditingHolding(null);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const payload = {
      ...formData,
      quantity: parseFloat(formData.quantity) || 0,
      buy_price: parseFloat(formData.buy_price) || 0,
      current_price: parseFloat(formData.current_price) || 0,
    };

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
    } catch (err) {
      toast.error("Failed to save holding");
    }
  };

  const handleEdit = (h) => {
    setEditingHolding(h);
    setFormData({
      name: h.name, ticker: h.ticker || "", asset_type: h.asset_type, quantity: String(h.quantity),
      buy_price: String(h.buy_price), current_price: String(h.current_price), sector: h.sector || "Other", buy_date: h.buy_date || "",
    });
    setShowAddDialog(true);
  };

  const handleDelete = async (holdingId) => {
    try {
      await axios.delete(`${API}/portfolio/holdings/${holdingId}`, { withCredentials: true });
      toast.success("Holding deleted");
      onRefresh();
    } catch {
      toast.error("Failed to delete");
    }
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadResult(null);
    const formPayload = new FormData();
    formPayload.append("file", file);
    try {
      const res = await axios.post(`${API}/portfolio/upload`, formPayload, {
        withCredentials: true,
        headers: { "Content-Type": "multipart/form-data" },
      });
      
      // Check if it's an async task (CAS PDF)
      if (res.data.task_id && res.data.status === "processing") {
        toast.info("CAS PDF is being processed by AI. This may take 1-2 minutes...");
        setUploadResult({ message: "Processing CAS PDF with AI...", status: "processing" });
        // Poll for status
        const taskId = res.data.task_id;
        const pollInterval = setInterval(async () => {
          try {
            const statusRes = await axios.get(`${API}/portfolio/upload-status/${taskId}`, { withCredentials: true });
            const task = statusRes.data;
            if (task.status === "completed") {
              clearInterval(pollInterval);
              setUploadResult(task);
              setUploading(false);
              if (task.count > 0) {
                toast.success(task.message || `${task.count} holdings imported`);
              } else {
                toast.info(task.message || "No holdings found");
              }
              onRefresh();
            } else if (task.status === "error") {
              clearInterval(pollInterval);
              setUploadResult({ message: task.message, status: "error" });
              setUploading(false);
              toast.error(task.message || "CAS parsing failed");
            } else {
              setUploadResult({ message: task.message || "Processing...", status: "processing" });
            }
          } catch {
            // Keep polling
          }
        }, 5000);
        // Safety timeout after 5 minutes
        setTimeout(() => {
          clearInterval(pollInterval);
          setUploading(false);
        }, 300000);
      } else {
        // Synchronous result (CSV/Excel)
        setUploadResult(res.data);
        toast.success(res.data.message || `${res.data.count} holdings imported`);
        setUploading(false);
        onRefresh();
      }
    } catch (err) {
      const detail = err.response?.data?.detail || "Upload failed. Please check your file format.";
      toast.error(detail);
      setUploading(false);
    } finally {
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <div data-testid="portfolio-view">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl sm:text-3xl font-medium tracking-tight text-slate-900" style={{ fontFamily: "'Outfit', sans-serif" }}>
            Portfolio
          </h1>
          <p className="text-sm text-slate-500 mt-1">{holdings.length} holdings</p>
        </div>
        <div className="flex items-center gap-3">
          <input type="file" ref={fileRef} accept=".csv,.xlsx,.xls,.pdf" onChange={handleFileUpload} className="hidden" />
          <Button
            data-testid="upload-portfolio-button"
            variant="outline"
            onClick={() => setShowUploadDialog(true)}
            disabled={uploading}
            className="rounded-xl border-slate-200 text-slate-600 hover:bg-slate-50"
          >
            <Upload className="w-4 h-4 mr-2" strokeWidth={1.5} />
            {uploading ? "Processing..." : "Import Portfolio"}
          </Button>
          <Button
            data-testid="add-holding-button"
            onClick={() => { resetForm(); setShowAddDialog(true); }}
            className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl"
          >
            <Plus className="w-4 h-4 mr-2" strokeWidth={2} />
            Add Holding
          </Button>
        </div>
      </div>

      {/* Holdings Table */}
      {holdings.length === 0 ? (
        <Card className="bg-white border-slate-100 rounded-2xl shadow-none">
          <CardContent className="p-12 text-center">
            <p className="text-slate-500 text-sm">No holdings yet. Add your first investment above.</p>
          </CardContent>
        </Card>
      ) : (
        <Card className="bg-white border-slate-100 rounded-2xl shadow-none overflow-hidden" data-testid="holdings-table">
          <Table>
            <TableHeader>
              <TableRow className="border-slate-100 hover:bg-transparent">
                <TableHead className="text-xs font-bold tracking-[0.1em] uppercase text-slate-400 h-12">Name</TableHead>
                <TableHead className="text-xs font-bold tracking-[0.1em] uppercase text-slate-400 h-12">Type</TableHead>
                <TableHead className="text-xs font-bold tracking-[0.1em] uppercase text-slate-400 h-12">Qty</TableHead>
                <TableHead className="text-xs font-bold tracking-[0.1em] uppercase text-slate-400 h-12">Buy Price</TableHead>
                <TableHead className="text-xs font-bold tracking-[0.1em] uppercase text-slate-400 h-12">CMP</TableHead>
                <TableHead className="text-xs font-bold tracking-[0.1em] uppercase text-slate-400 h-12">P&L</TableHead>
                <TableHead className="text-xs font-bold tracking-[0.1em] uppercase text-slate-400 h-12">Sector</TableHead>
                <TableHead className="text-xs font-bold tracking-[0.1em] uppercase text-slate-400 h-12 w-20"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {holdings.map((h) => {
                const inv = h.quantity * h.buy_price;
                const cur = h.quantity * h.current_price;
                const pnl = cur - inv;
                const pnlPct = inv > 0 ? (pnl / inv) * 100 : 0;
                const isPositive = pnl >= 0;
                return (
                  <TableRow key={h.holding_id} className="border-slate-50 hover:bg-slate-50/50">
                    <TableCell className="py-4">
                      <div>
                        <p className="text-sm font-medium text-slate-900">{h.name}</p>
                        {h.ticker && <p className="text-xs text-slate-400">{h.ticker}</p>}
                      </div>
                    </TableCell>
                    <TableCell>
                      <span className="text-xs font-medium bg-slate-100 text-slate-600 px-2 py-1 rounded-full">
                        {ASSET_LABELS[h.asset_type] || h.asset_type}
                      </span>
                    </TableCell>
                    <TableCell className="text-sm text-slate-700">{h.quantity}</TableCell>
                    <TableCell className="text-sm text-slate-700">₹{h.buy_price.toLocaleString()}</TableCell>
                    <TableCell className="text-sm text-slate-700">₹{h.current_price.toLocaleString()}</TableCell>
                    <TableCell>
                      <div>
                        <p className={`text-sm font-medium ${isPositive ? "text-emerald-600" : "text-red-500"}`}>
                          {isPositive ? "+" : ""}₹{Math.abs(pnl).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                        </p>
                        <p className={`text-xs ${isPositive ? "text-emerald-500" : "text-red-400"}`}>
                          {isPositive ? "+" : ""}{pnlPct.toFixed(1)}%
                        </p>
                      </div>
                    </TableCell>
                    <TableCell className="text-sm text-slate-500">{h.sector}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-1">
                        <button
                          data-testid={`edit-holding-${h.holding_id}`}
                          onClick={() => handleEdit(h)}
                          className="p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
                        >
                          <Pencil className="w-4 h-4" strokeWidth={1.5} />
                        </button>
                        <button
                          data-testid={`delete-holding-${h.holding_id}`}
                          onClick={() => handleDelete(h.holding_id)}
                          className="p-1.5 rounded-lg hover:bg-red-50 text-slate-400 hover:text-red-500 transition-colors"
                        >
                          <Trash2 className="w-4 h-4" strokeWidth={1.5} />
                        </button>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </Card>
      )}

      {/* Add/Edit Dialog */}
      <Dialog open={showAddDialog} onOpenChange={setShowAddDialog}>
        <DialogContent className="sm:max-w-lg rounded-2xl">
          <DialogHeader>
            <DialogTitle className="text-xl font-medium text-slate-900" style={{ fontFamily: "'Outfit', sans-serif" }}>
              {editingHolding ? "Edit Holding" : "Add Holding"}
            </DialogTitle>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="space-y-4 mt-2">
            <div className="grid grid-cols-2 gap-4">
              <div className="col-span-2">
                <label className="text-xs font-medium text-slate-500 mb-1 block">Name *</label>
                <Input
                  data-testid="holding-name-input"
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  placeholder="e.g. Reliance Industries"
                  required
                  className="rounded-xl border-slate-200 focus:border-emerald-500"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-slate-500 mb-1 block">Ticker / Symbol</label>
                <Input
                  data-testid="holding-ticker-input"
                  value={formData.ticker}
                  onChange={(e) => setFormData({ ...formData, ticker: e.target.value })}
                  placeholder="e.g. RELIANCE"
                  className="rounded-xl border-slate-200 focus:border-emerald-500"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-slate-500 mb-1 block">Asset Type *</label>
                <Select value={formData.asset_type} onValueChange={(v) => setFormData({ ...formData, asset_type: v })}>
                  <SelectTrigger data-testid="holding-type-select" className="rounded-xl border-slate-200">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {ASSET_TYPES.map(t => (
                      <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-xs font-medium text-slate-500 mb-1 block">Quantity *</label>
                <Input
                  data-testid="holding-quantity-input"
                  type="number"
                  step="any"
                  value={formData.quantity}
                  onChange={(e) => setFormData({ ...formData, quantity: e.target.value })}
                  placeholder="10"
                  required
                  className="rounded-xl border-slate-200 focus:border-emerald-500"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-slate-500 mb-1 block">Buy Price (₹) *</label>
                <Input
                  data-testid="holding-buy-price-input"
                  type="number"
                  step="any"
                  value={formData.buy_price}
                  onChange={(e) => setFormData({ ...formData, buy_price: e.target.value })}
                  placeholder="1500"
                  required
                  className="rounded-xl border-slate-200 focus:border-emerald-500"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-slate-500 mb-1 block">Current Price (₹) *</label>
                <Input
                  data-testid="holding-current-price-input"
                  type="number"
                  step="any"
                  value={formData.current_price}
                  onChange={(e) => setFormData({ ...formData, current_price: e.target.value })}
                  placeholder="1800"
                  required
                  className="rounded-xl border-slate-200 focus:border-emerald-500"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-slate-500 mb-1 block">Sector</label>
                <Select value={formData.sector} onValueChange={(v) => setFormData({ ...formData, sector: v })}>
                  <SelectTrigger data-testid="holding-sector-select" className="rounded-xl border-slate-200">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {SECTORS.map(s => (
                      <SelectItem key={s} value={s}>{s}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-xs font-medium text-slate-500 mb-1 block">Buy Date</label>
                <Input
                  data-testid="holding-buy-date-input"
                  type="date"
                  value={formData.buy_date}
                  onChange={(e) => setFormData({ ...formData, buy_date: e.target.value })}
                  className="rounded-xl border-slate-200 focus:border-emerald-500"
                />
              </div>
            </div>
            <div className="flex items-center justify-end gap-3 pt-2">
              <Button type="button" variant="outline" onClick={() => setShowAddDialog(false)} className="rounded-xl border-slate-200">
                Cancel
              </Button>
              <Button data-testid="save-holding-button" type="submit" className="bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl">
                {editingHolding ? "Update" : "Add"} Holding
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      {/* Upload Dialog */}
      <Dialog open={showUploadDialog} onOpenChange={setShowUploadDialog}>
        <DialogContent className="sm:max-w-md rounded-2xl">
          <DialogHeader>
            <DialogTitle className="text-xl font-medium text-slate-900" style={{ fontFamily: "'Outfit', sans-serif" }}>
              Import Portfolio
            </DialogTitle>
            <DialogDescription className="text-sm text-slate-500">
              Upload your CAS statement, CSV, or Excel file to import holdings.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 mt-4">
            {/* File type options */}
            <div className="grid grid-cols-3 gap-3">
              <button
                data-testid="upload-type-cas"
                onClick={() => { fileRef.current.accept = ".pdf"; fileRef.current.click(); }}
                disabled={uploading}
                className="flex flex-col items-center gap-2 p-4 rounded-xl border border-slate-200 hover:border-emerald-300 hover:bg-emerald-50 transition-all duration-200"
              >
                <FileText className="w-8 h-8 text-red-500" strokeWidth={1.5} />
                <span className="text-xs font-medium text-slate-700">CAS PDF</span>
                <span className="text-[10px] text-slate-400">CAMS / Karvy</span>
              </button>
              <button
                data-testid="upload-type-csv"
                onClick={() => { fileRef.current.accept = ".csv"; fileRef.current.click(); }}
                disabled={uploading}
                className="flex flex-col items-center gap-2 p-4 rounded-xl border border-slate-200 hover:border-emerald-300 hover:bg-emerald-50 transition-all duration-200"
              >
                <File className="w-8 h-8 text-emerald-600" strokeWidth={1.5} />
                <span className="text-xs font-medium text-slate-700">CSV</span>
                <span className="text-[10px] text-slate-400">Broker export</span>
              </button>
              <button
                data-testid="upload-type-excel"
                onClick={() => { fileRef.current.accept = ".xlsx,.xls"; fileRef.current.click(); }}
                disabled={uploading}
                className="flex flex-col items-center gap-2 p-4 rounded-xl border border-slate-200 hover:border-emerald-300 hover:bg-emerald-50 transition-all duration-200"
              >
                <FileSpreadsheet className="w-8 h-8 text-green-600" strokeWidth={1.5} />
                <span className="text-xs font-medium text-slate-700">Excel</span>
                <span className="text-[10px] text-slate-400">.xlsx / .xls</span>
              </button>
            </div>

            {uploading && (
              <div className="flex items-center justify-center gap-3 py-4">
                <div className="w-5 h-5 border-2 border-emerald-600 border-t-transparent rounded-full animate-spin" />
                <span className="text-sm text-slate-500">
                  {uploadResult?.status === "processing" 
                    ? "AI is analyzing your CAS PDF... This may take 1-2 minutes." 
                    : "Processing file..."}
                </span>
              </div>
            )}

            {uploadResult && uploadResult.status === "error" && (
              <div className="bg-red-50 border border-red-200 rounded-xl p-4">
                <p className="text-sm font-medium text-red-800">{uploadResult.message}</p>
              </div>
            )}

            {uploadResult && uploadResult.count > 0 && (
              <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-4">
                <p className="text-sm font-medium text-emerald-800">{uploadResult.message}</p>
                {uploadResult.holdings?.length > 0 && (
                  <ul className="mt-2 space-y-1">
                    {uploadResult.holdings.slice(0, 5).map((h) => (
                      <li key={h.holding_id} className="text-xs text-emerald-600">
                        {h.name} ({h.asset_type}) - {h.quantity} units
                      </li>
                    ))}
                    {uploadResult.holdings.length > 5 && (
                      <li className="text-xs text-emerald-500">... and {uploadResult.holdings.length - 5} more</li>
                    )}
                  </ul>
                )}
              </div>
            )}

            <div className="bg-slate-50 rounded-xl p-4">
              <p className="text-xs font-medium text-slate-700 mb-2">Supported formats:</p>
              <ul className="text-xs text-slate-500 space-y-1">
                <li><span className="font-medium">CAS PDF</span> — Consolidated Account Statement from CAMS/Karvy (AI-parsed)</li>
                <li><span className="font-medium">CSV</span> — Broker exports from Zerodha, ICICI Direct, Angel One etc.</li>
                <li><span className="font-medium">Excel</span> — Custom spreadsheets with Name, Quantity, Buy Price columns</li>
              </ul>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default PortfolioView;
