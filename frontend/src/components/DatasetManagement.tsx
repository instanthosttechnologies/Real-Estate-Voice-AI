"use client";

import React, { useEffect, useState, useCallback } from "react";
import {
  Database,
  UploadCloud,
  CheckCircle2,
  AlertCircle,
  RefreshCw,
  RotateCcw,
  Sparkles,
  Layers,
  Table,
  Eye,
  X,
  Play,
  Check,
  Search,
  FileSpreadsheet,
  CheckSquare,
  Square,
  Sliders,
  ShieldCheck,
  Tag,
  Building,
  ArrowRight,
  Info,
} from "lucide-react";
import {
  api,
  DatasetSummaryItem,
  DatasetDetailResponse,
  DatasetInspectionResponse,
  DatasetPreviewQueryResponse,
} from "@/lib/api";

export function DatasetManagement() {
  // =========================================================================
  // Primary State
  // =========================================================================
  const [activeDataset, setActiveDataset] = useState<DatasetDetailResponse | null>(null);
  const [datasetsList, setDatasetsList] = useState<DatasetSummaryItem[]>([]);
  const [companies, setCompanies] = useState<{ id: string; name: string; slug: string }[]>([]);
  const [selectedCompanyId, setSelectedCompanyId] = useState<string | undefined>(undefined);
  const [loading, setLoading] = useState<boolean>(true);
  const [actionLoading, setActionLoading] = useState<boolean>(false);
  const [feedbackMessage, setFeedbackMessage] = useState<{ type: "success" | "error" | "info"; text: string } | null>(null);

  // =========================================================================
  // Wizard Modal State: Upload & Dynamic Column Discovery & Approval
  // =========================================================================
  const [wizardOpen, setWizardOpen] = useState<boolean>(false);
  const [wizardStep, setWizardStep] = useState<1 | 2 | 3 | 4>(1); // 1: Upload, 2: Inspect, 3: Configure/Approve, 4: Summary/Confirm
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [customDatasetName, setCustomDatasetName] = useState<string>("");
  const [inspectionData, setInspectionData] = useState<DatasetInspectionResponse | null>(null);
  const [selectedSheet, setSelectedSheet] = useState<string>("");

  // Approval Form State
  const [approvedFields, setApprovedFields] = useState<string[]>([]);
  const [displayIdentifier, setDisplayIdentifier] = useState<string>("");
  const [domainName, setDomainName] = useState<string>("");
  const [welcomeGreeting, setWelcomeGreeting] = useState<string>("");
  const [fieldLabels, setFieldLabels] = useState<Record<string, string>>({});

  // View Details Modal
  const [viewModalDataset, setViewModalDataset] = useState<DatasetDetailResponse | null>(null);

  // =========================================================================
  // Query Preview Panel State
  // =========================================================================
  const [previewQueryText, setPreviewQueryText] = useState<string>("");
  const [previewLoading, setPreviewLoading] = useState<boolean>(false);
  const [previewResult, setPreviewResult] = useState<DatasetPreviewQueryResponse | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  // =========================================================================
  // Data Fetching
  // =========================================================================
  const loadDatasets = useCallback(async () => {
    setLoading(true);
    setFeedbackMessage(null);
    try {
      const [activeRes, listRes, compRes] = await Promise.all([
        api.datasets.getActive(selectedCompanyId).catch(() => null),
        api.datasets.list(selectedCompanyId).catch(() => []),
        api.datasets.listCompanies().catch(() => []),
      ]);
      setActiveDataset(activeRes);
      setDatasetsList(listRes);
      setCompanies(compRes);
    } catch (err: any) {
      console.error("Failed to load dataset state:", err);
      setFeedbackMessage({ type: "error", text: err.message || "Failed to load datasets" });
    } finally {
      setLoading(false);
    }
  }, [selectedCompanyId]);

  useEffect(() => {
    loadDatasets();
  }, [loadDatasets]);

  // =========================================================================
  // Wizard Handlers
  // =========================================================================
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      const ext = file.name.split(".").pop()?.toLowerCase();
      if (!["xlsx", "xls", "csv"].includes(ext || "")) {
        setFeedbackMessage({ type: "error", text: "Please select an Excel (.xlsx, .xls) or CSV file." });
        return;
      }
      setSelectedFile(file);
      if (!customDatasetName) {
        setCustomDatasetName(file.name.replace(/\.[^/.]+$/, ""));
      }
    }
  };

  const handleStartInspection = async () => {
    if (!selectedFile) return;
    setActionLoading(true);
    setFeedbackMessage(null);
    try {
      const inspected = await api.datasets.inspect(selectedFile);
      setInspectionData(inspected);
      setSelectedSheet(inspected.primary_sheet);

      // Pre-select all columns by default for convenience
      const primaryCols = inspected.worksheets[inspected.primary_sheet]?.columns || [];
      const colNames = primaryCols.map((c) => c.column_name);
      setApprovedFields(colNames);

      // Pick first candidate identifier or first column as display identifier
      const candidateId = inspected.candidate_identifiers[0] || colNames[0] || "id";
      setDisplayIdentifier(candidateId);

      // Set default domain and greeting suggestions
      setDomainName(customDatasetName || "Universal Business Inventory");
      setWelcomeGreeting(
        `Welcome to our AI assistant! I am ready to answer your questions about our catalog.`
      );

      // Initialize field labels with clean human-readable names
      const initialLabels: Record<string, string> = {};
      colNames.forEach((col) => {
        initialLabels[col] = col
          .replace(/[_-]/g, " ")
          .replace(/\b\w/g, (l) => l.toUpperCase());
      });
      setFieldLabels(initialLabels);

      setWizardStep(2);
    } catch (err: any) {
      console.error("Inspection error:", err);
      setFeedbackMessage({ type: "error", text: err.message || "Failed to inspect workbook columns." });
    } finally {
      setActionLoading(false);
    }
  };

  const toggleFieldApproval = (colName: string) => {
    setApprovedFields((prev) => {
      if (prev.includes(colName)) {
        const next = prev.filter((f) => f !== colName);
        if (displayIdentifier === colName && next.length > 0) {
          setDisplayIdentifier(next[0]);
        }
        return next;
      } else {
        return [...prev, colName];
      }
    });
  };

  const handleSelectAllFields = () => {
    if (!inspectionData || !selectedSheet) return;
    const allCols = inspectionData.worksheets[selectedSheet]?.columns.map((c) => c.column_name) || [];
    setApprovedFields(allCols);
    if (!approvedFields.includes(displayIdentifier) && allCols.length > 0) {
      setDisplayIdentifier(allCols[0]);
    }
  };

  const handleDeselectAllFields = () => {
    setApprovedFields([]);
  };

  const handleConfirmAndUpload = async (autoActivate: boolean) => {
    if (!selectedFile || approvedFields.length === 0 || !displayIdentifier) {
      setFeedbackMessage({
        type: "error",
        text: "Please approve at least one field and select a valid primary display identifier.",
      });
      return;
    }

    setActionLoading(true);
    setFeedbackMessage(null);
    try {
      // Step A: Upload & Import file (creates dataset in pending_approval status)
      const uploaded = await api.datasets.upload(
        selectedFile,
        customDatasetName.trim() || undefined,
        selectedCompanyId
      );

      // Step B: Approve schema with whitelist
      const approved = await api.datasets.approve(
        uploaded.id,
        {
          approved_fields: approvedFields,
          display_identifier: displayIdentifier,
          field_labels: fieldLabels,
          domain_name: domainName.trim() || undefined,
          welcome_greeting: welcomeGreeting.trim() || undefined,
        },
        selectedCompanyId
      );

      // Step C: Activate if requested
      if (autoActivate) {
        await api.datasets.activate(approved.id, selectedCompanyId);
        setFeedbackMessage({
          type: "success",
          text: `Dataset "${approved.name}" v${approved.version} was uploaded, approved, and activated successfully!`,
        });
      } else {
        setFeedbackMessage({
          type: "success",
          text: `Dataset "${approved.name}" v${approved.version} was saved and approved. You can activate it when ready.`,
        });
      }

      // Reset wizard
      setWizardOpen(false);
      setWizardStep(1);
      setSelectedFile(null);
      setInspectionData(null);
      loadDatasets();
    } catch (err: any) {
      console.error("Save & Activate error:", err);
      setFeedbackMessage({ type: "error", text: err.message || "Operation failed." });
    } finally {
      setActionLoading(false);
    }
  };

  const handleActivateDataset = async (datasetId: string) => {
    if (!confirm("Activate this dataset version for AI voice and search queries?")) return;
    setActionLoading(true);
    setFeedbackMessage(null);
    try {
      const activated = await api.datasets.activate(datasetId, selectedCompanyId);
      setFeedbackMessage({
        type: "success",
        text: `Dataset "${activated.name}" v${activated.version} is now active!`,
      });
      loadDatasets();
    } catch (err: any) {
      console.error("Activation error:", err);
      setFeedbackMessage({ type: "error", text: err.message || "Failed to activate dataset." });
    } finally {
      setActionLoading(false);
    }
  };

  const handleRollback = async (datasetId: string) => {
    if (!confirm("Revert to the previous approved dataset version?")) return;
    setActionLoading(true);
    setFeedbackMessage(null);
    try {
      const res = await api.datasets.rollback(datasetId, selectedCompanyId);
      setFeedbackMessage({
        type: "success",
        text: res.reverted_to
          ? `Successfully rolled back to "${res.reverted_to.name}" v${res.reverted_to.version}.`
          : `Active dataset was rolled back successfully.`,
      });
      loadDatasets();
    } catch (err: any) {
      console.error("Rollback error:", err);
      setFeedbackMessage({ type: "error", text: err.message || "Failed to rollback dataset." });
    } finally {
      setActionLoading(false);
    }
  };

  const handleRunPreviewQuery = async () => {
    if (!previewQueryText.trim()) return;
    setPreviewLoading(true);
    setPreviewError(null);
    try {
      const res = await api.datasets.previewQuery(
        {
          query_text: previewQueryText.trim(),
          limit: 5,
        },
        selectedCompanyId
      );
      setPreviewResult(res);
    } catch (err: any) {
      console.error("Preview query error:", err);
      setPreviewError(err.message || "Failed to execute preview query.");
      setPreviewResult(null);
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleOpenViewDetails = async (id: string) => {
    try {
      const detail = await api.datasets.getById(id, selectedCompanyId);
      setViewModalDataset(detail);
    } catch (err: any) {
      console.error("Failed to load dataset details:", err);
    }
  };

  return (
    <div className="space-y-8">
      {/* Top Controls & Tenant Company Selector */}
      <div className="bg-white border border-sky-100 rounded-2xl p-5 shadow-sm flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center space-x-2">
            <Database className="w-5 h-5 text-sky-600" />
            <h2 className="text-lg font-bold text-slate-900">AI Knowledge & Universal Datasets</h2>
          </div>
          <p className="text-xs text-slate-600 mt-1">
            Universal schema-agnostic ingestion. Inspect column metadata, approve permitted fields, and activate versioned datasets.
          </p>
        </div>

        <div className="flex items-center space-x-3 w-full sm:w-auto">
          {companies.length > 0 && (
            <div className="flex items-center space-x-2 text-xs">
              <Building className="w-4 h-4 text-slate-500" />
              <select
                value={selectedCompanyId || ""}
                onChange={(e) => setSelectedCompanyId(e.target.value || undefined)}
                className="px-3 py-1.5 border border-sky-200 rounded-lg text-slate-800 bg-white shadow-xs focus:ring-2 focus:ring-sky-500 focus:outline-hidden"
              >
                <option value="">Platform / All Tenants</option>
                {companies.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </div>
          )}

          <button
            onClick={() => {
              setWizardStep(1);
              setSelectedFile(null);
              setInspectionData(null);
              setWizardOpen(true);
            }}
            className="inline-flex items-center space-x-2 px-4 py-2 rounded-xl bg-sky-600 hover:bg-sky-700 text-white text-xs font-semibold shadow-xs transition-colors"
          >
            <UploadCloud className="w-4 h-4" />
            <span>Upload New Dataset</span>
          </button>

          <button
            onClick={loadDatasets}
            disabled={loading}
            className="p-2 border border-sky-200 hover:bg-sky-50 text-slate-700 rounded-xl transition-colors"
            title="Refresh Datasets"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin text-sky-600" : ""}`} />
          </button>
        </div>
      </div>

      {/* Global Feedback Alert */}
      {feedbackMessage && (
        <div
          className={`p-4 rounded-xl text-sm flex items-start space-x-3 border ${
            feedbackMessage.type === "success"
              ? "bg-emerald-50 text-emerald-800 border-emerald-200"
              : feedbackMessage.type === "error"
              ? "bg-rose-50 text-rose-800 border-rose-200"
              : "bg-sky-50 text-sky-800 border-sky-200"
          }`}
        >
          {feedbackMessage.type === "success" ? (
            <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" />
          ) : feedbackMessage.type === "error" ? (
            <AlertCircle className="w-5 h-5 text-rose-600 shrink-0 mt-0.5" />
          ) : (
            <Info className="w-5 h-5 text-sky-600 shrink-0 mt-0.5" />
          )}
          <div className="flex-1">
            <span className="font-semibold">{feedbackMessage.text}</span>
          </div>
          <button
            onClick={() => setFeedbackMessage(null)}
            className="text-slate-400 hover:text-slate-600 p-1"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* ===================================================================== */}
      {/* SECTION 1: ACTIVE DATASET CARD                                        */}
      {/* ===================================================================== */}
      <div className="bg-white border border-sky-100 rounded-2xl p-6 shadow-sm">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between pb-4 border-b border-sky-100 gap-3">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-sky-50 border border-sky-200 flex items-center justify-center text-sky-700">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <h3 className="text-lg font-extrabold text-slate-900">
                  {activeDataset?.name || "No Active Dataset"}
                </h3>
                {activeDataset && (
                  <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-sky-100 text-sky-700 border border-sky-200">
                    v{activeDataset.version}
                  </span>
                )}
                <span
                  className={`px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                    activeDataset?.is_active
                      ? "bg-emerald-100 text-emerald-800 border border-emerald-200"
                      : "bg-slate-100 text-slate-600 border border-slate-200"
                  }`}
                >
                  {activeDataset?.is_active ? "Live & Active" : "Inactive"}
                </span>
              </div>
              <p className="text-xs text-slate-600 mt-0.5">
                Domain: <strong className="text-slate-800">{activeDataset?.domain_name || "General Business / Properties"}</strong> • 
                File: <span className="font-mono text-slate-700">{activeDataset?.filename || "None"}</span>
              </p>
            </div>
          </div>

          {activeDataset && (
            <div className="flex items-center space-x-2">
              <button
                onClick={() => handleRollback(activeDataset.id)}
                disabled={actionLoading}
                className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg border border-slate-200 hover:bg-slate-50 text-slate-700 text-xs font-semibold transition-colors"
                title="Roll back to previous active dataset version"
              >
                <RotateCcw className="w-3.5 h-3.5 text-slate-500" />
                <span>Rollback</span>
              </button>

              <button
                onClick={() => handleOpenViewDetails(activeDataset.id)}
                className="inline-flex items-center space-x-1.5 px-3 py-1.5 rounded-lg border border-sky-200 bg-sky-50 hover:bg-sky-100 text-sky-700 text-xs font-semibold transition-colors"
              >
                <Eye className="w-3.5 h-3.5" />
                <span>View Schema</span>
              </button>
            </div>
          )}
        </div>

        {activeDataset ? (
          <div className="mt-5 grid grid-cols-1 md:grid-cols-3 gap-5">
            {/* Metric 1 */}
            <div className="p-4 rounded-xl bg-sky-50/50 border border-sky-100">
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider block">
                Total Records
              </span>
              <span className="text-2xl font-black text-slate-900 mt-1 block">
                {activeDataset.total_rows.toLocaleString()}
              </span>
              <span className="text-xs text-slate-600 mt-0.5 block">
                Sheet: <strong className="text-slate-800">{activeDataset.primary_sheet}</strong>
              </span>
            </div>

            {/* Metric 2 */}
            <div className="p-4 rounded-xl bg-sky-50/50 border border-sky-100">
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider block">
                Approved Allowed Fields
              </span>
              <span className="text-2xl font-black text-sky-700 mt-1 block">
                {activeDataset.approved_fields ? activeDataset.approved_fields.length : "All (Legacy)"}
              </span>
              <span className="text-xs text-slate-600 mt-0.5 block">
                Key Identifier: <strong className="text-slate-800">{activeDataset.display_identifier || "Default"}</strong>
              </span>
            </div>

            {/* Metric 3 */}
            <div className="p-4 rounded-xl bg-sky-50/50 border border-sky-100">
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider block">
                Active Timestamp
              </span>
              <span className="text-sm font-bold text-slate-800 mt-1 block">
                {activeDataset.activated_at
                  ? new Date(activeDataset.activated_at).toLocaleString()
                  : new Date(activeDataset.created_at).toLocaleString()}
              </span>
              <span className="text-xs text-slate-600 mt-0.5 block truncate">
                Hash: <span className="font-mono">{activeDataset.file_hash?.substring(0, 12)}...</span>
              </span>
            </div>

            {/* Spoken Greeting Card */}
            <div className="md:col-span-3 p-4 rounded-xl bg-slate-50 border border-slate-200 text-xs">
              <div className="flex items-center space-x-2 text-slate-700 font-semibold mb-1">
                <Tag className="w-3.5 h-3.5 text-sky-600" />
                <span>AI Voice Opening Greeting:</span>
              </div>
              <p className="text-slate-800 italic bg-white p-3 rounded-lg border border-slate-200">
                "{activeDataset.welcome_greeting || "Welcome! How can I assist you today?"}"
              </p>
            </div>

            {/* Approved Field Badges */}
            {activeDataset.approved_fields && (
              <div className="md:col-span-3">
                <span className="text-xs font-semibold text-slate-600 block mb-2">
                  Permitted Voice & Search Columns:
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {activeDataset.approved_fields.map((f) => (
                    <span
                      key={f}
                      className={`px-2.5 py-1 rounded-lg text-xs font-medium border ${
                        f === activeDataset.display_identifier
                          ? "bg-amber-50 text-amber-800 border-amber-300 font-bold"
                          : "bg-white text-slate-700 border-sky-200"
                      }`}
                    >
                      {f === activeDataset.display_identifier && "★ "}
                      {activeDataset.field_labels?.[f] ? `${activeDataset.field_labels[f]} (${f})` : f}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="p-8 text-center text-slate-500">
            <Database className="w-10 h-10 text-slate-300 mx-auto mb-2" />
            <p className="text-sm font-medium">No active dataset is currently configured.</p>
            <p className="text-xs text-slate-400 mt-1">Upload a business Excel or CSV dataset to activate AI knowledge.</p>
          </div>
        )}
      </div>

      {/* ===================================================================== */}
      {/* SECTION 2: QUERY PREVIEW PANEL (TEST KNOWLEDGE WITHOUT AWS BEDROCK)   */}
      {/* ===================================================================== */}
      <div className="bg-white border border-sky-100 rounded-2xl p-6 shadow-sm">
        <div className="flex items-center justify-between pb-4 border-b border-sky-100">
          <div className="flex items-center space-x-2">
            <Play className="w-5 h-5 text-sky-600" />
            <h3 className="text-md font-bold text-slate-900">Query Preview & Grounding Sandbox</h3>
          </div>
          <span className="text-xs font-semibold px-2.5 py-1 rounded-lg bg-sky-50 text-sky-700 border border-sky-200">
            Zero Bedrock Calls • Offline Universal Engine
          </span>
        </div>

        <p className="text-xs text-slate-600 mt-2 mb-4">
          Test sample customer queries against the approved active dataset. Verify that response grounding matches your business schema and unapproved confidential fields are strictly absent.
        </p>

        <div className="flex flex-col sm:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-3" />
            <input
              type="text"
              value={previewQueryText}
              onChange={(e) => setPreviewQueryText(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleRunPreviewQuery()}
              placeholder="e.g. 'Show me 3 BHK in Gurugram under 1.5 Cr', 'Red SUV under 25 Lakhs', '256GB storage'"
              className="w-full pl-9 pr-4 py-2 text-sm border border-sky-200 rounded-xl focus:ring-2 focus:ring-sky-500 focus:outline-hidden text-slate-800"
            />
          </div>

          <button
            onClick={handleRunPreviewQuery}
            disabled={previewLoading || !previewQueryText.trim()}
            className="px-5 py-2 rounded-xl bg-sky-600 hover:bg-sky-700 disabled:opacity-50 text-white text-xs font-semibold shadow-xs flex items-center justify-center space-x-2 transition-colors"
          >
            {previewLoading ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" />
                <span>Querying...</span>
              </>
            ) : (
              <>
                <Play className="w-4 h-4" />
                <span>Test Query</span>
              </>
            )}
          </button>
        </div>

        {/* Query Preview Error */}
        {previewError && (
          <div className="mt-4 p-3 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-800">
            <strong>Error:</strong> {previewError}
          </div>
        )}

        {/* Query Preview Results */}
        {previewResult && (
          <div className="mt-5 space-y-4">
            <div className="p-4 rounded-xl bg-sky-50/70 border border-sky-200">
              <span className="text-xs font-bold text-sky-900 uppercase tracking-wider block mb-1">
                Grounded AI Voice Response:
              </span>
              <p className="text-sm font-semibold text-slate-800">{previewResult.voice_grounding}</p>
              <div className="mt-2 flex items-center space-x-3 text-xs text-slate-600">
                <span>Dataset: <strong>{previewResult.dataset_name} v{previewResult.dataset_version}</strong></span>
                <span>•</span>
                <span>Matches Found: <strong>{previewResult.total_matches}</strong></span>
                <span>•</span>
                <span className="text-emerald-700 font-medium">✓ Unapproved fields strictly omitted</span>
              </div>
            </div>

            {/* Matched Records Table / Cards */}
            {previewResult.records.length > 0 && (
              <div className="space-y-3">
                <span className="text-xs font-bold text-slate-700 uppercase tracking-wider block">
                  Top Grounded Records:
                </span>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {previewResult.records.map((rec) => (
                    <div
                      key={rec.id}
                      className="p-3.5 rounded-xl border border-sky-100 bg-white shadow-xs hover:border-sky-300 transition-all text-xs space-y-2"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-slate-900">{rec.display_title}</span>
                        <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-sky-50 text-sky-700 border border-sky-200">
                          {rec.sheet_name}
                        </span>
                      </div>
                      <p className="text-slate-600 italic bg-slate-50 p-2 rounded border border-slate-100">
                        {rec.voice_summary}
                      </p>
                      <div>
                        <span className="text-[11px] font-bold text-slate-500 block mb-1">
                          Approved Attributes:
                        </span>
                        <div className="flex flex-wrap gap-1">
                          {Object.entries(rec.attributes).map(([k, v]) => (
                            <span
                              key={k}
                              className="px-2 py-0.5 rounded bg-sky-50/60 text-slate-700 border border-sky-100 text-[11px]"
                            >
                              <strong>{k}:</strong> {String(v)}
                            </span>
                          ))}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ===================================================================== */}
      {/* SECTION 3: VERSION HISTORY TABLE                                      */}
      {/* ===================================================================== */}
      <div className="bg-white border border-sky-100 rounded-2xl shadow-sm overflow-hidden">
        <div className="p-5 border-b border-sky-100 flex items-center justify-between">
          <div>
            <h3 className="text-md font-bold text-slate-900">Dataset Version History</h3>
            <p className="text-xs text-slate-600 mt-0.5">
              Auditable list of all uploaded and versioned datasets within your organization.
            </p>
          </div>
          <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-sky-100 text-sky-800">
            {datasetsList.length} Versions
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-sky-100 text-xs">
            <thead className="bg-sky-50/60">
              <tr>
                <th className="px-4 py-3 text-left font-bold text-slate-700 uppercase tracking-wider">
                  Version
                </th>
                <th className="px-4 py-3 text-left font-bold text-slate-700 uppercase tracking-wider">
                  Dataset Name & Domain
                </th>
                <th className="px-4 py-3 text-left font-bold text-slate-700 uppercase tracking-wider">
                  Status
                </th>
                <th className="px-4 py-3 text-left font-bold text-slate-700 uppercase tracking-wider">
                  Rows
                </th>
                <th className="px-4 py-3 text-left font-bold text-slate-700 uppercase tracking-wider">
                  Approved Fields
                </th>
                <th className="px-4 py-3 text-left font-bold text-slate-700 uppercase tracking-wider">
                  Created At
                </th>
                <th className="px-4 py-3 text-right font-bold text-slate-700 uppercase tracking-wider">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-sky-100 bg-white">
              {datasetsList.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-slate-500">
                    No dataset history records found.
                  </td>
                </tr>
              ) : (
                datasetsList.map((d) => (
                  <tr key={d.id} className="hover:bg-sky-50/30 transition-colors">
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className="font-extrabold text-slate-900 px-2 py-0.5 rounded bg-sky-100/70 border border-sky-200">
                        v{d.version}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="font-bold text-slate-900">{d.name}</div>
                      <div className="text-[11px] text-slate-500">
                        {d.domain_name || "Properties / General"} • {d.filename}
                      </div>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span
                        className={`px-2 py-0.5 rounded-full font-bold uppercase text-[10px] ${
                          d.is_active
                            ? "bg-emerald-100 text-emerald-800 border border-emerald-200"
                            : d.status === "approved"
                            ? "bg-sky-100 text-sky-800 border border-sky-200"
                            : d.status === "pending_approval"
                            ? "bg-amber-100 text-amber-800 border border-amber-200"
                            : "bg-slate-100 text-slate-600 border border-slate-200"
                        }`}
                      >
                        {d.is_active ? "Active" : d.status.replace("_", " ")}
                      </span>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap font-medium text-slate-700">
                      {d.total_rows.toLocaleString()}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-slate-600">
                      {d.approved_fields ? `${d.approved_fields.length} Approved` : "All (Legacy)"}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-slate-500">
                      {new Date(d.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-right space-x-2">
                      <button
                        onClick={() => handleOpenViewDetails(d.id)}
                        className="text-sky-600 hover:text-sky-800 font-semibold"
                      >
                        Inspect
                      </button>
                      {!d.is_active && d.status === "approved" && (
                        <button
                          onClick={() => handleActivateDataset(d.id)}
                          className="text-emerald-600 hover:text-emerald-800 font-semibold"
                        >
                          Activate
                        </button>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ===================================================================== */}
      {/* MODAL: UPLOAD & FIELD APPROVAL WIZARD                                  */}
      {/* ===================================================================== */}
      {wizardOpen && (
        <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white border border-sky-200 rounded-3xl max-w-4xl w-full p-6 sm:p-8 shadow-xl max-h-[90vh] overflow-y-auto space-y-6">
            {/* Modal Header */}
            <div className="flex items-center justify-between pb-4 border-b border-sky-100">
              <div className="flex items-center space-x-3">
                <div className="w-10 h-10 rounded-xl bg-sky-50 border border-sky-200 flex items-center justify-center text-sky-700">
                  <UploadCloud className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-lg font-bold text-slate-900">
                    Universal Dynamic Dataset Ingestion Wizard
                  </h3>
                  <p className="text-xs text-slate-600">
                    Step {wizardStep} of 3 • Inspect columns, designate allowed AI fields, and activate safely.
                  </p>
                </div>
              </div>

              <button
                onClick={() => setWizardOpen(false)}
                className="p-2 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* WIZARD STEP 1: FILE SELECTION */}
            {wizardStep === 1 && (
              <div className="space-y-6">
                <div className="border-2 border-dashed border-sky-200 rounded-2xl p-8 text-center hover:border-sky-400 transition-colors bg-sky-50/20">
                  <FileSpreadsheet className="w-12 h-12 text-sky-600 mx-auto mb-3" />
                  <label
                    htmlFor="file-upload"
                    className="cursor-pointer text-sm font-bold text-sky-700 hover:text-sky-800"
                  >
                    Click to select an Excel (.xlsx, .xls) or CSV file
                    <input
                      id="file-upload"
                      type="file"
                      accept=".xlsx,.xls,.csv"
                      onChange={handleFileChange}
                      className="hidden"
                    />
                  </label>
                  <p className="text-xs text-slate-500 mt-1">
                    Universal format support: Real Estate, Automobile, Electronics, or any tabular data.
                  </p>
                  {selectedFile && (
                    <div className="mt-4 inline-flex items-center space-x-2 px-3 py-1.5 rounded-lg bg-emerald-50 border border-emerald-200 text-xs font-semibold text-emerald-800">
                      <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                      <span>{selectedFile.name} ({(selectedFile.size / 1024).toFixed(1)} KB)</span>
                    </div>
                  )}
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs font-bold text-slate-700 block mb-1">
                      Dataset Name (Optional)
                    </label>
                    <input
                      type="text"
                      value={customDatasetName}
                      onChange={(e) => setCustomDatasetName(e.target.value)}
                      placeholder="e.g. Electric Vehicle Fleet 2026"
                      className="w-full px-3 py-2 text-xs border border-sky-200 rounded-xl focus:ring-2 focus:ring-sky-500 text-slate-800"
                    />
                  </div>

                  {companies.length > 0 && (
                    <div>
                      <label className="text-xs font-bold text-slate-700 block mb-1">
                        Assign to Tenant Company
                      </label>
                      <select
                        value={selectedCompanyId || ""}
                        onChange={(e) => setSelectedCompanyId(e.target.value || undefined)}
                        className="w-full px-3 py-2 text-xs border border-sky-200 rounded-xl focus:ring-2 focus:ring-sky-500 text-slate-800 bg-white"
                      >
                        <option value="">Platform Default</option>
                        {companies.map((c) => (
                          <option key={c.id} value={c.id}>
                            {c.name}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>

                <div className="flex justify-end space-x-3 pt-4 border-t border-sky-100">
                  <button
                    onClick={() => setWizardOpen(false)}
                    className="px-4 py-2 rounded-xl border border-slate-200 text-slate-700 text-xs font-semibold hover:bg-slate-50"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={handleStartInspection}
                    disabled={!selectedFile || actionLoading}
                    className="px-5 py-2 rounded-xl bg-sky-600 hover:bg-sky-700 disabled:opacity-50 text-white text-xs font-semibold shadow-xs flex items-center space-x-2"
                  >
                    {actionLoading ? (
                      <>
                        <RefreshCw className="w-4 h-4 animate-spin" />
                        <span>Inspecting Workbook...</span>
                      </>
                    ) : (
                      <>
                        <span>Inspect Columns</span>
                        <ArrowRight className="w-4 h-4" />
                      </>
                    )}
                  </button>
                </div>
              </div>
            )}

            {/* WIZARD STEP 2 & 3: DYNAMIC COLUMN DISCOVERY & ADMIN FIELD APPROVAL */}
            {wizardStep === 2 && inspectionData && (
              <div className="space-y-6">
                {/* Discovery Summary Banner */}
                <div className="p-4 rounded-2xl bg-sky-50/70 border border-sky-200 flex flex-wrap items-center justify-between gap-3 text-xs">
                  <div>
                    <span className="font-bold text-slate-900 block">
                      Discovered {inspectionData.total_primary_rows} records across {inspectionData.total_worksheets} sheet(s)
                    </span>
                    <span className="text-slate-600">
                      Primary Worksheet: <strong>{inspectionData.primary_sheet}</strong>
                    </span>
                  </div>

                  <div className="flex items-center space-x-2">
                    <button
                      onClick={handleSelectAllFields}
                      className="px-2.5 py-1 rounded bg-white border border-sky-200 text-sky-700 font-semibold hover:bg-sky-50"
                    >
                      Select All
                    </button>
                    <button
                      onClick={handleDeselectAllFields}
                      className="px-2.5 py-1 rounded bg-white border border-slate-200 text-slate-600 font-semibold hover:bg-slate-50"
                    >
                      Deselect All
                    </button>
                  </div>
                </div>

                {/* Domain & Spoken Voice Settings */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 p-4 rounded-2xl bg-slate-50 border border-slate-200">
                  <div>
                    <label className="text-xs font-bold text-slate-800 block mb-1">
                      Business / Domain Name *
                    </label>
                    <input
                      type="text"
                      value={domainName}
                      onChange={(e) => setDomainName(e.target.value)}
                      placeholder="e.g. Automobile Inventory, Consumer Electronics, Luxury Real Estate"
                      className="w-full px-3 py-2 text-xs border border-slate-300 rounded-xl focus:ring-2 focus:ring-sky-500 bg-white text-slate-900"
                    />
                  </div>

                  <div>
                    <label className="text-xs font-bold text-slate-800 block mb-1">
                      Primary Display Identifier (Title) *
                    </label>
                    <select
                      value={displayIdentifier}
                      onChange={(e) => setDisplayIdentifier(e.target.value)}
                      className="w-full px-3 py-2 text-xs border border-slate-300 rounded-xl focus:ring-2 focus:ring-sky-500 bg-white text-slate-900"
                    >
                      {approvedFields.map((f) => (
                        <option key={f} value={f}>
                          {fieldLabels[f] || f} ({f})
                        </option>
                      ))}
                    </select>
                  </div>

                  <div className="sm:col-span-2">
                    <label className="text-xs font-bold text-slate-800 block mb-1">
                      AI Opening Spoken Greeting
                    </label>
                    <textarea
                      rows={2}
                      value={welcomeGreeting}
                      onChange={(e) => setWelcomeGreeting(e.target.value)}
                      placeholder="e.g. Welcome! I can help you find products, compare specifications, and review prices. How can I help you today?"
                      className="w-full px-3 py-2 text-xs border border-slate-300 rounded-xl focus:ring-2 focus:ring-sky-500 bg-white text-slate-900"
                    />
                  </div>
                </div>

                {/* Column Table with Checkboxes */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-bold text-slate-800 uppercase tracking-wider">
                      Discovered Columns ({inspectionData.worksheets[selectedSheet]?.columns.length || 0}):
                    </span>
                    <span className="text-xs text-slate-500">
                      Check fields permitted for AI voice. Unchecked columns remain confidential.
                    </span>
                  </div>

                  <div className="border border-sky-100 rounded-2xl overflow-hidden max-h-72 overflow-y-auto">
                    <table className="min-w-full divide-y divide-sky-100 text-xs">
                      <thead className="bg-sky-50/60 sticky top-0">
                        <tr>
                          <th className="px-3 py-2 text-left font-bold text-slate-700">Allow AI</th>
                          <th className="px-3 py-2 text-left font-bold text-slate-700">Column Name</th>
                          <th className="px-3 py-2 text-left font-bold text-slate-700">Type</th>
                          <th className="px-3 py-2 text-left font-bold text-slate-700">Spoken Label</th>
                          <th className="px-3 py-2 text-left font-bold text-slate-700">Sample Values</th>
                          <th className="px-3 py-2 text-left font-bold text-slate-700">Nulls / Unique</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-sky-100 bg-white">
                        {inspectionData.worksheets[selectedSheet]?.columns.map((col) => {
                          const isApproved = approvedFields.includes(col.column_name);
                          return (
                            <tr
                              key={col.column_name}
                              className={`hover:bg-sky-50/40 transition-colors ${
                                isApproved ? "bg-white" : "bg-slate-50/50 opacity-60"
                              }`}
                            >
                              <td className="px-3 py-2">
                                <button
                                  type="button"
                                  onClick={() => toggleFieldApproval(col.column_name)}
                                  className="text-sky-600 hover:text-sky-800"
                                >
                                  {isApproved ? (
                                    <CheckSquare className="w-4 h-4 text-sky-600" />
                                  ) : (
                                    <Square className="w-4 h-4 text-slate-400" />
                                  )}
                                </button>
                              </td>
                              <td className="px-3 py-2 font-bold text-slate-900">
                                {col.column_name}
                                {col.is_candidate_identifier && (
                                  <span className="ml-1.5 px-1.5 py-0.2 rounded text-[10px] bg-amber-100 text-amber-800 font-bold">
                                    Key Candidate
                                  </span>
                                )}
                              </td>
                              <td className="px-3 py-2 text-slate-600 font-mono text-[11px]">
                                {col.detected_type}
                              </td>
                              <td className="px-3 py-2">
                                <input
                                  type="text"
                                  value={fieldLabels[col.column_name] || ""}
                                  disabled={!isApproved}
                                  onChange={(e) =>
                                    setFieldLabels({
                                      ...fieldLabels,
                                      [col.column_name]: e.target.value,
                                    })
                                  }
                                  placeholder={col.column_name}
                                  className="px-2 py-1 text-xs border border-sky-200 rounded focus:ring-1 focus:ring-sky-500 w-32 bg-white"
                                />
                              </td>
                              <td className="px-3 py-2 text-slate-600 truncate max-w-xs">
                                {col.example_values.slice(0, 3).join(", ") || "-"}
                              </td>
                              <td className="px-3 py-2 text-slate-500 text-[11px]">
                                {col.null_count} nulls / {col.unique_values_count} unique
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Footer Controls */}
                <div className="flex flex-col sm:flex-row items-center justify-between pt-4 border-t border-sky-100 gap-3">
                  <div className="text-xs text-slate-600">
                    <strong className="text-sky-700">{approvedFields.length}</strong> fields approved for AI use.
                  </div>

                  <div className="flex items-center space-x-3">
                    <button
                      onClick={() => setWizardStep(1)}
                      className="px-4 py-2 rounded-xl border border-slate-200 text-slate-700 text-xs font-semibold hover:bg-slate-50"
                    >
                      Back
                    </button>
                    <button
                      onClick={() => handleConfirmAndUpload(false)}
                      disabled={approvedFields.length === 0 || actionLoading}
                      className="px-4 py-2 rounded-xl border border-sky-300 text-sky-700 hover:bg-sky-50 text-xs font-semibold"
                    >
                      Save Approved Only
                    </button>
                    <button
                      onClick={() => handleConfirmAndUpload(true)}
                      disabled={approvedFields.length === 0 || actionLoading}
                      className="px-5 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white text-xs font-semibold shadow-xs flex items-center space-x-2"
                    >
                      {actionLoading ? (
                        <>
                          <RefreshCw className="w-4 h-4 animate-spin" />
                          <span>Activating...</span>
                        </>
                      ) : (
                        <>
                          <CheckCircle2 className="w-4 h-4" />
                          <span>Approve & Activate Now</span>
                        </>
                      )}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ===================================================================== */}
      {/* MODAL: VIEW DATASET SCHEMA DETAILS                                    */}
      {/* ===================================================================== */}
      {viewModalDataset && (
        <div className="fixed inset-0 z-50 overflow-y-auto bg-slate-900/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white border border-sky-200 rounded-3xl max-w-3xl w-full p-6 shadow-xl max-h-[85vh] overflow-y-auto space-y-5">
            <div className="flex items-center justify-between pb-3 border-b border-sky-100">
              <div>
                <h3 className="text-lg font-bold text-slate-900">
                  {viewModalDataset.name} (v{viewModalDataset.version})
                </h3>
                <p className="text-xs text-slate-500">
                  Filename: {viewModalDataset.filename} • Domain: {viewModalDataset.domain_name || "General"}
                </p>
              </div>
              <button
                onClick={() => setViewModalDataset(null)}
                className="p-1 text-slate-400 hover:text-slate-600 rounded-lg hover:bg-slate-100"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="grid grid-cols-2 gap-4 text-xs">
              <div className="p-3 bg-sky-50/50 rounded-xl border border-sky-100">
                <span className="text-slate-500 block">Status:</span>
                <span className="font-bold text-slate-900 capitalize">{viewModalDataset.status}</span>
              </div>
              <div className="p-3 bg-sky-50/50 rounded-xl border border-sky-100">
                <span className="text-slate-500 block">Total Records:</span>
                <span className="font-bold text-slate-900">{viewModalDataset.total_rows.toLocaleString()}</span>
              </div>
            </div>

            <div>
              <span className="text-xs font-bold text-slate-800 uppercase tracking-wider block mb-2">
                Approved Allowed Fields:
              </span>
              <div className="flex flex-wrap gap-1.5">
                {viewModalDataset.approved_fields ? (
                  viewModalDataset.approved_fields.map((f) => (
                    <span
                      key={f}
                      className={`px-2.5 py-1 rounded-lg text-xs font-medium border ${
                        f === viewModalDataset.display_identifier
                          ? "bg-amber-50 text-amber-800 border-amber-300 font-bold"
                          : "bg-white text-slate-700 border-sky-200"
                      }`}
                    >
                      {f === viewModalDataset.display_identifier && "★ "}
                      {viewModalDataset.field_labels?.[f] ? `${viewModalDataset.field_labels[f]} (${f})` : f}
                    </span>
                  ))
                ) : (
                  <span className="text-xs text-slate-500">Legacy schema (all discovered fields enabled)</span>
                )}
              </div>
            </div>

            <div className="flex justify-end pt-3 border-t border-sky-100">
              <button
                onClick={() => setViewModalDataset(null)}
                className="px-4 py-2 rounded-xl bg-sky-600 text-white text-xs font-semibold hover:bg-sky-700"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
