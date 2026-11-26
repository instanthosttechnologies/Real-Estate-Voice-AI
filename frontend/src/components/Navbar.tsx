"use client";

import React from "react";
import Link from "next/link";
import Image from "next/image";
import { LogOut, User as UserIcon } from "lucide-react";
import { useAuth } from "@/lib/auth-context";

export function Navbar() {
  const { session, logout } = useAuth();

  if (!session) return null;

  const roleBadgeColor = {
    customer: "bg-emerald-50 text-emerald-700 border-emerald-200",
    admin: "bg-blue-50 text-blue-700 border-blue-200",
    super_owner: "bg-sky-50 text-sky-700 border-sky-200",
  }[session.role];

  const roleLabel = {
    customer: "Customer Portal",
    admin: "Admin Portal",
    super_owner: "Platform Super Owner",
  }[session.role];

  return (
    <header className="sticky top-0 z-50 bg-white/95 backdrop-blur-md border-b border-sky-100 shadow-xs">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <Image
            src="/brainmagic-logo.png"
            alt="Brain Magic Logo"
            width={32}
            height={66}
            className="h-8 md:h-10 w-auto object-contain flex-shrink-0"
            priority
          />
          <div>
            <span className="text-base sm:text-lg font-bold text-slate-900 tracking-tight">
              Brain Magic RealEstate Voice AI
            </span>
          </div>
        </div>

        <div className="flex items-center space-x-4">
          {(session.role === "admin" || session.role === "super_owner") && (
            <Link
              href="/admin/calendar"
              className="text-xs font-semibold text-emerald-700 hover:text-emerald-800 bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 px-2.5 py-1 rounded-full transition-colors hidden sm:inline-flex items-center gap-1"
            >
              Calendar
            </Link>
          )}
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
