"use client";

import React, { useEffect, useState, useCallback, useRef } from "react";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { Pagination } from "@/components/Pagination";
import { api } from "@/lib/api";
import {
  ShieldAlert,
  Database,
  FileSpreadsheet,
  Upload,
  ArrowRight,
  CheckCircle,
  AlertTriangle,
  RotateCcw,
  Volume2,
  FileText,
  Activity,
  Layers,
  Lock,
  Eye,
  RefreshCw,
  Search,
  Filter,
  Check,
  X,
  Play,
  Pause,
  AlertOctagon,
} from "lucide-react";

// Available canonical target fields for real estate ingestion
const CANONICAL_TARGET_FIELDS = [
  { value: "company_name", label: "Company / Developer Name" },
  { value: "project_name", label: "Project / Society Name" },
  { value: "city", label: "City" },
  { value: "state", label: "State" },
  { value: "postal_code", label: "Postal / Pin Code" },
  { value: "address_line_1", label: "Street Address" },
  { value: "property_name", label: "Property / Tower / Phase" },
  { value: "unit_number", label: "Unit / Flat / Door Number" },
  { value: "configuration_type", label: "Config (e.g. 2 BHK, 3 BHK)" },
  { value: "carpet_area_sqft", label: "Carpet Area (sq.ft)" },
  { value: "super_built_up_area_sqft", label: "Super Built-up Area (sq.ft)" },
  { value: "base_price", label: "Base Price (INR / Explicit Currency)" },
  { value: "availability_status", label: "Availability Status (available/reserved/sold)" },
  { value: "amenities", label: "Amenities (comma-separated or list)" },
];

