"use client";

import React, { useEffect, useState, useCallback } from "react";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { Pagination } from "@/components/Pagination";
import {
  api,
  RegisteredCustomerItem,
  CustomerPriorityRankingItem,
  CustomerDetailResponse,
} from "@/lib/api";
import {
  Users,
  Award,
  Search,
  ListFilter,
  RefreshCw,
  Clock,
  Calendar,
  ShieldAlert,
  ChevronDown,
  ChevronUp,
  Phone,
  Mail,
  MapPin,
  Building,
  Home,
  CheckCircle2,
  AlertCircle,
  FileText,
  UserCheck,
  Check,
  CalendarCheck,
  Database,
} from "lucide-react";
import { DatasetManagement } from "@/components/DatasetManagement";

export default function AdminDashboard() {
  const [activeTab, setActiveTab] = useState<"registered" | "ranking" | "datasets">("registered");

  // =========================================================================
  // Table 1: All Registered Customers State
  // =========================================================================
  const [registeredCustomers, setRegisteredCustomers] = useState<RegisteredCustomerItem[]>([]);
  const [regSearch, setRegSearch] = useState<string>("");
  const [regStatusFilter, setRegStatusFilter] = useState<string>("");
  const [regTotal, setRegTotal] = useState<number>(0);
  const [regLimit] = useState<number>(15);
  const [regOffset, setRegOffset] = useState<number>(0);
  const [regLoading, setRegLoading] = useState<boolean>(false);

  // =========================================================================
  // Table 2: Customer Priority Ranking State
  // =========================================================================
  const [rankingItems, setRankingItems] = useState<CustomerPriorityRankingItem[]>([]);
  const [rankSearch, setRankSearch] = useState<string>("");
  const [rankTimeRange, setRankTimeRange] = useState<string>("all");
  const [rankPriorityFilter, setRankPriorityFilter] = useState<string>("");
  const [rankTotal, setRankTotal] = useState<number>(0);
  const [rankLimit] = useState<number>(15);
  const [rankOffset, setRankOffset] = useState<number>(0);
  const [rankLoading, setRankLoading] = useState<boolean>(false);

  // =========================================================================
  // Inline Expandable Row State (Directly Below Selected Row)
  // =========================================================================
  const [expandedCustomerId, setExpandedCustomerId] = useState<string | null>(null);
  const [detailsCache, setDetailsCache] = useState<Record<string, CustomerDetailResponse>>({});
  const [loadingDetails, setLoadingDetails] = useState<Record<string, boolean>>({});
  const [detailsError, setDetailsError] = useState<Record<string, string>>({});

  // Fetch Table 1: All Registered Customers
  const fetchRegisteredCustomers = useCallback(async () => {
    setRegLoading(true);
    try {
      const res = await api.admin.getRegisteredCustomers({
        search: regSearch.trim() || undefined,
        status_filter: regStatusFilter || undefined,
        limit: regLimit,
        offset: regOffset,
      });
      setRegisteredCustomers(res.items || []);
      setRegTotal(res.total || 0);
    } catch (err) {
      console.error("Error loading All Registered Customers:", err);
    } finally {
      setRegLoading(false);
    }
  }, [regSearch, regStatusFilter, regLimit, regOffset]);

  // Fetch Table 2: Customer Priority Ranking
  const fetchPriorityRanking = useCallback(async () => {
    setRankLoading(true);
    try {
      const res = await api.admin.getPriorityRanking({
        search: rankSearch.trim() || undefined,
        time_range: rankTimeRange,
        priority_filter: rankPriorityFilter || undefined,
        limit: rankLimit,
        offset: rankOffset,
      });
      setRankingItems(res.items || []);
      setRankTotal(res.total || 0);
    } catch (err) {
      console.error("Error loading Customer Priority Ranking:", err);
    } finally {
      setRankLoading(false);
    }
  }, [rankSearch, rankTimeRange, rankPriorityFilter, rankLimit, rankOffset]);

  useEffect(() => {
    if (activeTab === "registered") {
      fetchRegisteredCustomers();
    } else if (activeTab === "ranking") {
      fetchPriorityRanking();
    }
    // Collapse any expanded row when switching tabs
    setExpandedCustomerId(null);
  }, [activeTab, fetchRegisteredCustomers, fetchPriorityRanking]);

  // Toggle inline expanded customer details
  const handleToggleCustomer = useCallback(
    async (customerId: string) => {
      if (expandedCustomerId === customerId) {
        // Clicking the same name collapses it
        setExpandedCustomerId(null);
        return;
      }

      // Clicking another name expands it and collapses any previous
      setExpandedCustomerId(customerId);

      // Load details if not already cached
      if (!detailsCache[customerId]) {
        setLoadingDetails((prev) => ({ ...prev, [customerId]: true }));
        try {
          const detail = await api.admin.getCustomerDetails(customerId);
          setDetailsCache((prev) => ({ ...prev, [customerId]: detail }));
          setDetailsError((prev) => {
            const next = { ...prev };
            delete next[customerId];
            return next;
          });
        } catch (err: any) {
          console.error("Error loading inline customer details:", err);
          setDetailsError((prev) => ({
            ...prev,
            [customerId]: err.message || "Failed to load customer details",
          }));
        } finally {
          setLoadingDetails((prev) => ({ ...prev, [customerId]: false }));
        }
      }
    },
    [expandedCustomerId, detailsCache]
  );

  const getPriorityBadgeClass = (priority: string) => {
    switch (priority?.toLowerCase()) {
      case "high":
        return "bg-rose-50 text-rose-700 border-rose-200 ring-1 ring-rose-400";
      case "medium":
        return "bg-sky-50 text-sky-700 border-sky-200 ring-1 ring-sky-400";
      case "low":
        return "bg-slate-50 text-slate-700 border-slate-200";
      default:
        return "bg-slate-50 text-slate-600 border-slate-200";
    }
  };

  const getRankBadgeClass = (rank: number) => {
    if (rank === 1) return "bg-amber-100 text-amber-800 border-amber-300 font-extrabold ring-1 ring-amber-400";
    if (rank === 2) return "bg-slate-200 text-slate-800 border-slate-300 font-bold";
    if (rank === 3) return "bg-amber-50 text-amber-700 border-amber-200 font-semibold";
    return "bg-sky-50 text-sky-800 border-sky-200 font-medium";
  };

  return (
    <ProtectedRoute allowedRoles={["admin", "super_owner"]}>
      <div className="max-w-7xl mx-auto px-4 py-8 sm:px-6 lg:px-8">
        {/* Header */}
        <div className="mb-6 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">
              Operational Admin Dashboard
            </h1>
            <p className="mt-1 text-sm text-slate-600">
              Operational triage and customer prioritization. Click any customer name to expand full records inline.
            </p>
          </div>

          <div className="flex items-center space-x-2 text-xs font-semibold px-3 py-1.5 rounded-lg border border-sky-200 bg-white shadow-xs text-slate-700">
            <ShieldAlert className="w-4 h-4 text-sky-600" />
            <span>Transcripts & Audio Strictly Restricted</span>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="border-b border-sky-100 mb-6">
          <nav className="-mb-px flex space-x-8" aria-label="Tabs">
            <button
              onClick={() => {
                setActiveTab("registered");
                setRegOffset(0);
              }}
              className={`py-4 px-1 inline-flex items-center space-x-2 border-b-2 font-medium text-sm transition-colors ${
                activeTab === "registered"
                  ? "border-sky-600 text-sky-600 font-semibold"
                  : "border-transparent text-slate-500 hover:text-slate-800 hover:border-slate-300"
              }`}
            >
              <Users className="w-4 h-4" />
              <span>All Registered Customers</span>
              {regTotal > 0 && (
                <span className="ml-1.5 px-2 py-0.5 rounded-full text-xs bg-sky-100 text-sky-700 font-bold">
                  {regTotal}
                </span>
              )}
            </button>

            <button
              onClick={() => {
                setActiveTab("ranking");
                setRankOffset(0);
              }}
              className={`py-4 px-1 inline-flex items-center space-x-2 border-b-2 font-medium text-sm transition-colors ${
                activeTab === "ranking"
                  ? "border-sky-600 text-sky-600 font-semibold"
                  : "border-transparent text-slate-500 hover:text-slate-800 hover:border-slate-300"
              }`}
            >
              <Award className="w-4 h-4 text-sky-600" />
              <span>Customer Priority Ranking</span>
              {rankTotal > 0 && (
                <span className="ml-1.5 px-2 py-0.5 rounded-full text-xs bg-sky-100 text-sky-700 font-bold">
                  {rankTotal}
                </span>
              )}
            </button>

            <button
              onClick={() => {
                setActiveTab("datasets");
              }}
              className={`py-4 px-1 inline-flex items-center space-x-2 border-b-2 font-medium text-sm transition-colors ${
                activeTab === "datasets"
                  ? "border-sky-600 text-sky-600 font-semibold"
                  : "border-transparent text-slate-500 hover:text-slate-800 hover:border-slate-300"
              }`}
            >
              <Database className="w-4 h-4 text-sky-600" />
              <span>AI Knowledge / Dataset Management</span>
            </button>
          </nav>
        </div>

        {/* ==================================================================== */}
        {/* TABLE 1: ALL REGISTERED CUSTOMERS                                   */}
        {/* Main Columns: 1. Customer Name | 2. Verification Status | 3. Total Convs */}
        {/* ==================================================================== */}
        {activeTab === "registered" && (
          <div className="bg-white border border-sky-100 rounded-2xl shadow-sm overflow-hidden">
            {/* Filter and Search Bar */}
            <div className="p-4 sm:p-6 border-b border-sky-100 flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
              <div className="flex-1 flex flex-col sm:flex-row items-center gap-3">
                <div className="relative w-full sm:w-80">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                    <Search className="w-4 h-4" />
                  </div>
                  <input
                    type="text"
                    value={regSearch}
                    onChange={(e) => {
                      setRegSearch(e.target.value);
                      setRegOffset(0);
                    }}
                    placeholder="Search name, phone, or email..."
                    className="block w-full pl-9 pr-3 py-2 border border-slate-200 rounded-lg text-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500"
                  />
                </div>

                <div className="flex items-center space-x-2 w-full sm:w-auto">
                  <ListFilter className="w-4 h-4 text-sky-600" />
                  <span className="text-xs font-semibold text-slate-700 uppercase tracking-wider">Status:</span>
                  <select
                    value={regStatusFilter}
                    onChange={(e) => {
                      setRegStatusFilter(e.target.value);
                      setRegOffset(0);
                    }}
                    className="py-1.5 px-3 border border-slate-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-sky-500"
                  >
                    <option value="">All Statuses</option>
                    <option value="verified">Verified</option>
                    <option value="unverified">Unverified</option>
                  </select>
                </div>
              </div>

              <div className="flex items-center space-x-2">
                <button
                  onClick={fetchRegisteredCustomers}
                  disabled={regLoading}
                  className="inline-flex items-center space-x-1.5 px-3 py-1.5 border border-slate-200 rounded-lg text-xs font-semibold text-slate-700 hover:bg-sky-50/50 transition-colors disabled:opacity-50"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${regLoading ? "animate-spin" : ""}`} />
                  <span>Refresh</span>
                </button>
              </div>
            </div>

            {/* Table */}
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-sky-100">
                <thead className="bg-sky-50/70">
                  <tr>
                    <th className="px-6 py-3.5 text-left text-xs font-semibold text-slate-700 uppercase tracking-wider">
                      Customer Name
                    </th>
                    <th className="px-6 py-3.5 text-left text-xs font-semibold text-slate-700 uppercase tracking-wider">
                      Verification Status
                    </th>
                    <th className="px-6 py-3.5 text-center text-xs font-semibold text-slate-700 uppercase tracking-wider">
                      Total AI Conversations
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-slate-100">
                  {regLoading ? (
                    <tr>
                      <td colSpan={3} className="px-6 py-12 text-center text-sm text-slate-500">
                        <div className="inline-block w-6 h-6 border-2 border-sky-600 border-t-transparent rounded-full animate-spin mb-2"></div>
                        <p>Loading registered customer profiles...</p>
                      </td>
                    </tr>
                  ) : registeredCustomers.length === 0 ? (
                    <tr>
                      <td colSpan={3} className="px-6 py-12 text-center text-sm text-slate-500">
                        No registered customers found matching your criteria.
                      </td>
                    </tr>
                  ) : (
                    registeredCustomers.map((cust) => {
                      const isExpanded = expandedCustomerId === cust.customer_id;
                      const detail = detailsCache[cust.customer_id];
                      const isLoading = loadingDetails[cust.customer_id];
                      const error = detailsError[cust.customer_id];

                      return (
                        <React.Fragment key={cust.customer_id}>
                          <tr
                            className={`transition-colors cursor-pointer ${
                              isExpanded ? "bg-sky-50/50" : "hover:bg-sky-50/25"
                            }`}
                            onClick={() => handleToggleCustomer(cust.customer_id)}
                          >
                            {/* Column 1: Customer Name (Clickable) */}
                            <td className="px-6 py-4 whitespace-nowrap">
                              <button
                                type="button"
                                className="group flex items-center space-x-2 text-left focus:outline-none"
                              >
                                <span className="text-sm font-semibold text-sky-700 group-hover:text-sky-900 group-hover:underline">
                                  {cust.customer_name}
                                </span>
                                {isExpanded ? (
                                  <ChevronUp className="w-4 h-4 text-sky-600 shrink-0" />
                                ) : (
                                  <ChevronDown className="w-4 h-4 text-slate-400 group-hover:text-sky-600 shrink-0" />
                                )}
                              </button>
                            </td>

                            {/* Column 2: Verification Status */}
                            <td className="px-6 py-4 whitespace-nowrap text-sm">
                              <span
                                className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold border ${
                                  cust.is_verified
                                    ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                                    : "bg-slate-100 text-slate-600 border-slate-200"
                                }`}
                              >
                                {cust.is_verified ? "Verified" : "Unverified"}
                              </span>
                            </td>

                            {/* Column 3: Total AI Conversations */}
                            <td className="px-6 py-4 whitespace-nowrap text-sm text-center">
                              <span
                                className={`inline-flex items-center px-3 py-0.5 rounded-full text-xs font-bold ${
                                  cust.total_conversations > 0
                                    ? "bg-sky-100 text-sky-800"
                                    : "bg-slate-100 text-slate-500"
                                }`}
                              >
                                {cust.total_conversations}
                              </span>
                            </td>
                          </tr>

                          {/* EXPANDABLE DETAILS ROW DIRECTLY BELOW SELECTED CUSTOMER */}
                          {isExpanded && (
                            <tr className="bg-sky-50/30 border-b border-sky-100">
                              <td colSpan={3} className="px-6 py-5">
                                <div className="bg-white border border-sky-200/80 rounded-xl p-5 shadow-xs animate-in fade-in duration-150 space-y-4">
                                  {isLoading ? (
                                    <div className="py-8 text-center">
                                      <div className="inline-block w-6 h-6 border-2 border-sky-600 border-t-transparent rounded-full animate-spin mb-2"></div>
                                      <p className="text-xs text-slate-500 font-medium">Loading full customer details...</p>
                                    </div>
                                  ) : error ? (
                                    <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-xs flex items-center space-x-2">
                                      <AlertCircle className="w-4 h-4 shrink-0" />
                                      <span>{error}</span>
                                    </div>
                                  ) : (
                                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 text-xs">
                                      {/* Customer Identification */}
                                      <div className="p-3.5 rounded-lg bg-sky-50/40 border border-sky-100 space-y-2">
                                        <div className="font-bold text-slate-800 uppercase tracking-wider text-2xs flex items-center space-x-1.5">
                                          <UserCheck className="w-3.5 h-3.5 text-sky-600" />
                                          <span>Customer Identity</span>
                                        </div>
                                        <div>
                                          <span className="text-slate-500">Customer ID:</span>{" "}
                                          <span className="font-mono text-slate-700 select-all">
                                            {cust.customer_id}
                                          </span>
                                        </div>
                                        <div>
                                          <span className="text-slate-500">Full Name:</span>{" "}
                                          <span className="font-semibold text-slate-900">{cust.customer_name}</span>
                                        </div>
                                        <div>
                                          <span className="text-slate-500">Phone Number:</span>{" "}
                                          <span className="font-mono text-slate-800">{cust.phone}</span>
                                        </div>
                                        <div>
                                          <span className="text-slate-500">Email ID:</span>{" "}
                                          <span className="text-slate-700">{cust.email || "Not provided"}</span>
                                        </div>
                                        <div>
                                          <span className="text-slate-500">OTP Verification Status:</span>{" "}
                                          <span className={cust.is_verified ? "text-emerald-700 font-semibold" : "text-slate-600"}>
                                            {cust.is_verified ? "Verified" : "Unverified"}
                                          </span>
                                        </div>
                                        <div>
                                          <span className="text-slate-500">Registration Date:</span>{" "}
                                          <span className="text-slate-700">
                                            {new Date(cust.registration_date).toLocaleString()}
                                          </span>
                                        </div>
                                      </div>

                                      {/* Real Estate Preferences */}
                                      <div className="p-3.5 rounded-lg bg-sky-50/40 border border-sky-100 space-y-2">
                                        <div className="font-bold text-slate-800 uppercase tracking-wider text-2xs flex items-center space-x-1.5">
                                          <Building className="w-3.5 h-3.5 text-sky-600" />
                                          <span>Property Preferences</span>
                                        </div>
                                        <div>
                                          <span className="text-slate-500">Preferred City / Location:</span>{" "}
                                          <span className="font-medium text-slate-800">
                                            {detail?.preferred_location || cust.preferred_location || "Not provided"}
                                          </span>
                                        </div>
                                        <div>
                                          <span className="text-slate-500">Interested Property / Project:</span>{" "}
                                          <span className="font-medium text-slate-800">
                                            {detail?.interested_project || "Not provided"}
                                          </span>
                                        </div>
                                        <div>
                                          <span className="text-slate-500">Preferred BHK:</span>{" "}
                                          <span className="font-medium text-slate-800">
                                            {detail?.preferred_config || cust.preferred_config || "Not provided"}
                                          </span>
                                        </div>
                                        <div>
                                          <span className="text-slate-500">Budget Range:</span>{" "}
                                          <span className="font-semibold text-slate-800">
                                            {detail?.budget_display || cust.budget_display || "Not provided"}
                                          </span>
                                        </div>
                                        <div>
                                          <span className="text-slate-500">Lead Qualification Status:</span>{" "}
                                          <span className="font-medium capitalize text-slate-800">
                                            {detail?.qualification_status || cust.qualification_status || "Not provided"}
                                          </span>
                                        </div>
                                      </div>

                                      {/* Engagement & Follow-up Details */}
                                      <div className="p-3.5 rounded-lg bg-sky-50/40 border border-sky-100 space-y-2">
                                        <div className="font-bold text-slate-800 uppercase tracking-wider text-2xs flex items-center space-x-1.5">
                                          <CalendarCheck className="w-3.5 h-3.5 text-sky-600" />
                                          <span>Conversations & Visits</span>
                                        </div>
                                        <div>
                                          <span className="text-slate-500">Total AI Conversations:</span>{" "}
                                          <span className="font-bold text-slate-800">{cust.total_conversations}</span>
                                        </div>
                                        <div>
                                          <span className="text-slate-500">Last Conversation Date:</span>{" "}
                                          <span className="text-slate-700">
                                            {cust.last_conversation_date
                                              ? new Date(cust.last_conversation_date).toLocaleString()
                                              : "Never"}
                                          </span>
                                        </div>
                                        <div>
                                          <span className="text-slate-500">Site Visit Booking Details:</span>{" "}
                                          <span className="text-slate-800 font-medium">
                                            {detail?.site_visits && detail.site_visits.length > 0
                                              ? `${detail.site_visits.length} visit(s) recorded — Status: ${detail.site_visit_status || detail.site_visits[0].status}`
                                              : "Not provided"}
                                          </span>
                                        </div>
                                        <div>
                                          <span className="text-slate-500">Requirement Notes:</span>{" "}
                                          <p className="mt-1 text-slate-700 italic bg-white p-2 rounded border border-slate-200">
                                            {detail?.notes || "Not provided"}
                                          </p>
                                        </div>
                                      </div>
                                    </div>
                                  )}
                                </div>
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <Pagination
              total={regTotal}
              limit={regLimit}
              offset={regOffset}
              onPageChange={(newOffset) => setRegOffset(newOffset)}
            />
          </div>
        )}

        {/* ==================================================================== */}
        {/* TABLE 2: CUSTOMER PRIORITY RANKING                                  */}
        {/* Main Columns: 1. Rank | 2. Customer Name | 3. Total Convs | 4. Repeat Convs | 5. Total Duration | 6. Priority */}
        {/* Numerical Priority Score is STRICTLY omitted from UI and response    */}
        {/* ==================================================================== */}
        {activeTab === "ranking" && (
          <div className="bg-white border border-sky-100 rounded-2xl shadow-sm overflow-hidden">
            {/* Filter and Search Bar */}
            <div className="p-4 sm:p-6 border-b border-sky-100 flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
              <div className="flex-1 flex flex-col sm:flex-row items-center gap-3">
                <div className="relative w-full sm:w-72">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                    <Search className="w-4 h-4" />
                  </div>
                  <input
                    type="text"
                    value={rankSearch}
                    onChange={(e) => {
                      setRankSearch(e.target.value);
                      setRankOffset(0);
                    }}
                    placeholder="Search name or phone..."
                    className="block w-full pl-9 pr-3 py-2 border border-slate-200 rounded-lg text-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500"
                  />
                </div>

                {/* Time Range Filter */}
                <div className="flex items-center space-x-2 w-full sm:w-auto">
                  <Calendar className="w-4 h-4 text-sky-600" />
                  <span className="text-xs font-semibold text-slate-700 uppercase tracking-wider">Range:</span>
                  <select
                    value={rankTimeRange}
                    onChange={(e) => {
                      setRankTimeRange(e.target.value);
                      setRankOffset(0);
                    }}
                    className="py-1.5 px-3 border border-slate-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-sky-500"
                  >
                    <option value="all">All time</option>
                    <option value="30d">Last 30 days</option>
                    <option value="7d">Last 7 days</option>
                  </select>
                </div>

                {/* Priority Filter */}
                <div className="flex items-center space-x-2 w-full sm:w-auto">
                  <ListFilter className="w-4 h-4 text-sky-600" />
                  <span className="text-xs font-semibold text-slate-700 uppercase tracking-wider">Priority:</span>
                  <select
                    value={rankPriorityFilter}
                    onChange={(e) => {
                      setRankPriorityFilter(e.target.value);
                      setRankOffset(0);
                    }}
                    className="py-1.5 px-3 border border-slate-200 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-sky-500"
                  >
                    <option value="">All Priorities (Urgent → High → Medium → Low)</option>
                    <option value="high">High Priority</option>
                    <option value="medium">Medium Priority</option>
                    <option value="low">Low Priority</option>
                  </select>
                </div>
              </div>

              <div className="flex items-center space-x-2">
                <button
                  onClick={fetchPriorityRanking}
                  disabled={rankLoading}
                  className="inline-flex items-center space-x-1.5 px-3 py-1.5 border border-slate-200 rounded-lg text-xs font-semibold text-slate-700 hover:bg-sky-50/50 transition-colors disabled:opacity-50"
                >
                  <RefreshCw className={`w-3.5 h-3.5 ${rankLoading ? "animate-spin" : ""}`} />
                  <span>Refresh</span>
                </button>
              </div>
            </div>

            {/* Table */}
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-sky-100">
                <thead className="bg-sky-50/70">
                  <tr>
                    <th className="px-5 py-3.5 text-center text-xs font-semibold text-slate-700 uppercase tracking-wider">
                      Rank
                    </th>
                    <th className="px-5 py-3.5 text-left text-xs font-semibold text-slate-700 uppercase tracking-wider">
                      Customer Name
                    </th>
                    <th className="px-5 py-3.5 text-center text-xs font-semibold text-slate-700 uppercase tracking-wider">
                      Total Conversations
                    </th>
                    <th className="px-5 py-3.5 text-center text-xs font-semibold text-slate-700 uppercase tracking-wider">
                      Repeat Conversations
                    </th>
                    <th className="px-5 py-3.5 text-left text-xs font-semibold text-slate-700 uppercase tracking-wider">
                      Total Conversation Duration
                    </th>
                    <th className="px-5 py-3.5 text-center text-xs font-semibold text-slate-700 uppercase tracking-wider">
                      Priority
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-slate-100">
                  {rankLoading ? (
                    <tr>
                      <td colSpan={6} className="px-6 py-12 text-center text-sm text-slate-500">
                        <div className="inline-block w-6 h-6 border-2 border-sky-600 border-t-transparent rounded-full animate-spin mb-2"></div>
                        <p>Computing priority rankings based on conversational duration and repeat engagement...</p>
                      </td>
                    </tr>
                  ) : rankingItems.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-6 py-12 text-center text-sm text-slate-500">
                        No customer ranking records found for this time range.
                      </td>
                    </tr>
                  ) : (
                    rankingItems.map((item) => {
                      const isExpanded = expandedCustomerId === item.customer_id;
                      const detail = detailsCache[item.customer_id];
                      const isLoading = loadingDetails[item.customer_id];
                      const error = detailsError[item.customer_id];

                      return (
                        <React.Fragment key={item.customer_id}>
                          <tr
                            className={`transition-colors cursor-pointer ${
                              isExpanded ? "bg-sky-50/50" : "hover:bg-sky-50/25"
                            }`}
                            onClick={() => handleToggleCustomer(item.customer_id)}
                          >
                            {/* Column 1: Rank */}
                            <td className="px-5 py-3.5 whitespace-nowrap text-center">
                              <span className={`inline-flex items-center justify-center w-7 h-7 rounded-full text-xs border ${getRankBadgeClass(item.rank)}`}>
                                #{item.rank}
                              </span>
                            </td>

                            {/* Column 2: Customer Name (Clickable) */}
                            <td className="px-5 py-3.5 whitespace-nowrap">
                              <button
                                type="button"
                                className="group flex items-center space-x-2 text-left focus:outline-none"
                              >
                                <span className="text-sm font-semibold text-sky-700 group-hover:text-sky-900 group-hover:underline">
                                  {item.customer_name}
                                </span>
                                {isExpanded ? (
                                  <ChevronUp className="w-4 h-4 text-sky-600 shrink-0" />
                                ) : (
                                  <ChevronDown className="w-4 h-4 text-slate-400 group-hover:text-sky-600 shrink-0" />
                                )}
                              </button>
                            </td>

                            {/* Column 3: Total Conversations */}
                            <td className="px-5 py-3.5 whitespace-nowrap text-center text-sm font-semibold text-slate-800">
                              {item.total_conversations}
                            </td>

                            {/* Column 4: Repeat Conversations */}
                            <td className="px-5 py-3.5 whitespace-nowrap text-center text-sm text-slate-700 font-medium">
                              <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-bold ${item.repeat_conversations > 0 ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-500"}`}>
                                {item.repeat_conversations}
                              </span>
                            </td>

                            {/* Column 5: Total Conversation Duration */}
                            <td className="px-5 py-3.5 whitespace-nowrap text-xs font-medium text-slate-700">
                              <div className="flex items-center space-x-1.5">
                                <Clock className="w-3.5 h-3.5 text-sky-600" />
                                <span>{item.total_duration_formatted}</span>
                              </div>
                            </td>

                            {/* Column 6: Priority (High / Medium / Low) */}
                            <td className="px-5 py-3.5 whitespace-nowrap text-center">
                              <span className={`inline-flex items-center px-3 py-1 rounded-full text-xs font-bold border capitalize ${getPriorityBadgeClass(item.priority)}`}>
                                {item.priority}
                              </span>
                            </td>
                          </tr>

                          {/* EXPANDABLE DETAILS ROW DIRECTLY BELOW SELECTED CUSTOMER IN TABLE 2 */}
                          {isExpanded && (
                            <tr className="bg-sky-50/30 border-b border-sky-100">
                              <td colSpan={6} className="px-6 py-5">
                                <div className="bg-white border border-sky-200/80 rounded-xl p-5 shadow-xs animate-in fade-in duration-150 space-y-6">
                                  {isLoading ? (
                                    <div className="py-8 text-center">
                                      <div className="inline-block w-6 h-6 border-2 border-sky-600 border-t-transparent rounded-full animate-spin mb-2"></div>
                                      <p className="text-xs text-slate-500 font-medium">Loading comprehensive customer priority details...</p>
                                    </div>
                                  ) : error ? (
                                    <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-xs flex items-center space-x-2">
                                      <AlertCircle className="w-4 h-4 shrink-0" />
                                      <span>{error}</span>
                                    </div>
                                  ) : (
                                    <>
                                      {/* SECTION A — CUSTOMER CONTACT INFORMATION */}
                                      <div>
                                        <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider mb-2.5 flex items-center space-x-1.5">
                                          <UserCheck className="w-4 h-4 text-sky-600" />
                                          <span>Section A — Customer Contact Information</span>
                                        </h3>
                                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 p-3.5 rounded-lg bg-sky-50/40 border border-sky-100 text-xs">
                                          <div>
                                            <span className="text-slate-500">Customer ID:</span>{" "}
                                            <span className="font-mono text-slate-700 select-all">{item.customer_id}</span>
                                          </div>
                                          <div>
                                            <span className="text-slate-500">Full Name:</span>{" "}
                                            <span className="font-semibold text-slate-900">{item.customer_name}</span>
                                          </div>
                                          <div>
                                            <span className="text-slate-500">Phone Number:</span>{" "}
                                            <span className="font-mono text-slate-800">{item.phone}</span>
                                          </div>
                                          <div>
                                            <span className="text-slate-500">Email ID:</span>{" "}
                                            <span className="text-slate-700">{item.email || detail?.email || "Not provided"}</span>
                                          </div>
                                          <div>
                                            <span className="text-slate-500">Verification Status:</span>{" "}
                                            <span className={detail?.is_verified ? "text-emerald-700 font-semibold" : "text-slate-600"}>
                                              {detail?.is_verified ? "Verified" : "Unverified"}
                                            </span>
                                          </div>
                                          <div>
                                            <span className="text-slate-500">Registration Date:</span>{" "}
                                            <span className="text-slate-700">
                                              {detail?.registration_date ? new Date(detail.registration_date).toLocaleString() : "Not provided"}
                                            </span>
                                          </div>
                                        </div>
                                      </div>

                                      {/* SECTION B — CUSTOMER REAL ESTATE REQUIREMENTS */}
                                      <div>
                                        <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider mb-2.5 flex items-center space-x-1.5">
                                          <Building className="w-4 h-4 text-sky-600" />
                                          <span>Section B — Customer Real Estate Requirements</span>
                                        </h3>
                                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 p-3.5 rounded-lg bg-sky-50/40 border border-sky-100 text-xs">
                                          <div>
                                            <span className="text-slate-500">Preferred City / Location:</span>{" "}
                                            <span className="font-medium text-slate-800">{detail?.preferred_location || "Not provided"}</span>
                                          </div>
                                          <div>
                                            <span className="text-slate-500">Interested Property / Project:</span>{" "}
                                            <span className="font-medium text-slate-800">{detail?.interested_project || "Not provided"}</span>
                                          </div>
                                          <div>
                                            <span className="text-slate-500">Property Type:</span>{" "}
                                            <span className="font-medium text-slate-800">{detail?.property_type || "Apartment"}</span>
                                          </div>
                                          <div>
                                            <span className="text-slate-500">Preferred BHK:</span>{" "}
                                            <span className="font-medium text-slate-800">{detail?.preferred_config || "Not provided"}</span>
                                          </div>
                                          <div>
                                            <span className="text-slate-500">Budget Range:</span>{" "}
                                            <span className="font-semibold text-slate-800">{detail?.budget_display || "Not provided"}</span>
                                          </div>
                                          <div className="sm:col-span-2 lg:col-span-3">
                                            <span className="text-slate-500">Requirement Notes:</span>{" "}
                                            <span className="italic text-slate-700">{detail?.notes || "Not provided"}</span>
                                          </div>
                                        </div>
                                      </div>

                                      {/* SECTION C — AI CONVERSATION ACTIVITY */}
                                      <div>
                                        <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider mb-2.5 flex items-center space-x-1.5">
                                          <Clock className="w-4 h-4 text-sky-600" />
                                          <span>Section C — AI Conversation Activity</span>
                                        </h3>
                                        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 p-3.5 rounded-lg bg-sky-50/40 border border-sky-100 text-xs mb-3">
                                          <div>
                                            <span className="text-slate-500 block">Completed Convs:</span>
                                            <span className="font-bold text-slate-900 text-sm">{item.total_conversations}</span>
                                          </div>
                                          <div>
                                            <span className="text-slate-500 block">Repeat Convs:</span>
                                            <span className="font-bold text-slate-900 text-sm">{item.repeat_conversations}</span>
                                          </div>
                                          <div>
                                            <span className="text-slate-500 block">Total Duration:</span>
                                            <span className="font-bold text-slate-900 text-sm">{item.total_duration_formatted}</span>
                                          </div>
                                          <div>
                                            <span className="text-slate-500 block">Average Duration:</span>
                                            <span className="font-bold text-slate-900 text-sm">{item.avg_duration_formatted}</span>
                                          </div>
                                          <div>
                                            <span className="text-slate-500 block">Most Recent Call:</span>
                                            <span className="font-bold text-slate-900 text-sm">{detail?.recent_conversation_duration_formatted || "—"}</span>
                                          </div>
                                          <div>
                                            <span className="text-slate-500 block">Last Conv Date:</span>
                                            <span className="text-slate-700 text-2xs block truncate">
                                              {item.last_conversation_date ? new Date(item.last_conversation_date).toLocaleString() : "—"}
                                            </span>
                                          </div>
                                        </div>

                                        {/* Conversation Date & Duration History */}
                                        {detail?.conversations && detail.conversations.length > 0 ? (
                                          <div className="border border-sky-100 rounded-lg overflow-hidden text-xs">
                                            <table className="min-w-full divide-y divide-sky-100">
                                              <thead className="bg-sky-50/70">
                                                <tr>
                                                  <th className="px-3.5 py-2 text-left font-semibold text-slate-700">Session ID</th>
                                                  <th className="px-3.5 py-2 text-center font-semibold text-slate-700">Duration</th>
                                                  <th className="px-3.5 py-2 text-center font-semibold text-slate-700">Priority</th>
                                                  <th className="px-3.5 py-2 text-left font-semibold text-slate-700">Recorded Date</th>
                                                </tr>
                                              </thead>
                                              <tbody className="bg-white divide-y divide-slate-100">
                                                {detail.conversations.map((conv) => (
                                                  <tr key={conv.id}>
                                                    <td className="px-3.5 py-2 font-mono text-slate-700">{conv.session_id}</td>
                                                    <td className="px-3.5 py-2 text-center font-semibold text-slate-800">{conv.duration_seconds}s</td>
                                                    <td className="px-3.5 py-2 text-center">
                                                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-2xs font-bold uppercase ${getPriorityBadgeClass(conv.conversation_priority)}`}>
                                                        {conv.conversation_priority}
                                                      </span>
                                                    </td>
                                                    <td className="px-3.5 py-2 text-slate-500">{new Date(conv.created_at).toLocaleString()}</td>
                                                  </tr>
                                                ))}
                                              </tbody>
                                            </table>
                                          </div>
                                        ) : (
                                          <div className="text-xs text-slate-400 italic">No conversation history recorded.</div>
                                        )}
                                      </div>

                                      {/* SECTION D — CUSTOMER PRIORITY INFORMATION */}
                                      <div>
                                        <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider mb-2.5 flex items-center space-x-1.5">
                                          <Award className="w-4 h-4 text-sky-600" />
                                          <span>Section D — Customer Priority Information</span>
                                        </h3>
                                        <div className="p-3.5 rounded-lg bg-sky-50/40 border border-sky-100 text-xs space-y-2">
                                          <div className="flex flex-wrap items-center gap-4">
                                            <div>
                                              <span className="text-slate-500">Current Rank:</span>{" "}
                                              <span className={`ml-1 inline-flex items-center px-2.5 py-0.5 rounded-full font-bold text-xs ${getRankBadgeClass(item.rank)}`}>
                                                #{item.rank}
                                              </span>
                                            </div>
                                            <div>
                                              <span className="text-slate-500">Priority Level:</span>{" "}
                                              <span className={`ml-1 inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold border capitalize ${getPriorityBadgeClass(item.priority)}`}>
                                                {item.priority} Priority
                                              </span>
                                            </div>
                                          </div>
                                          <div className="pt-2 border-t border-sky-100/70">
                                            <span className="font-semibold text-slate-700">Engagement Summary: </span>
                                            <span className="text-slate-800 font-medium">
                                              {detail?.engagement_summary ||
                                                `This customer completed ${item.total_conversations} AI conversation${item.total_conversations !== 1 ? "s" : ""}, including ${item.repeat_conversations} repeat conversation${item.repeat_conversations !== 1 ? "s" : ""}, with a total talk time of ${item.total_duration_formatted}.`}
                                            </span>
                                          </div>
                                        </div>
                                      </div>

                                      {/* SECTION E — FOLLOW-UP DETAILS */}
                                      <div>
                                        <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider mb-2.5 flex items-center space-x-1.5">
                                          <CalendarCheck className="w-4 h-4 text-emerald-600" />
                                          <span>Section E — Follow-Up Details</span>
                                        </h3>
                                        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 p-3.5 rounded-lg bg-sky-50/40 border border-sky-100 text-xs">
                                          <div>
                                            <span className="text-slate-500 block">Existing Lead Qualification:</span>
                                            <span className="font-semibold text-slate-800 capitalize">
                                              {detail?.qualification_status || "Not provided"}
                                            </span>
                                          </div>
                                          <div>
                                            <span className="text-slate-500 block">Site Visit Booking Status:</span>
                                            <span className="font-semibold text-slate-800 capitalize">
                                              {detail?.site_visit_status || "Not provided"}
                                            </span>
                                          </div>
                                          <div>
                                            <span className="text-slate-500 block">Last Site Visit Date:</span>
                                            <span className="text-slate-700">
                                              {detail?.last_site_visit_date ? new Date(detail.last_site_visit_date).toLocaleDateString() : "Not provided"}
                                            </span>
                                          </div>
                                          <div>
                                            <span className="text-slate-500 block">Next Scheduled Visit:</span>
                                            <span className="text-slate-700">
                                              {detail?.next_scheduled_visit ? new Date(detail.next_scheduled_visit).toLocaleString() : "Not provided"}
                                            </span>
                                          </div>
                                          <div className="sm:col-span-2 lg:col-span-4 pt-1">
                                            <span className="text-slate-500">Customer Requirement Notes:</span>{" "}
                                            <span className="italic text-slate-700">{detail?.notes || "Not provided"}</span>
                                          </div>
                                        </div>
                                      </div>
                                    </>
                                  )}
                                </div>
                              </td>
                            </tr>
                          )}
                        </React.Fragment>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <Pagination
              total={rankTotal}
              limit={rankLimit}
              offset={rankOffset}
              onPageChange={(newOffset) => setRankOffset(newOffset)}
            />
          </div>
        )}

        {/* ==================================================================== */}
        {/* TAB 3: AI KNOWLEDGE / UNIVERSAL DATASET MANAGEMENT                  */}
        {/* ==================================================================== */}
        {activeTab === "datasets" && (
          <DatasetManagement />
        )}
      </div>
    </ProtectedRoute>
  );
}
