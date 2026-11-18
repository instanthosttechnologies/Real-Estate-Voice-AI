"use client";

import React, { useEffect, useState, useCallback } from "react";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { Pagination } from "@/components/Pagination";
import { api } from "@/lib/api";
import {
  ListFilter,
  Search,
  Users,
  Flame,
  Calendar,
  Clock,
  UserCheck,
  ShieldAlert,
  Building,
  RefreshCw,
} from "lucide-react";

interface ConversationItem {
  id: string;
  session_id: string;
  customer_id?: string;
  customer_name?: string;
  duration_seconds: number;
  conversation_priority: string;
  created_at: string;
}

interface CustomerItem {
  id: string;
  full_name: string;
  email?: string;
  phone: string;
  lead_priority?: string;
  qualification_status?: string;
  total_site_visits: number;
  created_at: string;
}

export default function AdminDashboard() {
  const [activeTab, setActiveTab] = useState<"conversations" | "customers">("conversations");

  // Tab 1: Conversation Priority Table state
  const [conversations, setConversations] = useState<ConversationItem[]>([]);
  const [convPriorityFilter, setConvPriorityFilter] = useState<string>("");
  const [convLimit] = useState(15);
  const [convOffset, setConvOffset] = useState(0);
  const [convLoading, setConvLoading] = useState(false);

  // Tab 2: Total Customer Details Table state
  const [customers, setCustomers] = useState<CustomerItem[]>([]);
  const [customerSearch, setCustomerSearch] = useState<string>("");
  const [custPriorityFilter, setCustPriorityFilter] = useState<string>("");
  const [custLimit] = useState(15);
  const [custOffset, setCustOffset] = useState(0);
  const [custLoading, setCustLoading] = useState(false);

  // Fetch Conversation Priority Table
  const fetchConversations = useCallback(async () => {
    setConvLoading(true);
    try {
      const data = await api.admin.getConversations({
        priority: convPriorityFilter || undefined,
        limit: convLimit,
        offset: convOffset,
      });
      setConversations(data);
    } catch (err) {
      console.error("Error loading Conversation Priority Table:", err);
    } finally {
      setConvLoading(false);
    }
  }, [convPriorityFilter, convLimit, convOffset]);

  // Fetch Total Customer Details Table
  const fetchCustomers = useCallback(async () => {
    setCustLoading(true);
    try {
      const data = await api.admin.getCustomers({
        search: customerSearch || undefined,
        lead_priority: custPriorityFilter || undefined,
        limit: custLimit,
        offset: custOffset,
      });
      setCustomers(data);
    } catch (err) {
      console.error("Error loading Total Customer Details Table:", err);
    } finally {
      setCustLoading(false);
    }
  }, [customerSearch, custPriorityFilter, custLimit, custOffset]);

  useEffect(() => {
    if (activeTab === "conversations") {
      fetchConversations();
    } else {
      fetchCustomers();
    }
  }, [activeTab, fetchConversations, fetchCustomers]);

  const getPriorityBadge = (priority: string) => {
    switch (priority?.toLowerCase()) {
      case "urgent":
        return "bg-red-50 text-red-700 border-red-200 ring-1 ring-red-400";
      case "high":
        return "bg-amber-50 text-amber-700 border-amber-200 ring-1 ring-amber-400";
      case "medium":
        return "bg-blue-50 text-blue-700 border-blue-200";
      case "low":
        return "bg-slate-50 text-slate-700 border-slate-200";
      default:
        return "bg-slate-50 text-slate-600 border-slate-200";
    }
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
              Operational triage tables strictly limited to priority monitoring and customer qualification data.
            </p>
          </div>

          <div className="flex items-center space-x-2 text-xs font-semibold px-3 py-1.5 rounded-lg border border-slate-200 bg-white shadow-sm text-slate-700">
            <ShieldAlert className="w-4 h-4 text-emerald-600" />
            <span>Transcripts & Audio Strictly Restricted</span>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="border-b border-slate-200 mb-6">
          <nav className="-mb-px flex space-x-8" aria-label="Tabs">
            <button
              onClick={() => setActiveTab("conversations")}
              className={`py-4 px-1 inline-flex items-center space-x-2 border-b-2 font-medium text-sm transition-colors ${
                activeTab === "conversations"
                  ? "border-emerald-600 text-emerald-600 font-semibold"
                  : "border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300"
              }`}
            >
              <Flame className="w-4 h-4" />
              <span>Conversation Priority Table</span>
            </button>

            <button
              onClick={() => setActiveTab("customers")}
              className={`py-4 px-1 inline-flex items-center space-x-2 border-b-2 font-medium text-sm transition-colors ${
                activeTab === "customers"
                  ? "border-emerald-600 text-emerald-600 font-semibold"
                  : "border-transparent text-slate-500 hover:text-slate-700 hover:border-slate-300"
              }`}
            >
              <Users className="w-4 h-4" />
              <span>Total Customer Details Table</span>
            </button>
          </nav>
        </div>

        {/* ==================================================================== */}
        {/* TAB 1: CONVERSATION PRIORITY TABLE                                  */}
        {/* ==================================================================== */}
        {activeTab === "conversations" && (
          <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
            {/* Filter Bar */}
            <div className="p-4 sm:p-6 border-b border-slate-200 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div className="flex items-center space-x-3">
                <ListFilter className="w-5 h-5 text-slate-400" />
                <span className="text-xs font-semibold text-slate-700 uppercase tracking-wider">Priority Filter:</span>
                <select
                  value={convPriorityFilter}
                  onChange={(e) => {
                    setConvPriorityFilter(e.target.value);
                    setConvOffset(0);
                  }}
                  className="py-1.5 px-3 border border-slate-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-emerald-500"
                >
                  <option value="">All Priorities (Urgent → High → Medium → Low)</option>
                  <option value="urgent">Urgent</option>
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                </select>
              </div>

              <button
                onClick={fetchConversations}
                disabled={convLoading}
                className="inline-flex items-center space-x-1.5 px-3 py-1.5 border border-slate-300 rounded-lg text-xs font-semibold text-slate-700 hover:bg-slate-50 transition-colors disabled:opacity-50"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${convLoading ? "animate-spin" : ""}`} />
                <span>Refresh</span>
              </button>
            </div>

            {/* Table */}
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200">
                <thead className="bg-slate-50">
                  <tr>
                    <th className="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                      Priority Rank
                    </th>
                    <th className="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                      Session ID
                    </th>
                    <th className="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                      Customer
                    </th>
                    <th className="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                      Duration
                    </th>
                    <th className="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                      Recorded Date
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-slate-200">
                  {convLoading ? (
                    <tr>
                      <td colSpan={5} className="px-6 py-12 text-center text-sm text-slate-500">
                        <div className="inline-block w-6 h-6 border-2 border-emerald-600 border-t-transparent rounded-full animate-spin mb-2"></div>
                        <p>Loading operational conversation records...</p>
                      </td>
                    </tr>
                  ) : conversations.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-6 py-12 text-center text-sm text-slate-500">
                        No conversations found matching criteria.
                      </td>
                    </tr>
                  ) : (
                    conversations.map((item) => (
                      <tr key={item.id} className="hover:bg-slate-50 transition-colors">
                        <td className="px-6 py-4 whitespace-nowrap">
                          <span
                            className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-bold border capitalize ${getPriorityBadge(
                              item.conversation_priority
                            )}`}
                          >
                            {item.conversation_priority}
                          </span>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm font-mono text-slate-700">
                          {item.session_id}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-slate-900">
                          {item.customer_name || "Anonymous / Unlinked"}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-600 flex items-center space-x-1.5">
                          <Clock className="w-3.5 h-3.5 text-slate-400" />
                          <span>{item.duration_seconds}s</span>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-500">
                          {new Date(item.created_at).toLocaleString()}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <Pagination
              total={conversations.length}
              limit={convLimit}
              offset={convOffset}
              onPageChange={(newOffset) => setConvOffset(newOffset)}
            />
          </div>
        )}

        {/* ==================================================================== */}
        {/* TAB 2: TOTAL CUSTOMER DETAILS TABLE                                 */}
        {/* ==================================================================== */}
        {activeTab === "customers" && (
          <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
            {/* Search and Filter Bar */}
            <div className="p-4 sm:p-6 border-b border-slate-200 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div className="flex-1 flex flex-col sm:flex-row items-center gap-3">
                <div className="relative w-full sm:w-80">
                  <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                    <Search className="w-4 h-4" />
                  </div>
                  <input
                    type="text"
                    value={customerSearch}
                    onChange={(e) => {
                      setCustomerSearch(e.target.value);
                      setCustOffset(0);
                    }}
                    placeholder="Search by customer name, email, or phone..."
                    className="block w-full pl-9 pr-3 py-2 border border-slate-300 rounded-lg text-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  />
                </div>

                <div className="flex items-center space-x-2 w-full sm:w-auto">
                  <span className="text-xs font-semibold text-slate-700 uppercase tracking-wider">Priority:</span>
                  <select
                    value={custPriorityFilter}
                    onChange={(e) => {
                      setCustPriorityFilter(e.target.value);
                      setCustOffset(0);
                    }}
                    className="py-1.5 px-3 border border-slate-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-emerald-500"
                  >
                    <option value="">All (Urgent → High → Medium → Low)</option>
                    <option value="urgent">Urgent</option>
                    <option value="high">High</option>
                    <option value="medium">Medium</option>
                    <option value="low">Low</option>
                  </select>
                </div>
              </div>

              <button
                onClick={fetchCustomers}
                disabled={custLoading}
                className="inline-flex items-center space-x-1.5 px-3 py-1.5 border border-slate-300 rounded-lg text-xs font-semibold text-slate-700 hover:bg-slate-50 transition-colors disabled:opacity-50"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${custLoading ? "animate-spin" : ""}`} />
                <span>Refresh</span>
              </button>
            </div>

            {/* Table */}
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200">
                <thead className="bg-slate-50">
                  <tr>
                    <th className="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                      Lead Priority
                    </th>
                    <th className="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                      Customer Name
                    </th>
                    <th className="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                      Contact Information
                    </th>
                    <th className="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                      Qualification
                    </th>
                    <th className="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                      Site Visits Booked
                    </th>
                    <th className="px-6 py-3.5 text-left text-xs font-semibold text-slate-500 uppercase tracking-wider">
                      Registered Date
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-slate-200">
                  {custLoading ? (
                    <tr>
                      <td colSpan={6} className="px-6 py-12 text-center text-sm text-slate-500">
                        <div className="inline-block w-6 h-6 border-2 border-emerald-600 border-t-transparent rounded-full animate-spin mb-2"></div>
                        <p>Loading total customer details...</p>
                      </td>
                    </tr>
                  ) : customers.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-6 py-12 text-center text-sm text-slate-500">
                        No customer records found.
                      </td>
                    </tr>
                  ) : (
                    customers.map((cust) => (
                      <tr key={cust.id} className="hover:bg-slate-50 transition-colors">
                        <td className="px-6 py-4 whitespace-nowrap">
                          {cust.lead_priority ? (
                            <span
                              className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-bold border capitalize ${getPriorityBadge(
                                cust.lead_priority
                              )}`}
                            >
                              {cust.lead_priority}
                            </span>
                          ) : (
                            <span className="text-xs text-slate-400">None</span>
                          )}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm font-semibold text-slate-900">
                          {cust.full_name}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-600">
                          <div>{cust.email || "No email"}</div>
                          <div className="text-xs text-slate-400 font-mono mt-0.5">{cust.phone}</div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm">
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-800 capitalize">
                            {cust.qualification_status || "unqualified"}
                          </span>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-700">
                          <div className="flex items-center space-x-1.5 font-semibold">
                            <Calendar className="w-4 h-4 text-emerald-600" />
                            <span>{cust.total_site_visits}</span>
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-500">
                          {new Date(cust.created_at).toLocaleDateString()}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            <Pagination
              total={customers.length}
              limit={custLimit}
              offset={custOffset}
              onPageChange={(newOffset) => setCustOffset(newOffset)}
            />
          </div>
        )}
      </div>
    </ProtectedRoute>
  );
}
