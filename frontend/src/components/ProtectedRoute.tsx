"use client";

import React, { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { ShieldAlert } from "lucide-react";

interface ProtectedRouteProps {
  children: React.ReactNode;
  allowedRoles: ("customer" | "admin" | "super_owner")[];
}

export function ProtectedRoute({ children, allowedRoles }: ProtectedRouteProps) {
  const { session, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !session) {
      router.push("/login");
    }
  }, [session, isLoading, router]);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="flex flex-col items-center space-y-3">
          <div className="w-10 h-10 border-4 border-emerald-600 border-t-transparent rounded-full animate-spin"></div>
          <p className="text-sm font-medium text-slate-500">Authenticating session...</p>
        </div>
      </div>
    );
  }

  if (!session) {
    return null;
  }

  if (!allowedRoles.includes(session.role)) {
    return (
      <div className="min-h-[70vh] flex items-center justify-center p-6">
        <div className="max-w-md w-full bg-white border border-red-200 rounded-xl p-6 shadow-sm text-center">
          <div className="mx-auto w-12 h-12 bg-red-100 rounded-full flex items-center justify-center text-red-600 mb-4">
            <ShieldAlert className="w-6 h-6" />
          </div>
          <h2 className="text-xl font-bold text-slate-900 mb-2">Access Restricted</h2>
          <p className="text-sm text-slate-600 mb-6">
            Your current role (<span className="font-semibold text-slate-800">{session.role}</span>) does not have authorization to view this operational portal.
          </p>
          <button
            onClick={() => {
              if (session.role === "customer") router.push("/customer");
              else if (session.role === "admin") router.push("/admin");
              else router.push("/super-owner");
            }}
            className="w-full bg-slate-900 hover:bg-slate-800 text-white font-medium py-2.5 px-4 rounded-lg transition-colors text-sm"
          >
            Return to Authorized Portal
          </button>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
