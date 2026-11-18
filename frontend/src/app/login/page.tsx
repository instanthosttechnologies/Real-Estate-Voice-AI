"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import {
  Building2,
  Lock,
  Mail,
  AlertCircle,
  ArrowRight,
  ArrowLeft,
  ShieldCheck,
  User,
  Phone,
  KeyRound,
  RotateCcw,
  Clock,
  CheckCircle2,
  Mic,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";

export default function LoginPage() {
  const { login, customerOnboard, requestOtp, verifyOtp } = useAuth();

  // Tab: "admin" | "customer"
  const [activeTab, setActiveTab] = useState<"admin" | "customer">("admin");

  // Admin login state
  const [adminEmail, setAdminEmail] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [adminLoading, setAdminLoading] = useState(false);

  // Customer OTP login state
  const [customerName, setCustomerName] = useState("");
  const [customerPhone, setCustomerPhone] = useState("");
  const [customerEmail, setCustomerEmail] = useState("");
  const [customerOtpStep, setCustomerOtpStep] = useState<"details" | "verify">("details");
  const [otpCode, setOtpCode] = useState("");
  const [onboardingToken, setOnboardingToken] = useState<string | null>(null);
  const [resendCooldown, setResendCooldown] = useState(0);

  // Common UI states
  const [error, setError] = useState<string | null>(null);
  const [infoMessage, setInfoMessage] = useState<string | null>(null);
  const [customerSubmitting, setCustomerSubmitting] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [resending, setResending] = useState(false);

  // Resend cooldown timer
  useEffect(() => {
    if (resendCooldown <= 0) return;
    const interval = setInterval(() => {
      setResendCooldown((prev) => {
        if (prev <= 1) {
          clearInterval(interval);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [resendCooldown]);

  // Handle Admin Sign In
  const handleAdminSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setInfoMessage(null);
    setAdminLoading(true);

    try {
      await login(adminEmail, adminPassword, true);
    } catch (err: any) {
      setError(err.message || "Failed to log in. Please verify your administrative credentials.");
    } finally {
      setAdminLoading(false);
    }
  };

  // Handle Customer Details Submit -> Trigger Email OTP
  const handleCustomerDetailsSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setInfoMessage(null);

    const cleanName = customerName.trim();
    if (cleanName.length < 2) {
      setError("Please enter your full name (minimum 2 characters).");
      return;
    }

    const cleanPhone = customerPhone.replace(/[^\d+]/g, "");
    const phoneDigits = cleanPhone.replace(/\D/g, "");
    if (phoneDigits.length < 7) {
      setError("Please enter a valid mobile number (at least 7 digits).");
      return;
    }

    const cleanEmail = customerEmail.trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cleanEmail)) {
      setError("Please enter a valid email address.");
      return;
    }

    setCustomerSubmitting(true);
    try {
      const onboardSession = await customerOnboard(cleanName, cleanPhone, cleanEmail);
      const token = onboardSession.accessToken;
      setOnboardingToken(token);

      await requestOtp(cleanPhone, "email", token);

      setResendCooldown(60);
      setInfoMessage(`Verification code dispatched to ${cleanEmail}.`);
      setCustomerOtpStep("verify");
    } catch (err: any) {
      setError(err.message || "Failed to initiate customer sign-in. Please verify your details.");
    } finally {
      setCustomerSubmitting(false);
    }
  };

  // Handle Customer OTP Verification
  const handleCustomerVerifyOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setInfoMessage(null);

    const cleanOtp = otpCode.trim();
    if (!/^\d{6}$/.test(cleanOtp)) {
      setError("Please enter a valid 6-digit numeric verification code.");
      return;
    }

    const cleanPhone = customerPhone.replace(/[^\d+]/g, "");
    setVerifying(true);
    try {
      await verifyOtp(cleanOtp, cleanPhone, "email", onboardingToken || undefined);
    } catch (err: any) {
      setError(err.message || "Invalid or expired verification code. Please check and try again.");
    } finally {
      setVerifying(false);
    }
  };

  // Handle Resend OTP
  const handleResendOtp = async () => {
    if (resendCooldown > 0 || resending) return;

    setError(null);
    setInfoMessage(null);
    setResending(true);

    const cleanPhone = customerPhone.replace(/[^\d+]/g, "");
    const cleanEmail = customerEmail.trim().toLowerCase();
    try {
      await requestOtp(cleanPhone, "email", onboardingToken || undefined);
      setResendCooldown(60);
      setInfoMessage(`A fresh verification code has been dispatched to ${cleanEmail}.`);
    } catch (err: any) {
      setError(err.message || "Failed to resend verification code. Please try again later.");
    } finally {
      setResending(false);
    }
  };

  return (
    <div className="min-h-[85vh] flex items-center justify-center px-4 sm:px-6 lg:px-8 py-8 bg-slate-50">
      <div className="max-w-md w-full space-y-6 bg-white p-8 rounded-2xl border border-slate-200 shadow-sm">
        <div>
          <Link
            href="/"
            className="inline-flex items-center text-xs font-semibold text-slate-500 hover:text-slate-800 mb-6 transition-colors"
          >
            <ArrowLeft className="w-3.5 h-3.5 mr-1.5" />
            Back to Welcome
          </Link>

          {/* Mode Tabs */}
          <div className="flex rounded-lg bg-slate-100 p-1 mb-6 text-xs font-semibold">
            <button
              type="button"
              onClick={() => {
                setActiveTab("admin");
                setError(null);
                setInfoMessage(null);
              }}
              className={`flex-1 py-2 rounded-md transition-all flex items-center justify-center space-x-1.5 ${
                activeTab === "admin" ? "bg-white text-slate-900 shadow-sm" : "text-slate-600 hover:text-slate-900"
              }`}
            >
              <ShieldCheck className="w-3.5 h-3.5" />
              <span>Admin Login</span>
            </button>
            <button
              type="button"
              onClick={() => {
                setActiveTab("customer");
                setError(null);
                setInfoMessage(null);
              }}
              className={`flex-1 py-2 rounded-md transition-all flex items-center justify-center space-x-1.5 ${
                activeTab === "customer" ? "bg-white text-slate-900 shadow-sm" : "text-slate-600 hover:text-slate-900"
              }`}
            >
              <Mic className="w-3.5 h-3.5" />
              <span>Customer Sign In</span>
            </button>
          </div>

          <div className="text-center">
            <div
              className={`mx-auto h-12 w-12 rounded-xl flex items-center justify-center text-white shadow-sm mb-4 ${
                activeTab === "admin" ? "bg-slate-900" : "bg-emerald-600"
              }`}
            >
              {activeTab === "admin" ? <ShieldCheck className="h-7 w-7" /> : <Mic className="h-6 w-6" />}
            </div>
            <h2 className="text-2xl font-bold text-slate-900 tracking-tight">
              {activeTab === "admin" ? "Admin Portal Sign In" : "Customer Voice Sign In"}
            </h2>
            <p className="mt-1.5 text-sm text-slate-600">
              {activeTab === "admin"
                ? "Secure access to platform management and operational controls."
                : customerOtpStep === "verify"
                ? `Enter the 6-digit code sent to ${customerEmail}`
                : "Enter your registered contact details to receive an Email OTP."}
            </p>
          </div>
        </div>

        {infoMessage && (
          <div className="p-3.5 rounded-lg bg-emerald-50 border border-emerald-200 flex items-start space-x-2.5 text-emerald-800 text-sm">
            <CheckCircle2 className="w-4 h-4 flex-shrink-0 mt-0.5 text-emerald-600" />
            <span>{infoMessage}</span>
          </div>
        )}

        {error && (
          <div className="p-4 rounded-lg bg-red-50 border border-red-200 flex items-start space-x-3 text-red-700 text-sm">
            <AlertCircle className="w-5 h-5 flex-shrink-0 mt-0.5 text-red-500" />
            <span>{error}</span>
          </div>
        )}

        {/* Tab 1: Admin Credential Login */}
        {activeTab === "admin" && (
          <form className="mt-4 space-y-4" onSubmit={handleAdminSubmit}>
            <div>
              <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1.5">
                Administrator Email
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                  <Mail className="h-4 w-4" />
                </div>
                <input
                  type="email"
                  required
                  value={adminEmail}
                  onChange={(e) => setAdminEmail(e.target.value)}
                  placeholder="admin@realty.com"
                  className="block w-full pl-9 pr-3 py-2.5 border border-slate-300 rounded-lg text-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-900 focus:border-slate-900 transition-colors"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1.5">
                Password
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                  <Lock className="h-4 w-4" />
                </div>
                <input
                  type="password"
                  required
                  value={adminPassword}
                  onChange={(e) => setAdminPassword(e.target.value)}
                  placeholder="••••••••"
                  className="block w-full pl-9 pr-3 py-2.5 border border-slate-300 rounded-lg text-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-slate-900 focus:border-slate-900 transition-colors"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={adminLoading}
              className="w-full flex justify-center items-center py-2.5 px-4 border border-transparent rounded-lg shadow-sm text-sm font-semibold text-white bg-slate-900 hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-slate-900 transition-colors disabled:opacity-50"
            >
              {adminLoading ? (
                <span className="flex items-center space-x-2">
                  <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></span>
                  <span>Authenticating...</span>
                </span>
              ) : (
                <span className="flex items-center space-x-1">
                  <span>Sign in as Administrator</span>
                  <ArrowRight className="w-4 h-4 ml-1" />
                </span>
              )}
            </button>
          </form>
        )}

        {/* Tab 2: Customer Email OTP Login */}
        {activeTab === "customer" && (
          <>
            {customerOtpStep === "details" ? (
              <form onSubmit={handleCustomerDetailsSubmit} className="mt-4 space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1.5">
                    Full Name <span className="text-red-500">*</span>
                  </label>
                  <div className="relative">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                      <User className="h-4 w-4" />
                    </div>
                    <input
                      type="text"
                      required
                      value={customerName}
                      onChange={(e) => setCustomerName(e.target.value)}
                      placeholder="e.g. Ramesh Kumar"
                      className="block w-full pl-9 pr-3 py-2.5 border border-slate-300 rounded-lg text-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 transition-colors"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1.5">
                    Mobile Number <span className="text-red-500">*</span>
                  </label>
                  <div className="relative">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                      <Phone className="h-4 w-4" />
                    </div>
                    <input
                      type="tel"
                      required
                      value={customerPhone}
                      onChange={(e) => setCustomerPhone(e.target.value)}
                      placeholder="+91-9876543210"
                      className="block w-full pl-9 pr-3 py-2.5 border border-slate-300 rounded-lg text-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 transition-colors"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1.5">
                    Registered Email Address <span className="text-red-500">*</span>
                  </label>
                  <div className="relative">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                      <Mail className="h-4 w-4" />
                    </div>
                    <input
                      type="email"
                      required
                      value={customerEmail}
                      onChange={(e) => setCustomerEmail(e.target.value)}
                      placeholder="ramesh.kumar@example.com"
                      className="block w-full pl-9 pr-3 py-2.5 border border-slate-300 rounded-lg text-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 transition-colors"
                    />
                  </div>
                </div>

                <div className="pt-2">
                  <button
                    type="submit"
                    disabled={customerSubmitting}
                    className="w-full flex items-center justify-center py-2.5 px-4 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-sm shadow-sm transition-colors disabled:opacity-50"
                  >
                    {customerSubmitting ? (
                      <span className="flex items-center space-x-2">
                        <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></span>
                        <span>Dispatching Email OTP...</span>
                      </span>
                    ) : (
                      <span className="flex items-center space-x-1.5">
                        <span>Send Verification Code</span>
                        <ArrowRight className="w-4 h-4" />
                      </span>
                    )}
                  </button>
                </div>
              </form>
            ) : (
              <form onSubmit={handleCustomerVerifyOtp} className="mt-4 space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-2">
                    Enter 6-Digit Verification Code
                  </label>
                  <div className="relative">
                    <input
                      type="text"
                      required
                      maxLength={6}
                      autoComplete="one-time-code"
                      value={otpCode}
                      onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                      placeholder="••••••"
                      className="block w-full py-3 px-4 text-center tracking-[0.5em] text-2xl font-mono font-bold border border-slate-300 rounded-lg placeholder-slate-300 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 transition-colors"
                    />
                  </div>
                  <p className="mt-1.5 text-xs text-slate-500 text-center">
                    Check your spam/junk folder if the verification code does not arrive in your inbox.
                  </p>
                </div>

                <div>
                  <button
                    type="submit"
                    disabled={verifying || otpCode.length !== 6}
                    className="w-full flex items-center justify-center py-2.5 px-4 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-sm shadow-sm transition-colors disabled:opacity-50"
                  >
                    {verifying ? (
                      <span className="flex items-center space-x-2">
                        <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></span>
                        <span>Verifying Code...</span>
                      </span>
                    ) : (
                      <span className="flex items-center space-x-1.5">
                        <span>Verify & Sign In</span>
                        <ArrowRight className="w-4 h-4" />
                      </span>
                    )}
                  </button>
                </div>

                <div className="pt-4 border-t border-slate-100 flex items-center justify-between text-xs">
                  <button
                    type="button"
                    onClick={() => {
                      setCustomerOtpStep("details");
                      setError(null);
                      setInfoMessage(null);
                    }}
                    className="text-slate-500 hover:text-slate-800 transition-colors"
                  >
                    Edit details
                  </button>
                  <button
                    type="button"
                    onClick={handleResendOtp}
                    disabled={resendCooldown > 0 || resending}
                    className="font-semibold text-emerald-600 hover:text-emerald-700 disabled:text-slate-400 transition-colors inline-flex items-center space-x-1"
                  >
                    <RotateCcw className={`w-3 h-3 ${resending ? "animate-spin" : ""}`} />
                    <span>
                      {resendCooldown > 0 ? `Resend Code in ${resendCooldown}s` : "Resend Code"}
                    </span>
                  </button>
                </div>
              </form>
            )}
          </>
        )}

        <div className="pt-4 border-t border-slate-200 text-center">
          <p className="text-xs text-slate-500 mb-2">New property buyer or investor?</p>
          <Link
            href="/"
            className="inline-flex items-center text-sm font-semibold text-emerald-600 hover:text-emerald-700 transition-colors"
          >
            Explore with our AI Voice Assistant
            <ArrowRight className="w-3.5 h-3.5 ml-1" />
          </Link>
        </div>
      </div>
    </div>
  );
}
