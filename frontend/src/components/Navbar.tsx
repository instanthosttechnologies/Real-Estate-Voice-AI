"use client";

import React from "react";
import Link from "next/link";
import { Building2, LogOut, Shield, User as UserIcon } from "lucide-react";
import { useAuth } from "@/lib/auth-context";

export function Navbar() {
  const { session, logout } = useAuth();

  if (!session) return null;

  const roleBadgeColor = {
    customer: "bg-emerald-50 text-emerald-700 border-emerald-200",
    admin: "bg-blue-50 text-blue-700 border-blue-200",
    super_owner: "bg-purple-50 text-purple-700 border-purple-200",
  }[session.role];

  const roleLabel = {
    customer: "Customer Portal",
    admin: "Admin Portal",
    super_owner: "Platform Super Owner",
  }[session.role];

  return (
    <header className="sticky top-0 z-50 bg-white border-b border-slate-200 shadow-sm">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div className="h-10 w-10 rounded-lg bg-emerald-600 flex items-center justify-center text-white shadow-sm">
            <Building2 className="h-6 w-6" />
          </div>
          <div>
            <span className="text-lg font-bold text-slate-900 tracking-tight">RealEstate Voice AI</span>
            <span className="hidden sm:inline-block ml-2 text-xs font-semibold px-2 py-0.5 rounded-full border bg-slate-50 text-slate-600">
              Nova 2.5 Sonic
            </span>
          </div>
        </div>

        <div className="flex items-center space-x-4">
          <span className={`text-xs font-semibold px-2.5 py-1 rounded-full border capitalize ${roleBadgeColor}`}>
            {roleLabel}
          </span>

          <div className="flex items-center space-x-2 text-sm text-slate-600 border-l border-slate-200 pl-4">
            <UserIcon className="h-4 w-4 text-slate-400" />
            <span className="hidden md:inline font-medium text-slate-700">{session.email}</span>
          </div>

          <button
            onClick={() => logout()}
            className="inline-flex items-center space-x-1 text-sm font-medium text-slate-600 hover:text-red-600 px-3 py-1.5 rounded-md hover:bg-slate-50 transition-colors"
            title="Log out"
          >
            <LogOut className="h-4 w-4" />
            <span className="hidden sm:inline">Logout</span>
          </button>
        </div>
      </div>
    </header>
  );
}
