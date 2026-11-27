"use client";

import React, { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { api } from "@/lib/api";
import {
  Calendar as CalendarIcon,
  Clock,
  User,
  Phone,
  Building2,
  MapPin,
  CheckCircle2,
  AlertCircle,
  XCircle,
  RotateCw,
  Plus,
  Search,
  Filter,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  CalendarDays,
  List,
  Sparkles,
  ArrowRight,
  ShieldAlert,
  X,
} from "lucide-react";

interface Appointment {
  id: string;
  customer_name: string;
  contact_number?: string;
  project_id: string;
  property_name: string;
  city: string;
  visit_date: string;
  visit_time: string;
  timezone: string;
  appointment_type: string;
  booking_status: string;
  conversation_id?: string;
  booking_source: string;
  customer_notes?: string;
  assigned_agent?: string;
  created_at: string;
  updated_at: string;
}

export default function AdminCalendarPage() {
  const [appointments, setAppointments] = useState<Appointment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Stats
  const [totalCount, setTotalCount] = useState(0);
  const [confirmedCount, setConfirmedCount] = useState(0);
  const [rescheduledCount, setRescheduledCount] = useState(0);
  const [cancelledCount, setCancelledCount] = useState(0);

  // Helper to format today's date in local YYYY-MM-DD
  const getTodayDateString = () => {
    const d = new Date();
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  };

  // Controls & Filters
  const [viewMode, setViewMode] = useState<"month" | "list">("month");
  const [currentDate, setCurrentDate] = useState<Date>(() => new Date());
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");

  // Modals
  const [rescheduleModalAppt, setRescheduleModalAppt] = useState<Appointment | null>(null);
  const [newDate, setNewDate] = useState("");
  const [newTime, setNewTime] = useState("10:00 AM - 11:00 AM");
  const [rescheduleReason, setRescheduleReason] = useState("");
  const [actionLoading, setActionLoading] = useState(false);

  const [cancelModalAppt, setCancelModalAppt] = useState<Appointment | null>(null);
  const [cancelReason, setCancelReason] = useState("");

  const [showNewModal, setShowNewModal] = useState(false);
  const [newApptData, setNewApptData] = useState({
    customer_name: "",
    contact_number: "",
    property_name: "Godrej Aristocrat",
    city: "Gurugram",
    visit_date: getTodayDateString(),
    visit_time: "10:00 AM - 11:00 AM",
    customer_notes: "",
  });

  const [showSlotChecker, setShowSlotChecker] = useState(false);
  const [slotCheckProject, setSlotCheckProject] = useState("Godrej Aristocrat");
  const [slotCheckDate, setSlotCheckDate] = useState(getTodayDateString());
  const [slotCheckResult, setSlotCheckResult] = useState<any | null>(null);

  // Load appointments
  const fetchAppointments = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.appointments.list({
        status: statusFilter !== "all" ? statusFilter : undefined,
        search: searchQuery.trim() || undefined,
        limit: 100,
      });
      setAppointments(res.items || []);
      setTotalCount(res.total || 0);
      setConfirmedCount(res.active_confirmed_count || 0);
      setRescheduledCount(res.rescheduled_count || 0);
      setCancelledCount(res.cancelled_count || 0);
    } catch (err: any) {
      console.error("Error fetching appointments:", err);
      setError(err.message || "Failed to load appointments");
    } finally {
      setLoading(false);
    }
  }, [statusFilter, searchQuery]);

  useEffect(() => {
    fetchAppointments();
  }, [fetchAppointments]);

  // Calendar math
  const year = currentDate.getFullYear();
  const month = currentDate.getMonth();
  const firstDayIndex = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  const monthNames = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
  ];

  const handlePrevMonth = () => {
    setCurrentDate(new Date(year, month - 1, 1));
  };

  const handleNextMonth = () => {
    setCurrentDate(new Date(year, month + 1, 1));
  };

  const handleToday = () => {
    setCurrentDate(new Date(2026, 10, 26)); // Fixed demo baseline
    setSelectedDate(null);
  };

  // Reschedule handler
  const handleRescheduleSubmit = async () => {
    if (!rescheduleModalAppt || !newDate || !newTime) return;
    setActionLoading(true);
    try {
      await api.appointments.reschedule(rescheduleModalAppt.id, {
        new_visit_date: newDate,
        new_visit_time: newTime,
        reschedule_reason: rescheduleReason,
      });
      setRescheduleModalAppt(null);
      setRescheduleReason("");
      fetchAppointments();
    } catch (err: any) {
      alert(err.message || "Rescheduling failed");
    } finally {
      setActionLoading(false);
    }
  };

  // Cancel handler
  const handleCancelSubmit = async () => {
    if (!cancelModalAppt) return;
    setActionLoading(true);
    try {
      await api.appointments.cancel(cancelModalAppt.id, cancelReason);
      setCancelModalAppt(null);
      setCancelReason("");
      fetchAppointments();
    } catch (err: any) {
      alert(err.message || "Cancellation failed");
    } finally {
      setActionLoading(false);
    }
  };

  // Create manual appointment handler
  const handleCreateSubmit = async () => {
    if (!newApptData.customer_name || !newApptData.property_name || !newApptData.visit_date) {
      alert("Please fill required fields");
      return;
    }
    setActionLoading(true);
    try {
      await api.appointments.create(newApptData);
      setShowNewModal(false);
      setNewApptData({
        customer_name: "",
        contact_number: "",
        property_name: "Godrej Aristocrat",
        city: "Gurugram",
        visit_date: "2026-11-27",
        visit_time: "10:00 AM - 11:00 AM",
        customer_notes: "",
      });
      fetchAppointments();
    } catch (err: any) {
      alert(err.message || "Booking failed");
    } finally {
      setActionLoading(false);
    }
  };

  // Slot check handler
  const handleCheckSlots = async () => {
    try {
      const res = await api.appointments.getSlots(slotCheckProject, slotCheckDate);
      setSlotCheckResult(res);
    } catch (err: any) {
      alert(err.message || "Could not retrieve slots");
    }
  };

  // Filtered by selected day if clicked
  const displayAppointments = selectedDate
    ? appointments.filter((a) => a.visit_date === selectedDate)
    : appointments;

  return (
    <ProtectedRoute allowedRoles={["admin", "super_owner"]}>
      <div className="min-h-screen bg-slate-950 text-slate-100 p-4 sm:p-8">
        <div className="max-w-7xl mx-auto space-y-6">
          {/* Header & Breadcrumb */}
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-4 border-b border-slate-800">
            <div>
              <div className="flex items-center gap-2 text-xs text-slate-400 mb-1">
                <Link href="/admin" className="hover:text-emerald-400 transition-colors">Admin Portal</Link>
                <span>/</span>
                <span className="text-emerald-400 font-semibold">Calendar & Site Visits</span>
              </div>
              <h1 className="text-2xl font-black text-white flex items-center gap-2">
                <CalendarIcon className="w-6 h-6 text-emerald-400" />
                Live Booking Calendar & Appointments
              </h1>
              <p className="text-xs text-slate-400 mt-1">
                Real-time appointment schedule synchronized with AI Voice conversations and admin actions.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => setShowSlotChecker(true)}
                className="px-3.5 py-2 rounded-xl text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition-colors flex items-center gap-1.5"
              >
                <Clock className="w-4 h-4 text-emerald-400" /> Slot Availability
              </button>
              <button
                onClick={() => setShowNewModal(true)}
                className="px-4 py-2 rounded-xl text-xs font-bold bg-emerald-500 hover:bg-emerald-600 text-slate-950 shadow-lg shadow-emerald-500/20 transition-all flex items-center gap-1.5"
              >
                <Plus className="w-4 h-4" /> New Booking
              </button>
              <Link
                href="/admin"
                className="px-3 py-2 rounded-xl text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors"
              >
                Dashboard
              </Link>
            </div>
          </div>

          {/* KPI Stat Cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="bg-slate-900/80 border border-slate-800 rounded-2xl p-4">
              <span className="text-xs font-medium text-slate-400 block">Total Bookings</span>
              <span className="text-2xl font-black text-white mt-1 block">{totalCount}</span>
            </div>
            <div className="bg-slate-900/80 border border-emerald-500/30 rounded-2xl p-4">
              <span className="text-xs font-medium text-emerald-400 block flex items-center gap-1">
                <CheckCircle2 className="w-3.5 h-3.5" /> Confirmed Visits
              </span>
              <span className="text-2xl font-black text-emerald-300 mt-1 block">{confirmedCount}</span>
            </div>
            <div className="bg-slate-900/80 border border-amber-500/30 rounded-2xl p-4">
              <span className="text-xs font-medium text-amber-400 block flex items-center gap-1">
                <RotateCw className="w-3.5 h-3.5" /> Rescheduled
              </span>
              <span className="text-2xl font-black text-amber-300 mt-1 block">{rescheduledCount}</span>
            </div>
            <div className="bg-slate-900/80 border border-rose-500/30 rounded-2xl p-4">
              <span className="text-xs font-medium text-rose-400 block flex items-center gap-1">
                <XCircle className="w-3.5 h-3.5" /> Cancelled
              </span>
              <span className="text-2xl font-black text-rose-400 mt-1 block">{cancelledCount}</span>
            </div>
          </div>

          {/* Filter Bar & View Toggle */}
          <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-4 flex flex-col md:flex-row md:items-center md:justify-between gap-4">
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative">
                <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
                <input
                  type="text"
                  placeholder="Search customer, property, phone..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-9 pr-3 py-1.5 rounded-xl bg-slate-950 border border-slate-700 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-emerald-500 w-56 sm:w-64"
                />
              </div>

              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="px-3 py-1.5 rounded-xl bg-slate-950 border border-slate-700 text-xs text-slate-200 focus:outline-none focus:border-emerald-500"
              >
                <option value="all">All Statuses</option>
                <option value="confirmed">Confirmed</option>
                <option value="rescheduled">Rescheduled</option>
                <option value="cancelled">Cancelled</option>
              </select>

              {selectedDate && (
                <div className="flex items-center gap-1 px-2.5 py-1 rounded-xl bg-emerald-500/20 text-emerald-300 text-xs border border-emerald-500/30">
                  <span>Filtered: {selectedDate}</span>
                  <button onClick={() => setSelectedDate(null)} className="hover:text-white">
                    <X className="w-3 h-3" />
                  </button>
                </div>
              )}
            </div>

            <div className="flex items-center gap-2">
              <div className="flex items-center bg-slate-950 rounded-xl p-1 border border-slate-800">
                <button
                  onClick={() => setViewMode("month")}
                  className={`px-3 py-1 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors ${
                    viewMode === "month"
                      ? "bg-emerald-500 text-slate-950"
                      : "text-slate-400 hover:text-white"
                  }`}
                >
                  <CalendarDays className="w-3.5 h-3.5" /> Month
                </button>
                <button
                  onClick={() => setViewMode("list")}
                  className={`px-3 py-1 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors ${
                    viewMode === "list"
                      ? "bg-emerald-500 text-slate-950"
                      : "text-slate-400 hover:text-white"
                  }`}
                >
                  <List className="w-3.5 h-3.5" /> Agenda List
                </button>
              </div>

              <button
                onClick={fetchAppointments}
                className="p-2 text-slate-400 hover:text-white bg-slate-950 border border-slate-800 rounded-xl hover:bg-slate-800"
                title="Refresh appointments"
              >
                <RotateCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
              </button>
            </div>
          </div>

          {/* VIEW: Month Calendar Grid */}
          {viewMode === "month" && (
            <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl">
              {/* Month Navigator */}
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-bold text-white flex items-center gap-2">
                  <span>{monthNames[month]} {year}</span>
                  <button
                    onClick={handleToday}
                    className="px-2.5 py-0.5 text-xs font-semibold rounded-md bg-slate-800 text-slate-300 hover:text-white"
                  >
                    Demo Date
                  </button>
                </h2>
                <div className="flex items-center gap-1">
                  <button
                    onClick={handlePrevMonth}
                    className="p-1.5 rounded-lg bg-slate-800 text-slate-300 hover:text-white"
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                  <button
                    onClick={handleNextMonth}
                    className="p-1.5 rounded-lg bg-slate-800 text-slate-300 hover:text-white"
                  >
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              </div>

              {/* Day Headers */}
              <div className="grid grid-cols-7 gap-2 mb-2 text-center text-xs font-bold text-slate-400 uppercase tracking-wider">
                <div>Sun</div>
                <div>Mon</div>
                <div>Tue</div>
                <div>Wed</div>
                <div>Thu</div>
                <div>Fri</div>
                <div>Sat</div>
              </div>

              {/* Days Grid */}
              <div className="grid grid-cols-7 gap-2">
                {/* Blank days for padding */}
                {Array.from({ length: firstDayIndex }).map((_, i) => (
                  <div key={`blank-${i}`} className="min-h-[100px] rounded-xl bg-slate-950/40 border border-slate-900 p-2 opacity-30" />
                ))}

                {/* Actual Month Days */}
                {Array.from({ length: daysInMonth }).map((_, i) => {
                  const dayNum = i + 1;
                  const dateStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(dayNum).padStart(2, "0")}`;
                  const dayAppts = appointments.filter((a) => a.visit_date === dateStr);
                  const isToday = dateStr === "2026-11-26";
                  const isSelected = selectedDate === dateStr;

                  return (
                    <div
                      key={`day-${dayNum}`}
                      onClick={() => setSelectedDate(isSelected ? null : dateStr)}
                      className={`min-h-[110px] rounded-xl border p-2 flex flex-col justify-between transition-all cursor-pointer ${
                        isSelected
                          ? "bg-slate-800 border-emerald-500 shadow-md shadow-emerald-500/10"
                          : isToday
                          ? "bg-emerald-950/20 border-emerald-500/40"
                          : "bg-slate-950/80 border-slate-800/80 hover:border-slate-700"
                      }`}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span
                          className={`text-xs font-bold w-6 h-6 rounded-full flex items-center justify-center ${
                            isToday ? "bg-emerald-500 text-slate-950" : "text-slate-300"
                          }`}
                        >
                          {dayNum}
                        </span>
                        {dayAppts.length > 0 && (
                          <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-slate-800 text-emerald-400">
                            {dayAppts.length}
                          </span>
                        )}
                      </div>

                      {/* Appointment Chips in Box */}
                      <div className="space-y-1 overflow-y-auto max-h-[70px]">
                        {dayAppts.slice(0, 2).map((a) => (
                          <div
                            key={a.id}
                            className={`px-1.5 py-0.5 rounded text-[10px] font-medium truncate ${
                              a.booking_status === "confirmed"
                                ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                                : a.booking_status === "rescheduled"
                                ? "bg-amber-500/20 text-amber-300 border border-amber-500/30"
                                : "bg-rose-500/20 text-rose-300 border border-rose-500/30"
                            }`}
                            title={`${a.customer_name} - ${a.property_name} (${a.visit_time})`}
                          >
                            {a.visit_time.split(" ")[0]} {a.customer_name}
                          </div>
                        ))}
                        {dayAppts.length > 2 && (
                          <div className="text-[9px] text-slate-400 font-medium pl-1">
                            +{dayAppts.length - 2} more
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Agenda / Appointments List */}
          <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-xl">
            <div className="flex items-center justify-between mb-4 pb-3 border-b border-slate-800">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <List className="w-4 h-4 text-emerald-400" />
                {selectedDate ? `Appointments on ${selectedDate}` : "All Scheduled Appointments"}
                <span className="text-xs font-normal text-slate-400">({displayAppointments.length} bookings)</span>
              </h3>
            </div>

            {loading ? (
              <div className="py-12 text-center text-slate-400">Loading appointments...</div>
            ) : displayAppointments.length === 0 ? (
              <div className="py-12 text-center text-slate-500">
                <CalendarIcon className="w-10 h-10 mx-auto mb-2 opacity-30" />
                <p className="text-sm">No appointments found matching current filters.</p>
              </div>
            ) : (
              <div className="divide-y divide-slate-800">
                {displayAppointments.map((appt) => (
                  <div
                    key={appt.id}
                    className="py-4 flex flex-col md:flex-row md:items-center md:justify-between gap-4 hover:bg-slate-800/30 p-2 rounded-xl transition-colors"
                  >
                    {/* Left: Customer & Property Info */}
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-white text-sm">{appt.customer_name}</span>
                        {appt.contact_number && (
                          <span className="text-xs text-slate-400 flex items-center gap-1">
                            <Phone className="w-3 h-3 text-slate-500" /> {appt.contact_number}
                          </span>
                        )}
                        <span
                          className={`px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                            appt.booking_status === "confirmed"
                              ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30"
                              : appt.booking_status === "rescheduled"
                              ? "bg-amber-500/20 text-amber-300 border border-amber-500/30"
                              : "bg-rose-500/20 text-rose-300 border border-rose-500/30"
                          }`}
                        >
                          {appt.booking_status}
                        </span>
                        <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">
                          {appt.booking_source}
                        </span>
                      </div>

                      <div className="flex flex-wrap items-center gap-3 text-xs text-slate-400">
                        <span className="flex items-center gap-1 font-semibold text-slate-200">
                          <Building2 className="w-3.5 h-3.5 text-emerald-400" /> {appt.property_name}
                        </span>
                        <span className="flex items-center gap-1">
                          <MapPin className="w-3 h-3 text-slate-500" /> {appt.city}
                        </span>
                        <span className="flex items-center gap-1 text-emerald-400 font-medium">
                          <CalendarIcon className="w-3 h-3" /> {appt.visit_date}
                        </span>
                        <span className="flex items-center gap-1 text-slate-300">
                          <Clock className="w-3 h-3 text-slate-500" /> {appt.visit_time}
                        </span>
                      </div>

                      {appt.customer_notes && (
                        <p className="text-xs text-slate-400 italic pl-1 border-l-2 border-slate-700 mt-1">
                          {appt.customer_notes}
                        </p>
                      )}
                    </div>

                    {/* Right: Actions */}
                    <div className="flex items-center gap-2 self-start md:self-auto">
                      {appt.booking_status !== "cancelled" && (
                        <>
                          <button
                            onClick={() => {
                              setRescheduleModalAppt(appt);
                              setNewDate(appt.visit_date);
                              setNewTime(appt.visit_time);
                              setRescheduleReason("");
                            }}
                            className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-amber-300 border border-amber-500/30 transition-colors flex items-center gap-1"
                          >
                            <RotateCw className="w-3 h-3" /> Reschedule
                          </button>
                          <button
                            onClick={() => {
                              setCancelModalAppt(appt);
                              setCancelReason("");
                            }}
                            className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-rose-950/50 text-rose-400 border border-rose-500/30 transition-colors flex items-center gap-1"
                          >
                            <XCircle className="w-3 h-3" /> Cancel
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* MODAL: Reschedule */}
        {rescheduleModalAppt && (
          <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
            <div className="bg-slate-900 border border-slate-700 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl animate-in fade-in">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <h4 className="text-base font-bold text-white flex items-center gap-2">
                  <RotateCw className="w-4 h-4 text-amber-400" /> Reschedule Appointment
                </h4>
                <button onClick={() => setRescheduleModalAppt(null)} className="text-slate-400 hover:text-white">
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div>
                <p className="text-xs text-slate-400">Customer: <strong className="text-white">{rescheduleModalAppt.customer_name}</strong></p>
                <p className="text-xs text-slate-400">Property: <strong className="text-white">{rescheduleModalAppt.property_name}</strong></p>
              </div>

              <div className="space-y-3">
                <div>
                  <label className="text-xs font-semibold text-slate-300 block mb-1">New Visit Date</label>
                  <input
                    type="date"
                    value={newDate}
                    onChange={(e) => setNewDate(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-700 text-xs text-white focus:outline-none focus:border-amber-400"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-300 block mb-1">New Time Slot</label>
                  <select
                    value={newTime}
                    onChange={(e) => setNewTime(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-700 text-xs text-white focus:outline-none focus:border-amber-400"
                  >
                    <option value="10:00 AM - 11:00 AM">10:00 AM - 11:00 AM</option>
                    <option value="11:30 AM - 12:30 PM">11:30 AM - 12:30 PM</option>
                    <option value="02:00 PM - 03:00 PM">02:00 PM - 03:00 PM</option>
                    <option value="03:30 PM - 04:30 PM">03:30 PM - 04:30 PM</option>
                    <option value="05:00 PM - 06:00 PM">05:00 PM - 06:00 PM</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-300 block mb-1">Reason for Rescheduling</label>
                  <input
                    type="text"
                    placeholder="e.g. Customer requested weekend afternoon slot"
                    value={rescheduleReason}
                    onChange={(e) => setRescheduleReason(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-700 text-xs text-white focus:outline-none focus:border-amber-400"
                  />
                </div>
              </div>

              <div className="flex justify-end gap-2 pt-2 border-t border-slate-800">
                <button
                  onClick={() => setRescheduleModalAppt(null)}
                  className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-400 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  onClick={handleRescheduleSubmit}
                  disabled={actionLoading}
                  className="px-4 py-2 rounded-xl text-xs font-bold bg-amber-500 hover:bg-amber-600 text-slate-950"
                >
                  {actionLoading ? "Saving..." : "Confirm Reschedule"}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* MODAL: Cancel */}
        {cancelModalAppt && (
          <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
            <div className="bg-slate-900 border border-slate-700 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl animate-in fade-in">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <h4 className="text-base font-bold text-white flex items-center gap-2">
                  <XCircle className="w-4 h-4 text-rose-400" /> Cancel Appointment
                </h4>
                <button onClick={() => setCancelModalAppt(null)} className="text-slate-400 hover:text-white">
                  <X className="w-5 h-5" />
                </button>
              </div>

              <p className="text-xs text-slate-300">
                Are you sure you want to cancel the appointment for <strong className="text-white">{cancelModalAppt.customer_name}</strong> at <strong className="text-white">{cancelModalAppt.property_name}</strong>?
              </p>

              <div>
                <label className="text-xs font-semibold text-slate-300 block mb-1">Cancellation Reason</label>
                <input
                  type="text"
                  placeholder="e.g. Customer cancelled due to travel"
                  value={cancelReason}
                  onChange={(e) => setCancelReason(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-700 text-xs text-white focus:outline-none focus:border-rose-400"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2 border-t border-slate-800">
                <button
                  onClick={() => setCancelModalAppt(null)}
                  className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-400 hover:text-white"
                >
                  Back
                </button>
                <button
                  onClick={handleCancelSubmit}
                  disabled={actionLoading}
                  className="px-4 py-2 rounded-xl text-xs font-bold bg-rose-600 hover:bg-rose-700 text-white"
                >
                  {actionLoading ? "Cancelling..." : "Confirm Cancellation"}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* MODAL: New Manual Appointment */}
        {showNewModal && (
          <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
            <div className="bg-slate-900 border border-slate-700 rounded-2xl max-w-lg w-full p-6 space-y-4 shadow-2xl animate-in fade-in">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <h4 className="text-base font-bold text-white flex items-center gap-2">
                  <Plus className="w-4 h-4 text-emerald-400" /> Book In-Person Site Visit
                </h4>
                <button onClick={() => setShowNewModal(false)} className="text-slate-400 hover:text-white">
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="col-span-2 sm:col-span-1">
                  <label className="text-xs font-semibold text-slate-300 block mb-1">Customer Full Name *</label>
                  <input
                    type="text"
                    required
                    value={newApptData.customer_name}
                    onChange={(e) => setNewApptData({ ...newApptData, customer_name: e.target.value })}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-700 text-xs text-white focus:outline-none focus:border-emerald-500"
                  />
                </div>
                <div className="col-span-2 sm:col-span-1">
                  <label className="text-xs font-semibold text-slate-300 block mb-1">Contact Phone</label>
                  <input
                    type="text"
                    value={newApptData.contact_number}
                    onChange={(e) => setNewApptData({ ...newApptData, contact_number: e.target.value })}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-700 text-xs text-white focus:outline-none focus:border-emerald-500"
                  />
                </div>
                <div className="col-span-2 sm:col-span-1">
                  <label className="text-xs font-semibold text-slate-300 block mb-1">Property Name *</label>
                  <input
                    type="text"
                    required
                    value={newApptData.property_name}
                    onChange={(e) => setNewApptData({ ...newApptData, property_name: e.target.value })}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-700 text-xs text-white focus:outline-none focus:border-emerald-500"
                  />
                </div>
                <div className="col-span-2 sm:col-span-1">
                  <label className="text-xs font-semibold text-slate-300 block mb-1">City</label>
                  <input
                    type="text"
                    value={newApptData.city}
                    onChange={(e) => setNewApptData({ ...newApptData, city: e.target.value })}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-700 text-xs text-white focus:outline-none focus:border-emerald-500"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-300 block mb-1">Visit Date *</label>
                  <input
                    type="date"
                    required
                    value={newApptData.visit_date}
                    onChange={(e) => setNewApptData({ ...newApptData, visit_date: e.target.value })}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-700 text-xs text-white focus:outline-none focus:border-emerald-500"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-300 block mb-1">Time Slot *</label>
                  <select
                    value={newApptData.visit_time}
                    onChange={(e) => setNewApptData({ ...newApptData, visit_time: e.target.value })}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-700 text-xs text-white focus:outline-none focus:border-emerald-500"
                  >
                    <option value="10:00 AM - 11:00 AM">10:00 AM - 11:00 AM</option>
                    <option value="11:30 AM - 12:30 PM">11:30 AM - 12:30 PM</option>
                    <option value="02:00 PM - 03:00 PM">02:00 PM - 03:00 PM</option>
                    <option value="03:30 PM - 04:30 PM">03:30 PM - 04:30 PM</option>
                    <option value="05:00 PM - 06:00 PM">05:00 PM - 06:00 PM</option>
                  </select>
                </div>
                <div className="col-span-2">
                  <label className="text-xs font-semibold text-slate-300 block mb-1">Customer Requirements / Notes</label>
                  <input
                    type="text"
                    placeholder="e.g. Looking for 3BHK high floor"
                    value={newApptData.customer_notes}
                    onChange={(e) => setNewApptData({ ...newApptData, customer_notes: e.target.value })}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-700 text-xs text-white focus:outline-none focus:border-emerald-500"
                  />
                </div>
              </div>

              <div className="flex justify-end gap-2 pt-2 border-t border-slate-800">
                <button
                  onClick={() => setShowNewModal(false)}
                  className="px-4 py-2 rounded-xl text-xs font-semibold text-slate-400 hover:text-white"
                >
                  Cancel
                </button>
                <button
                  onClick={handleCreateSubmit}
                  disabled={actionLoading}
                  className="px-4 py-2 rounded-xl text-xs font-bold bg-emerald-500 hover:bg-emerald-600 text-slate-950"
                >
                  {actionLoading ? "Booking..." : "Create Appointment"}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* MODAL: Slot Availability Inspector */}
        {showSlotChecker && (
          <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
            <div className="bg-slate-900 border border-slate-700 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl animate-in fade-in">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <h4 className="text-base font-bold text-white flex items-center gap-2">
                  <Clock className="w-4 h-4 text-emerald-400" /> Slot Availability Checker
                </h4>
                <button onClick={() => setShowSlotChecker(false)} className="text-slate-400 hover:text-white">
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div className="space-y-3">
                <div>
                  <label className="text-xs font-semibold text-slate-300 block mb-1">Project Name</label>
                  <input
                    type="text"
                    value={slotCheckProject}
                    onChange={(e) => setSlotCheckProject(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-700 text-xs text-white focus:outline-none focus:border-emerald-500"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-slate-300 block mb-1">Visit Date</label>
                  <input
                    type="date"
                    value={slotCheckDate}
                    onChange={(e) => setSlotCheckDate(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-700 text-xs text-white focus:outline-none focus:border-emerald-500"
                  />
                </div>
                <button
                  onClick={handleCheckSlots}
                  className="w-full py-2 rounded-xl text-xs font-bold bg-emerald-500 hover:bg-emerald-600 text-slate-950"
                >
                  Check Live Slots
                </button>
              </div>

              {slotCheckResult && (
                <div className="pt-3 border-t border-slate-800 space-y-2">
                  <h5 className="text-xs font-bold text-white">Results for {slotCheckResult.property_name} ({slotCheckResult.visit_date})</h5>
                  <div className="text-xs text-emerald-400 font-semibold">
                    Available Slots ({slotCheckResult.total_available}):
                  </div>
                  <div className="grid grid-cols-1 gap-1.5">
                    {slotCheckResult.available_slots.map((s: string) => (
                      <div key={s} className="px-2.5 py-1 rounded-lg bg-emerald-500/10 text-emerald-300 text-xs border border-emerald-500/30 flex items-center justify-between">
                        <span>{s}</span>
                        <span className="text-[10px] text-emerald-400 font-bold">OPEN</span>
                      </div>
                    ))}
                    {slotCheckResult.booked_slots.map((s: string) => (
                      <div key={s} className="px-2.5 py-1 rounded-lg bg-rose-500/10 text-rose-300 text-xs border border-rose-500/30 flex items-center justify-between">
                        <span>{s}</span>
                        <span className="text-[10px] text-rose-400 font-bold">BOOKED</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </ProtectedRoute>
  );
}