export default function SuperOwnerDashboard() {
  const [activeTab, setActiveTab] = useState<"overview" | "ingestion" | "audit" | "privileged">("overview");

  // =========================================================================
  // Tab 1: Overview Metrics State
  // =========================================================================
  const [metrics, setMetrics] = useState({
    totalBatches: 0,
    totalAuditLogs: 0,
    totalConversations: 0,
    totalCustomers: 0,
  });
  const [metricsLoading, setMetricsLoading] = useState(false);

  // =========================================================================
  // Tab 2: Ingestion Pipeline State
  // =========================================================================
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewData, setPreviewData] = useState<any | null>(null);
  const [columnMappings, setColumnMappings] = useState<Record<string, string>>({});
  const [conflictStrategy, setConflictStrategy] = useState<"NEW_VERSION" | "OVERWRITE" | "SKIP">("NEW_VERSION");
  const [executeLoading, setExecuteLoading] = useState(false);
  const [ingestionResult, setIngestionResult] = useState<any | null>(null);
  const [ingestionError, setIngestionError] = useState<string | null>(null);

  // Ingestion Batches history
  const [batches, setBatches] = useState<any[]>([]);
  const [batchesLoading, setBatchesLoading] = useState(false);
  const [rollbackLoading, setRollbackLoading] = useState<string | null>(null);

  // =========================================================================
  // Tab 3: Privileged Transcript & Audio Inspection State
  // =========================================================================
  const [inspectSessionId, setInspectSessionId] = useState("");
  const [confirmAuditModal, setConfirmAuditModal] = useState<"transcript" | "audio" | null>(null);
  const [privTranscript, setPrivTranscript] = useState<any | null>(null);
  const [privAudio, setPrivAudio] = useState<any | null>(null);
  const [privLoading, setPrivLoading] = useState(false);
  const [privError, setPrivError] = useState<string | null>(null);
  const [isPlayingAudio, setIsPlayingAudio] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // =========================================================================
  // Tab 4: Audit Logs State
  // =========================================================================
  const [auditLogs, setAuditLogs] = useState<any[]>([]);
  const [auditActionFilter, setAuditActionFilter] = useState("");
  const [auditResourceFilter, setAuditResourceFilter] = useState("");
  const [auditLimit] = useState(20);
  const [auditOffset, setAuditOffset] = useState(0);
  const [auditLoading, setAuditLoading] = useState(false);

  // -------------------------------------------------------------------------
  // Fetch Overview Data
  // -------------------------------------------------------------------------
  const fetchOverview = useCallback(async () => {
    setMetricsLoading(true);
    try {
      const [batchesRes, auditRes, convRes, custRes] = await Promise.allSettled([
        api.superOwner.getBatches(),
        api.superOwner.getAuditLogs({ limit: 1 }),
        api.admin.getConversations({ limit: 1 }),
        api.admin.getCustomers({ limit: 1 }),
      ]);

      setMetrics({
        totalBatches: batchesRes.status === "fulfilled" ? batchesRes.value.length : 0,
        totalAuditLogs: auditRes.status === "fulfilled" ? auditRes.value.length : 0,
        totalConversations: convRes.status === "fulfilled" ? convRes.value.length : 0,
        totalCustomers: custRes.status === "fulfilled" ? custRes.value.length : 0,
      });

      if (batchesRes.status === "fulfilled") {
        setBatches(batchesRes.value);
      }
    } catch (err) {
      console.error("Error loading overview metrics:", err);
    } finally {
      setMetricsLoading(false);
    }
  }, []);

  // -------------------------------------------------------------------------
  // Fetch Batches
  // -------------------------------------------------------------------------
  const fetchBatches = useCallback(async () => {
    setBatchesLoading(true);
    try {
      const data = await api.superOwner.getBatches();
      setBatches(data);
    } catch (err) {
      console.error("Error fetching batches:", err);
    } finally {
      setBatchesLoading(false);
    }
  }, []);

  // -------------------------------------------------------------------------
  // Fetch Audit Logs
  // -------------------------------------------------------------------------
  const fetchAuditLogs = useCallback(async () => {
    setAuditLoading(true);
    try {
      const data = await api.superOwner.getAuditLogs({
        action: auditActionFilter || undefined,
        resource_type: auditResourceFilter || undefined,
        limit: auditLimit,
        offset: auditOffset,
      });
      setAuditLogs(data);
    } catch (err) {
      console.error("Error fetching audit logs:", err);
    } finally {
      setAuditLoading(false);
    }
  }, [auditActionFilter, auditResourceFilter, auditLimit, auditOffset]);

  useEffect(() => {
    if (activeTab === "overview") fetchOverview();
    else if (activeTab === "ingestion") fetchBatches();
    else if (activeTab === "audit") fetchAuditLogs();
  }, [activeTab, fetchOverview, fetchBatches, fetchAuditLogs]);

  // Handle file select
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setSelectedFile(e.target.files[0]);
      setPreviewData(null);
      setIngestionResult(null);
      setIngestionError(null);
    }
  };

  // Generate Preview & AI Column Mappings
  const handleGeneratePreview = async () => {
    if (!selectedFile) return;
    setPreviewLoading(true);
    setIngestionError(null);
    try {
      const res = await api.superOwner.previewIngestion(selectedFile);
      setPreviewData(res);

      // Pre-seed column mappings from AI suggestions
      const initialMap: Record<string, string> = {};
      if (res.suggested_mappings) {
        res.suggested_mappings.forEach((m: any) => {
          if (m.target_field) {
            initialMap[m.source_column] = m.target_field;
          }
        });
      }
      setColumnMappings(initialMap);
    } catch (err: any) {
      setIngestionError(err.message || "Failed to generate file preview.");
    } finally {
      setPreviewLoading(false);
    }
  };

  // Execute Batch Ingestion
  const handleExecuteIngestion = async () => {
    if (!selectedFile || Object.keys(columnMappings).length === 0) return;
    setExecuteLoading(true);
    setIngestionError(null);
    try {
      const res = await api.superOwner.executeIngestion(
        selectedFile,
        columnMappings,
        conflictStrategy
      );
      setIngestionResult(res);
      setSelectedFile(null);
      setPreviewData(null);
      fetchBatches();
    } catch (err: any) {
      setIngestionError(err.message || "Ingestion execution failed.");
    } finally {
      setExecuteLoading(false);
    }
  };

  // Rollback Batch
  const handleRollback = async (batchId: string) => {
    if (!confirm(`Are you sure you want to rollback batch ${batchId}? This will reverse all properties and revert price history.`)) {
      return;
    }
    setRollbackLoading(batchId);
    try {
      await api.superOwner.rollbackIngestion(batchId);
      fetchBatches();
    } catch (err: any) {
      alert(`Rollback failed: ${err.message || "Unknown error"}`);
    } finally {
      setRollbackLoading(null);
    }
  };

  // Inspect Decrypted Transcript
  const handleInspectTranscript = async () => {
    if (!inspectSessionId.trim()) return;
    setPrivLoading(true);
    setPrivError(null);
    try {
      const res = await api.superOwner.getTranscript(inspectSessionId.trim());
      setPrivTranscript(res);
      setConfirmAuditModal(null);
    } catch (err: any) {
      setPrivError(err.message || "Failed to decrypt transcript.");
    } finally {
      setPrivLoading(false);
    }
  };

  // Inspect Audio Stream
  const handleInspectAudio = async () => {
    if (!inspectSessionId.trim()) return;
    setPrivLoading(true);
    setPrivError(null);
    try {
      const res = await api.superOwner.getAudio(inspectSessionId.trim());
      setPrivAudio(res);
      setConfirmAuditModal(null);
    } catch (err: any) {
      setPrivError(err.message || "Failed to access audio stream.");
    } finally {
      setPrivLoading(false);
    }
  };

  return (
    <ProtectedRoute allowedRoles={["super_owner"]}>
      <div className="min-h-screen bg-slate-50 text-slate-900 pb-16">
        {/* Top Header Banner */}
        <header className="border-b border-sky-100 bg-white/90 backdrop-blur-md sticky top-16 z-20 shadow-xs">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
            <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
              <div>
                <div className="flex items-center gap-2">
                  <ShieldAlert className="w-6 h-6 text-sky-600" />
                  <h1 className="text-xl font-bold tracking-tight text-slate-900">
                    Platform Super Owner Console
                  </h1>
                  <span className="px-2.5 py-0.5 text-xs font-semibold bg-sky-50 text-sky-700 border border-sky-200 rounded-full">
                    Privileged Master Tier
                  </span>
                </div>
                <p className="text-xs text-slate-500 mt-0.5">
                  Dynamic multi-format dataset ingestion, cryptographically audited access, and system governance.
                </p>
              </div>

              {/* Navigation Tabs */}
              <div className="flex items-center bg-slate-100 p-1 rounded-xl border border-slate-200/80 self-start md:self-auto">
                <button
                  onClick={() => setActiveTab("overview")}
                  className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
                    activeTab === "overview"
                      ? "bg-white text-sky-700 shadow-sm font-semibold"
                      : "text-slate-600 hover:text-slate-900 hover:bg-white/60"
                  }`}
                >
                  <Activity className="w-3.5 h-3.5" />
                  Overview
                </button>
                <button
                  onClick={() => setActiveTab("ingestion")}
                  className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
                    activeTab === "ingestion"
                      ? "bg-white text-sky-700 shadow-sm font-semibold"
                      : "text-slate-600 hover:text-slate-900 hover:bg-white/60"
                  }`}
                >
                  <Database className="w-3.5 h-3.5" />
                  Dataset Ingestion
                </button>
                <button
                  onClick={() => setActiveTab("privileged")}
                  className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
                    activeTab === "privileged"
                      ? "bg-white text-sky-700 shadow-sm font-semibold"
                      : "text-slate-600 hover:text-slate-900 hover:bg-white/60"
                  }`}
                >
                  <Lock className="w-3.5 h-3.5" />
                  Privileged Access
                </button>
                <button
                  onClick={() => setActiveTab("audit")}
                  className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
                    activeTab === "audit"
                      ? "bg-white text-sky-700 shadow-sm font-semibold"
                      : "text-slate-600 hover:text-slate-900 hover:bg-white/60"
                  }`}
                >
                  <ShieldAlert className="w-3.5 h-3.5" />
                  Audit Trail
                </button>
              </div>
            </div>
          </div>
        </header>

        {/* Main Content Area */}
        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-8">
          {/* ================================================================= */}
          {/* TAB 1: OVERVIEW METRICS                                           */}
          {/* ================================================================= */}
          {activeTab === "overview" && (
            <div className="space-y-6">
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <div className="p-5 rounded-2xl bg-white border border-sky-100 shadow-sm hover:shadow-md transition-shadow">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                      Ingestion Batches
                    </span>
                    <div className="w-9 h-9 rounded-xl bg-sky-50 text-sky-600 border border-sky-100 flex items-center justify-center">
                      <Database className="w-4 h-4" />
                    </div>
                  </div>
                  <div className="mt-3 text-3xl font-extrabold text-slate-900">
                    {metricsLoading ? "..." : metrics.totalBatches}
                  </div>
                  <p className="mt-1 text-xs text-slate-500">Total catalog import batches processed</p>
                </div>

                <div className="p-5 rounded-2xl bg-white border border-sky-100 shadow-sm hover:shadow-md transition-shadow">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                      Security Audit Events
                    </span>
                    <div className="w-9 h-9 rounded-xl bg-amber-50 text-amber-600 border border-amber-100 flex items-center justify-center">
                      <ShieldAlert className="w-4 h-4" />
                    </div>
                  </div>
                  <div className="mt-3 text-3xl font-extrabold text-slate-900">
                    {metricsLoading ? "..." : metrics.totalAuditLogs}
                  </div>
                  <p className="mt-1 text-xs text-slate-500">Non-repudiable audit events recorded</p>
                </div>

                <div className="p-5 rounded-2xl bg-white border border-sky-100 shadow-sm hover:shadow-md transition-shadow">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                      Voice Conversations
                    </span>
                    <div className="w-9 h-9 rounded-xl bg-emerald-50 text-emerald-600 border border-emerald-100 flex items-center justify-center">
                      <Activity className="w-4 h-4" />
                    </div>
                  </div>
                  <div className="mt-3 text-3xl font-extrabold text-slate-900">
                    {metricsLoading ? "..." : metrics.totalConversations}
                  </div>
                  <p className="mt-1 text-xs text-slate-500">Total AI voice sessions completed</p>
                </div>

                <div className="p-5 rounded-2xl bg-white border border-sky-100 shadow-sm hover:shadow-md transition-shadow">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                      Registered Customers
                    </span>
                    <div className="w-9 h-9 rounded-xl bg-indigo-50 text-indigo-600 border border-indigo-100 flex items-center justify-center">
                      <Layers className="w-4 h-4" />
                    </div>
                  </div>
                  <div className="mt-3 text-3xl font-extrabold text-slate-900">
                    {metricsLoading ? "..." : metrics.totalCustomers}
                  </div>
                  <p className="mt-1 text-xs text-slate-500">Active CRM customer profiles</p>
                </div>
              </div>

              {/* Security Status Box */}
              <div className="p-6 rounded-2xl bg-gradient-to-r from-sky-50 via-white to-sky-50/60 border border-sky-200/80 shadow-sm">
                <h3 className="text-sm font-semibold text-slate-900 flex items-center gap-2">
                  <Lock className="w-4 h-4 text-sky-600" />
                  Security & Immutability Architecture Status
                </h3>
                <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4 text-xs">
                  <div className="p-4 rounded-xl bg-white border border-sky-100 shadow-xs">
                    <div className="font-semibold text-slate-900">PostgreSQL Least-Privilege Roles</div>
                    <p className="mt-1 text-slate-600 leading-relaxed">
                      Application role restricted to <code className="text-sky-700 bg-sky-50 px-1 py-0.5 rounded font-mono text-[11px] border border-sky-100">INSERT, SELECT</code> on audit_logs. Updates & deletes blocked by database engine triggers.
                    </p>
                  </div>
                  <div className="p-4 rounded-xl bg-white border border-sky-100 shadow-xs">
                    <div className="font-semibold text-slate-900">AES-256-GCM Transcript Encryption</div>
                    <p className="mt-1 text-slate-600 leading-relaxed">
                      Every transcript is encrypted before database persistence. Zero plaintext stored. Decryption strictly gated to Super Owner with audit trail.
                    </p>
                  </div>
                  <div className="p-4 rounded-xl bg-white border border-sky-100 shadow-xs">
                    <div className="font-semibold text-slate-900">Argon2id Password Security</div>
                    <p className="mt-1 text-slate-600 leading-relaxed">
                      Argon2id configured with memory cost 65,536 KB, 3 iterations, and 4 threads to prevent GPU brute-force attacks.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ================================================================= */}
          {/* TAB 2: DATASET INGESTION SUITE                                    */}
          {/* ================================================================= */}
          {activeTab === "ingestion" && (
            <div className="space-y-8">
              {/* Ingestion Upload Card */}
              <div className="p-6 rounded-2xl bg-white border border-sky-100 shadow-sm">
                <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
                  <div>
                    <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
                      <FileSpreadsheet className="w-5 h-5 text-sky-600" />
                      Dynamic Dataset Ingestion
                    </h2>
                    <p className="text-xs text-slate-500 mt-1">
                      Upload catalog files in Excel (.xlsx, .xls), CSV (.csv), JSON (.json), or PDF (.pdf) format.
                    </p>
                  </div>

                  <div className="flex items-center gap-3">
                    <label className="cursor-pointer px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded-xl border border-slate-200 transition flex items-center gap-2">
                      <Upload className="w-4 h-4 text-sky-600" />
                      {selectedFile ? selectedFile.name : "Select File"}
                      <input
                        type="file"
                        accept=".csv,.xlsx,.xls,.json,.pdf"
                        onChange={handleFileChange}
                        className="hidden"
                      />
                    </label>

                    <button
                      onClick={handleGeneratePreview}
                      disabled={!selectedFile || previewLoading}
                      className="px-4 py-2 bg-sky-600 hover:bg-sky-700 disabled:opacity-50 text-white text-xs font-semibold rounded-xl transition flex items-center gap-2 shadow-sm"
                    >
                      {previewLoading ? (
                        <>
                          <RefreshCw className="w-4 h-4 animate-spin" />
                          Analyzing File...
                        </>
                      ) : (
                        <>
                          <Eye className="w-4 h-4" />
                          Generate AI Preview
                        </>
                      )}
                    </button>
                  </div>
                </div>

                {ingestionError && (
                  <div className="mt-4 p-3 rounded-xl bg-red-50 border border-red-200 text-xs text-red-700 flex items-center gap-2">
                    <AlertTriangle className="w-4 h-4 text-red-500 shrink-0" />
                    <span>{ingestionError}</span>
                  </div>
                )}
              </div>

              {/* Preview and AI Mapping Section */}
              {previewData && (
                <div className="p-6 rounded-2xl bg-white border border-sky-100 shadow-sm space-y-6">
                  <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between pb-4 border-b border-slate-100 gap-4">
                    <div>
                      <h3 className="text-sm font-bold text-slate-900">
                        AI-Assisted Column Mapping Proposal
                      </h3>
                      <p className="text-xs text-slate-500 mt-0.5">
                        File: <span className="font-semibold text-sky-700">{previewData.filename}</span> ({previewData.file_format}) • SHA-256: <span className="font-mono text-slate-400">{previewData.file_hash?.substring(0, 16)}...</span>
                      </p>
                    </div>

                    <div className="flex items-center gap-3">
                      <label className="text-xs font-medium text-slate-600">
                        Conflict Strategy:
                      </label>
                      <select
                        value={conflictStrategy}
                        onChange={(e) => setConflictStrategy(e.target.value as any)}
                        className="bg-white border border-slate-200 text-xs text-slate-800 rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-sky-500"
                      >
                        <option value="NEW_VERSION">New Version (Preserve History)</option>
                        <option value="OVERWRITE">Overwrite Existing Record</option>
                        <option value="SKIP">Skip Existing Records</option>
                      </select>
                    </div>
                  </div>

                  {/* Mapping Grid */}
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs border-collapse">
                      <thead>
                        <tr className="border-b border-sky-100 text-slate-700 font-semibold bg-sky-50/80">
                          <th className="py-2.5 px-3">Source Header</th>
                          <th className="py-2.5 px-3">AI Proposed Target Field</th>
                          <th className="py-2.5 px-3">Confidence Score</th>
                          <th className="py-2.5 px-3">Sample Values</th>
                          <th className="py-2.5 px-3">Confirmed Mapping</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100 font-sans">
                        {previewData.suggested_mappings?.map((m: any, idx: number) => {
                          const confPercent = Math.round(m.confidence_score * 100);
                          const isHigh = m.confidence_score >= 0.85;
                          const isMed = m.confidence_score >= 0.6;

                          return (
                            <tr key={idx} className="hover:bg-sky-50/30 transition text-slate-800">
                              <td className="py-2.5 px-3 font-semibold text-slate-900">
                                {m.source_column}
                              </td>
                              <td className="py-2.5 px-3 text-sky-700 font-mono">
                                {m.target_field || <span className="text-slate-400 italic">None</span>}
                              </td>
                              <td className="py-2.5 px-3">
                                <span
                                  className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                                    isHigh
                                      ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                                      : isMed
                                      ? "bg-amber-50 text-amber-700 border border-amber-200"
                                      : "bg-red-50 text-red-700 border border-red-200"
                                  }`}
                                >
                                  {confPercent}%
                                </span>
                              </td>
                              <td className="py-2.5 px-3 text-slate-500 max-w-xs truncate">
                                {m.sample_values?.slice(0, 3).join(", ") || "-"}
                              </td>
                              <td className="py-2.5 px-3">
                                <select
                                  value={columnMappings[m.source_column] || ""}
                                  onChange={(e) => {
                                    const val = e.target.value;
                                    setColumnMappings((prev) => {
                                      const next = { ...prev };
                                      if (val) next[m.source_column] = val;
                                      else delete next[m.source_column];
                                      return next;
                                    });
                                  }}
                                  className="bg-white border border-slate-200 rounded-md px-2 py-1 text-xs text-slate-800 focus:outline-none focus:border-sky-500"
                                >
                                  <option value="">-- Ignore Column --</option>
                                  {CANONICAL_TARGET_FIELDS.map((f) => (
                                    <option key={f.value} value={f.value}>
                                      {f.label} ({f.value})
                                    </option>
                                  ))}
                                </select>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>

                  {/* Sample Raw Preview Data */}
                  <div className="pt-4 border-t border-slate-100">
                    <h4 className="text-xs font-semibold text-slate-700 mb-2">
                      Raw Preview Rows (Showing {previewData.preview_rows?.length || 0} samples)
                    </h4>
                    <div className="max-h-56 overflow-auto border border-sky-100 rounded-xl bg-white">
                      <table className="w-full text-left text-[11px]">
                        <thead>
                          <tr className="border-b border-sky-100 text-slate-700 bg-sky-50/80">
                            {previewData.detected_headers?.map((h: string) => (
                              <th key={h} className="py-2 px-3 whitespace-nowrap">
                                {h}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100 font-mono text-slate-600">
                          {previewData.preview_rows?.slice(0, 10).map((row: any, rIdx: number) => (
                            <tr key={rIdx} className="hover:bg-slate-50/60">
                              {previewData.detected_headers?.map((h: string) => (
                                <td key={h} className="py-1.5 px-3 whitespace-nowrap">
                                  {String(row[h] ?? "")}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  {/* Ingestion Action */}
                  <div className="flex items-center justify-between pt-4 border-t border-slate-100">
                    <div className="text-xs text-slate-500">
                      {Object.keys(columnMappings).length} columns mapped for database ingestion.
                    </div>
                    <button
                      onClick={handleExecuteIngestion}
                      disabled={executeLoading || Object.keys(columnMappings).length === 0}
                      className="px-5 py-2.5 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white text-xs font-semibold rounded-xl transition flex items-center gap-2 shadow-md shadow-emerald-600/20"
                    >
                      {executeLoading ? (
                        <>
                          <RefreshCw className="w-4 h-4 animate-spin" />
                          Executing Normalized Ingestion...
                        </>
                      ) : (
                        <>
                          <CheckCircle className="w-4 h-4" />
                          Execute Batch Ingestion
                        </>
                      )}
                    </button>
                  </div>
                </div>
              )}

              {/* Execution Result Banner */}
              {ingestionResult && (
                <div className="p-5 rounded-2xl bg-emerald-50 border border-emerald-200">
                  <h4 className="text-sm font-bold text-emerald-800 flex items-center gap-2">
                    <CheckCircle className="w-4 h-4 text-emerald-600" />
                    Batch Ingestion Completed Successfully
                  </h4>
                  <div className="mt-3 grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs font-mono">
                    <div className="p-3 bg-white rounded-xl border border-emerald-100 shadow-xs">
                      <div className="text-slate-500">Total Rows</div>
                      <div className="text-lg font-bold text-slate-900">{ingestionResult.total_rows}</div>
                    </div>
                    <div className="p-3 bg-white rounded-xl border border-emerald-100 shadow-xs">
                      <div className="text-slate-500">Imported</div>
                      <div className="text-lg font-bold text-emerald-600">{ingestionResult.imported_rows}</div>
                    </div>
                    <div className="p-3 bg-white rounded-xl border border-emerald-100 shadow-xs">
                      <div className="text-slate-500">Skipped</div>
                      <div className="text-lg font-bold text-amber-600">{ingestionResult.skipped_rows}</div>
                    </div>
                    <div className="p-3 bg-white rounded-xl border border-emerald-100 shadow-xs">
                      <div className="text-slate-500">Failed</div>
                      <div className="text-lg font-bold text-red-600">{ingestionResult.failed_rows}</div>
                    </div>
                  </div>
                  <div className="mt-3 text-xs text-slate-600">
                    Batch ID: <span className="font-mono font-semibold text-sky-700">{ingestionResult.batch_id}</span>
                  </div>
                </div>
              )}

              {/* Ingestion Batch History & Rollback Table */}
              <div className="p-6 rounded-2xl bg-white border border-sky-100 shadow-sm space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-bold text-slate-900 flex items-center gap-2">
                      <Layers className="w-4 h-4 text-sky-600" />
                      Ingestion Provenance & Rollback History
                    </h3>
                    <p className="text-xs text-slate-500 mt-0.5">
                      Atomic rollback reverses inserted records in reverse dependency order and restores previous pricing.
                    </p>
                  </div>
                  <button
                    onClick={fetchBatches}
                    className="p-1.5 rounded-lg border border-slate-200 hover:bg-slate-50 text-slate-500 hover:text-slate-700 transition"
                    title="Refresh batches"
                  >
                    <RefreshCw className="w-4 h-4" />
                  </button>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="border-b border-sky-100 text-slate-700 font-semibold bg-sky-50/80">
                        <th className="py-2.5 px-3">Batch ID</th>
                        <th className="py-2.5 px-3">Status</th>
                        <th className="py-2.5 px-3">Total Rows</th>
                        <th className="py-2.5 px-3">Imported</th>
                        <th className="py-2.5 px-3">Skipped / Failed</th>
                        <th className="py-2.5 px-3">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 font-sans">
                      {batchesLoading ? (
                        <tr>
                          <td colSpan={6} className="text-center py-6 text-slate-500">
                            Loading batches...
                          </td>
                        </tr>
                      ) : batches.length === 0 ? (
                        <tr>
                          <td colSpan={6} className="text-center py-6 text-slate-500">
                            No ingestion batches found.
                          </td>
                        </tr>
                      ) : (
                        batches.map((b: any) => (
                          <tr key={b.batch_id} className="hover:bg-sky-50/30 transition text-slate-800">
                            <td className="py-2.5 px-3 font-mono text-slate-700">
                              {b.batch_id}
                            </td>
                            <td className="py-2.5 px-3">
                              <span
                                className={`px-2 py-0.5 rounded-full text-[10px] font-semibold ${
                                  b.status === "completed"
                                    ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                                    : b.status === "rolled_back"
                                    ? "bg-amber-50 text-amber-700 border border-amber-200"
                                    : "bg-red-50 text-red-700 border border-red-200"
                                }`}
                              >
                                {b.status}
                              </span>
                            </td>
                            <td className="py-2.5 px-3 font-semibold text-slate-900">
                              {b.total_rows}
                            </td>
                            <td className="py-2.5 px-3 text-emerald-700 font-semibold">
                              {b.imported_rows}
                            </td>
                            <td className="py-2.5 px-3 text-slate-500">
                              {b.skipped_rows} / {b.failed_rows}
                            </td>
                            <td className="py-2.5 px-3">
                              {b.can_rollback && b.status !== "rolled_back" ? (
                                <button
                                  onClick={() => handleRollback(b.batch_id)}
                                  disabled={rollbackLoading === b.batch_id}
                                  className="px-2.5 py-1 bg-red-50 hover:bg-red-100 border border-red-200 text-red-700 text-xs font-semibold rounded-lg transition flex items-center gap-1.5"
                                >
                                  {rollbackLoading === b.batch_id ? (
                                    <RefreshCw className="w-3 h-3 animate-spin" />
                                  ) : (
                                    <RotateCcw className="w-3 h-3" />
                                  )}
                                  Atomic Rollback
                                </button>
                              ) : (
                                <span className="text-slate-400 text-xs italic">
                                  {b.status === "rolled_back" ? "Reverted" : "N/A"}
                                </span>
                              )}
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* ================================================================= */}
          {/* TAB 3: PRIVILEGED TRANSCRIPT & AUDIO INSPECTION                   */}
          {/* ================================================================= */}
          {activeTab === "privileged" && (
            <div className="space-y-6">
              {/* Warning Notice Banner */}
              <div className="p-5 rounded-2xl bg-amber-50 border border-amber-200 flex items-start gap-4">
                <AlertOctagon className="w-6 h-6 text-amber-600 shrink-0 mt-0.5" />
                <div>
                  <h3 className="text-sm font-bold text-amber-900">
                    Mandatory Audited Security Perimeter
                  </h3>
                  <p className="mt-1 text-xs text-amber-800 leading-relaxed">
                    Customer conversations, transcripts, and audio recordings are strictly confidential. Every access attempt triggers an immutable system audit record logging your user ID, timestamp, client IP, and target conversation session.
                  </p>
                </div>
              </div>

              {/* Session Input Card */}
              <div className="p-6 rounded-2xl bg-white border border-sky-100 shadow-sm">
                <h3 className="text-sm font-bold text-slate-900 mb-2">
                  Inspect Target Conversation Session
                </h3>
                <div className="flex flex-col sm:flex-row gap-3">
                  <input
                    type="text"
                    placeholder="Enter Conversation Session ID (e.g. session-user-12345)"
                    value={inspectSessionId}
                    onChange={(e) => setInspectSessionId(e.target.value)}
                    className="flex-1 bg-white border border-slate-200 text-xs text-slate-900 rounded-xl px-3.5 py-2.5 focus:outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-100 font-mono"
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={() => setConfirmAuditModal("transcript")}
                      disabled={!inspectSessionId.trim() || privLoading}
                      className="px-4 py-2.5 bg-sky-600 hover:bg-sky-700 disabled:opacity-50 text-white text-xs font-semibold rounded-xl transition flex items-center gap-2 shadow-sm"
                    >
                      <FileText className="w-4 h-4 text-sky-100" />
                      Decrypt Transcript
                    </button>
                    <button
                      onClick={() => setConfirmAuditModal("audio")}
                      disabled={!inspectSessionId.trim() || privLoading}
                      className="px-4 py-2.5 bg-slate-100 hover:bg-slate-200 disabled:opacity-50 text-slate-700 text-xs font-semibold rounded-xl border border-slate-200 transition flex items-center gap-2"
                    >
                      <Volume2 className="w-4 h-4 text-emerald-600" />
                      Access Audio
                    </button>
                  </div>
                </div>

                {privError && (
                  <div className="mt-4 p-3 rounded-xl bg-red-50 border border-red-200 text-xs text-red-700">
                    {privError}
                  </div>
                )}
              </div>

              {/* Decrypted Transcript Display */}
              {privTranscript && (
                <div className="p-6 rounded-2xl bg-white border border-sky-100 shadow-sm space-y-4">
                  <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                    <div>
                      <h4 className="text-sm font-bold text-slate-900 flex items-center gap-2">
                        <FileText className="w-4 h-4 text-sky-600" />
                        Decrypted AES-256-GCM Conversation Transcript
                      </h4>
                      <div className="text-xs text-slate-500 mt-0.5">
                        Session: <span className="font-mono text-slate-700 font-semibold">{privTranscript.session_id}</span> • Duration: {privTranscript.duration_seconds}s
                      </div>
                    </div>
                    <span className="px-2.5 py-1 text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-full">
                      Audit Event Logged
                    </span>
                  </div>

                  <div className="p-4 bg-slate-50 rounded-xl border border-slate-200 font-mono text-xs text-slate-800 whitespace-pre-wrap leading-relaxed max-h-96 overflow-y-auto">
                    {privTranscript.decrypted_transcript || (
                      <span className="text-slate-400 italic">Empty transcript or no dialog recorded.</span>
                    )}
                  </div>
                </div>
              )}

              {/* Audio Stream Display */}
              {privAudio && (
                <div className="p-6 rounded-2xl bg-white border border-sky-100 shadow-sm space-y-4">
                  <div className="flex items-center justify-between border-b border-slate-100 pb-3">
                    <div>
                      <h4 className="text-sm font-bold text-slate-900 flex items-center gap-2">
                        <Volume2 className="w-4 h-4 text-emerald-600" />
                        Authorized Audio Stream Playback
                      </h4>
                      <div className="text-xs text-slate-500 mt-0.5">
                        Session: <span className="font-mono text-slate-700 font-semibold">{privAudio.session_id}</span> • Signed URL expires in {privAudio.expires_in_seconds}s
                      </div>
                    </div>
                    <span className="px-2.5 py-1 text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-full">
                      Audit Event Logged
                    </span>
                  </div>

                  <div className="p-4 bg-sky-50/60 rounded-xl border border-sky-200 flex flex-col sm:flex-row items-center justify-between gap-4">
                    <div className="text-xs text-slate-600 font-mono truncate max-w-md">
                      Stream Source: {privAudio.audio_stream_url}
                    </div>

                    <audio
                      ref={audioRef}
                      controls
                      src={privAudio.audio_stream_url}
                      className="w-full sm:w-80 h-9"
                    />
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ================================================================= */}
          {/* TAB 4: SYSTEM AUDIT LOG VIEWER                                    */}
          {/* ================================================================= */}
          {activeTab === "audit" && (
            <div className="space-y-6">
              {/* Filter Bar */}
              <div className="p-4 rounded-2xl bg-white border border-sky-100 shadow-sm flex flex-wrap items-center justify-between gap-4">
                <div className="flex flex-wrap items-center gap-3">
                  <div className="flex items-center gap-2">
                    <Filter className="w-4 h-4 text-slate-400" />
                    <span className="text-xs font-semibold text-slate-700">Filter By:</span>
                  </div>

                  <select
                    value={auditActionFilter}
                    onChange={(e) => {
                      setAuditActionFilter(e.target.value);
                      setAuditOffset(0);
                    }}
                    className="bg-white border border-slate-200 text-xs text-slate-800 rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-sky-500"
                  >
                    <option value="">All Actions</option>
                    <option value="ACCESS_PRIVATE_TRANSCRIPT">ACCESS_PRIVATE_TRANSCRIPT</option>
                    <option value="STREAM_PRIVATE_AUDIO">STREAM_PRIVATE_AUDIO</option>
                    <option value="EXECUTE_INGESTION">EXECUTE_INGESTION</option>
                    <option value="ROLLBACK_INGESTION">ROLLBACK_INGESTION</option>
                  </select>

                  <select
                    value={auditResourceFilter}
                    onChange={(e) => {
                      setAuditResourceFilter(e.target.value);
                      setAuditOffset(0);
                    }}
                    className="bg-white border border-slate-200 text-xs text-slate-800 rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-sky-500"
                  >
                    <option value="">All Resource Types</option>
                    <option value="conversation">Conversation</option>
                    <option value="ingestion_batch">Ingestion Batch</option>
                    <option value="user">User</option>
                  </select>
                </div>

                <button
                  onClick={fetchAuditLogs}
                  className="p-1.5 rounded-lg border border-slate-200 hover:bg-slate-50 text-slate-500 hover:text-slate-700 transition"
                  title="Refresh Audit Logs"
                >
                  <RefreshCw className="w-4 h-4" />
                </button>
              </div>

              {/* Audit Logs Table */}
              <div className="p-6 rounded-2xl bg-white border border-sky-100 shadow-sm space-y-4">
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead>
                      <tr className="border-b border-sky-100 text-slate-700 font-semibold bg-sky-50/80">
                        <th className="py-2.5 px-3">Timestamp (UTC)</th>
                        <th className="py-2.5 px-3">Action</th>
                        <th className="py-2.5 px-3">Role</th>
                        <th className="py-2.5 px-3">User ID</th>
                        <th className="py-2.5 px-3">Resource Target</th>
                        <th className="py-2.5 px-3">Client IP</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 font-sans">
                      {auditLoading ? (
                        <tr>
                          <td colSpan={6} className="text-center py-6 text-slate-500">
                            Loading audit records...
                          </td>
                        </tr>
                      ) : auditLogs.length === 0 ? (
                        <tr>
                          <td colSpan={6} className="text-center py-6 text-slate-500">
                            No audit records found matching criteria.
                          </td>
                        </tr>
                      ) : (
                        auditLogs.map((log: any) => (
                          <tr key={log.id} className="hover:bg-sky-50/30 transition text-slate-800">
                            <td className="py-2.5 px-3 font-mono text-slate-600">
                              {new Date(log.timestamp).toISOString()}
                            </td>
                            <td className="py-2.5 px-3">
                              <span
                                className={`px-2 py-0.5 rounded-full text-[10px] font-semibold font-mono ${
                                  log.action.includes("TRANSCRIPT") || log.action.includes("AUDIO")
                                    ? "bg-red-50 text-red-700 border border-red-200"
                                    : "bg-sky-50 text-sky-700 border border-sky-200"
                                }`}
                              >
                                {log.action}
                              </span>
                            </td>
                            <td className="py-2.5 px-3 font-semibold text-slate-700">
                              {log.user_role}
                            </td>
                            <td className="py-2.5 px-3 font-mono text-slate-500">
                              {log.user_id ? String(log.user_id).substring(0, 8) + "..." : "-"}
                            </td>
                            <td className="py-2.5 px-3 font-mono text-slate-700">
                              {log.resource_type}: {log.resource_id ? String(log.resource_id).substring(0, 14) + "..." : "-"}
                            </td>
                            <td className="py-2.5 px-3 font-mono text-slate-500">
                              {log.ip_address || "127.0.0.1"}
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>

                <Pagination
                  offset={auditOffset}
                  limit={auditLimit}
                  total={auditLogs.length === auditLimit ? auditOffset + auditLimit + 1 : auditOffset + auditLogs.length}
                  onPageChange={setAuditOffset}
                />
              </div>
            </div>
          )}
        </main>

        {/* Modal: Mandatory Audited Action Confirmation */}
        {confirmAuditModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-xs p-4">
            <div className="w-full max-w-md bg-white border border-sky-200 rounded-2xl p-6 shadow-2xl space-y-4">
              <div className="flex items-center gap-3 text-red-600">
                <AlertTriangle className="w-6 h-6 shrink-0" />
                <h3 className="text-base font-bold text-slate-900">
                  Privileged Access Confirmation
                </h3>
              </div>

              <p className="text-xs text-slate-600 leading-relaxed">
                You are about to access{" "}
                <span className="font-semibold text-red-600">
                  {confirmAuditModal === "transcript" ? "Decrypted Customer Transcript" : "Raw Customer Audio Stream"}
                </span>{" "}
                for session <code className="bg-sky-50 px-1 py-0.5 rounded font-mono text-sky-800 border border-sky-100">{inspectSessionId}</code>.
              </p>

              <div className="p-3 bg-amber-50 border border-amber-200 rounded-xl text-xs text-amber-800 leading-tight">
                ⚠️ Notice: This action cannot be revoked. A permanent, non-repudiable entry will be appended to the database audit trail.
              </div>

              <div className="flex items-center justify-end gap-3 pt-2">
                <button
                  onClick={() => setConfirmAuditModal(null)}
                  className="px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-semibold rounded-xl transition"
                >
                  Cancel
                </button>
                <button
                  onClick={
                    confirmAuditModal === "transcript"
                      ? handleInspectTranscript
                      : handleInspectAudio
                  }
                  className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white text-xs font-semibold rounded-xl transition shadow-sm"
                >
                  Confirm & Audit Access
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </ProtectedRoute>
  );
}
