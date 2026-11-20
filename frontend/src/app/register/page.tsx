"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Lock,
  Mail,
  ShieldCheck,
  CheckCircle2,
  XCircle,
  AlertCircle,
  ArrowRight,
  ArrowLeft,
  User,
  Phone,
  KeyRound,
  RotateCcw,
  Clock,
  Mic,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";

export default function RegisterPage() {
  const { register, customerOnboard, requestOtp, verifyOtp } = useAuth();
  const router = useRouter();

  // Tab: "customer" (Default) | "admin"
  const [activeTab, setActiveTab] = useState<"customer" | "admin">("customer");

  // Admin registration state
  const [adminEmail, setAdminEmail] = useState("");
  const [password, setPassword] = useState("");
  const [adminLoading, setAdminLoading] = useState(false);
  const [adminSuccess, setAdminSuccess] = useState(false);

  // Customer onboarding & OTP state
  const [customerName, setCustomerName] = useState("");
  const [customerPhone, setCustomerPhone] = useState("");
  const [customerEmail, setCustomerEmail] = useState("");
  const [customerOtpStep, setCustomerOtpStep] = useState<"details" | "verify">("details");
  const [otpCode, setOtpCode] = useState("");
  const [onboardingToken, setOnboardingToken] = useState<string | null>(null);
  const [resendCooldown, setResendCooldown] = useState(0);

  // Status & error states
  const [error, setError] = useState<string | null>(null);
  const [infoMessage, setInfoMessage] = useState<string | null>(null);
  const [customerSubmitting, setCustomerSubmitting] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [resending, setResending] = useState(false);

  // Real-time password policy checks (Argon2id compliant)
  const checks = {
    length: password.length >= 8,
    upper: /[A-Z]/.test(password),
    lower: /[a-z]/.test(password),
    digit: /\d/.test(password),
    special: /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(password),
  };
  const isPasswordValid = Object.values(checks).every(Boolean);

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

  // Handle Admin Setup Submit
  const handleAdminSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isPasswordValid) {
      setError("Please ensure your password meets all complexity requirements.");
      return;
    }

    setError(null);
    setAdminLoading(true);

    try {
      await register(adminEmail, password, "admin");
      setAdminSuccess(true);
      setTimeout(() => {
        router.push("/login");
      }, 1500);
    } catch (err: any) {
      setError(err.message || "Administrator provisioning failed. Please verify credentials.");
    } finally {
      setAdminLoading(false);
    }
  };

  // Handle Customer Details Submit
  const handleCustomerSubmit = async (e: React.FormEvent) => {
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
      setInfoMessage(`A 6-digit verification code has been sent to ${cleanEmail}.`);
      setCustomerOtpStep("verify");
    } catch (err: any) {
      setError(err.message || "Failed to initialize customer registration. Please try again.");
    } finally {
      setCustomerSubmitting(false);
    }
  };

  // Handle Customer OTP Verify
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
            href="/login"
            className="inline-flex items-center text-xs font-semibold text-slate-500 hover:text-slate-800 mb-4 transition-colors"
          >
            <ArrowLeft className="w-3.5 h-3.5 mr-1.5" />
            Back to Sign In
          </Link>

          {/* Mode Switcher */}
          <div className="flex rounded-xl bg-slate-100 p-1 mb-6 text-xs font-semibold">
            <button
              type="button"
              onClick={() => {
                setActiveTab("customer");
                setError(null);
                setInfoMessage(null);
              }}
              className={`flex-1 py-2 rounded-lg transition-all flex items-center justify-center space-x-1.5 ${
                activeTab === "customer" ? "bg-white text-sky-700 shadow-sm font-bold" : "text-slate-600 hover:text-slate-900"
              }`}
            >
              <Mic className="w-3.5 h-3.5" />
              <span>Customer Voice Access</span>
            </button>
            <button
              type="button"
              onClick={() => {
                setActiveTab("admin");
                setError(null);
                setInfoMessage(null);
              }}
              className={`flex-1 py-2 rounded-lg transition-all flex items-center justify-center space-x-1.5 ${
                activeTab === "admin" ? "bg-white text-sky-700 shadow-sm font-bold" : "text-slate-600 hover:text-slate-900"
              }`}
            >
              <ShieldCheck className="w-3.5 h-3.5" />
              <span>Administrator Setup</span>
            </button>
          </div>

          <div className="text-center">
            <div
              className={`mx-auto h-12 w-12 rounded-xl flex items-center justify-center text-white shadow-sm mb-3 ${
                activeTab === "customer" ? "bg-sky-600" : "bg-sky-700"
              }`}
            >
              {activeTab === "customer" ? <Mic className="h-6 w-6" /> : <ShieldCheck className="h-7 w-7" />}
            </div>
            <h2 className="text-2xl font-bold text-slate-900 tracking-tight">
              {activeTab === "customer" ? "Customer Voice Registration" : "Administrator Setup"}
            </h2>
            <p className="mt-1 text-xs text-slate-600">
              {activeTab === "customer"
                ? customerOtpStep === "verify"
                  ? `Enter the 6-digit code sent to ${customerEmail}`
                  : "Register with your contact details and receive an Email OTP."
                : "Provision authorized staff credentials for CRM operations."}
            </p>
          </div>
        </div>

        {infoMessage && (
          <div className="p-3.5 rounded-lg bg-sky-50 border border-sky-200 flex items-start space-x-2.5 text-sky-800 text-sm">
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

        {adminSuccess && (
          <div className="p-4 rounded-lg bg-emerald-50 border border-emerald-200 flex items-start space-x-3 text-emerald-700 text-sm">
            <CheckCircle2 className="w-5 h-5 flex-shrink-0 mt-0.5 text-emerald-500" />
            <span>Administrator account registered successfully! Redirecting to login...</span>
          </div>
        )}

        {/* Tab 1: Customer Onboarding + Email OTP */}
        {activeTab === "customer" && (
          <>
            {customerOtpStep === "details" ? (
              <form className="space-y-4" onSubmit={handleCustomerSubmit}>
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
                      className="block w-full pl-9 pr-3 py-2 border border-slate-300 rounded-lg text-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-500"
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
                      className="block w-full pl-9 pr-3 py-2 border border-slate-300 rounded-lg text-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-500"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1.5">
                    Email Address (for verification OTP) <span className="text-red-500">*</span>
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
                      className="block w-full pl-9 pr-3 py-2 border border-slate-300 rounded-lg text-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-500"
                    />
                  </div>
                </div>

                <div className="pt-2">
                  <button
                    type="submit"
                    disabled={customerSubmitting}
                    className="w-full flex items-center justify-center py-2.5 px-4 rounded-lg bg-sky-600 hover:bg-sky-700 text-white font-semibold text-sm shadow-sm transition-colors disabled:opacity-50"
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
              <form onSubmit={handleCustomerVerifyOtp} className="space-y-4">
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
                      className="block w-full py-3 px-4 text-center tracking-[0.5em] text-2xl font-mono font-bold border border-slate-300 rounded-lg placeholder-slate-300 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-500 transition-colors"
                    />
                  </div>
                </div>

                <div>
                  <button
                    type="submit"
                    disabled={verifying || otpCode.length !== 6}
                    className="w-full flex items-center justify-center py-2.5 px-4 rounded-lg bg-sky-600 hover:bg-sky-700 text-white font-semibold text-sm shadow-sm transition-colors disabled:opacity-50"
                  >
                    {verifying ? (
                      <span className="flex items-center space-x-2">
                        <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></span>
                        <span>Verifying Code...</span>
                      </span>
                    ) : (
                      <span className="flex items-center space-x-1.5">
                        <span>Verify & Launch Voice Assistant</span>
                        <ArrowRight className="w-4 h-4" />
                      </span>
                    )}
                  </button>
                </div>

                <div className="pt-4 border-t border-sky-100 flex items-center justify-between text-xs">
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
                    className="font-semibold text-sky-600 hover:text-sky-700 disabled:text-slate-400 transition-colors inline-flex items-center space-x-1"
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

        {/* Tab 2: Administrator Provisioning Form */}
        {activeTab === "admin" && (
          <form className="space-y-4" onSubmit={handleAdminSubmit}>
            <div>
              <label className="block text-xs font-semibold text-slate-700 uppercase tracking-wider mb-1.5">
                Work Email Address
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
                  placeholder="staff@realty.com"
                  className="block w-full pl-9 pr-3 py-2 border border-slate-300 rounded-lg text-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-500"
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
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="block w-full pl-9 pr-3 py-2 border border-slate-300 rounded-lg text-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-500"
                />
              </div>

              {/* Password Policy Checklist */}
              <div className="mt-3 p-3 bg-slate-50 border border-slate-200 rounded-lg text-xs space-y-1.5">
                <p className="font-semibold text-slate-700 mb-1">Argon2id Password Security Rules:</p>
                <div className="grid grid-cols-2 gap-1 text-slate-600">
                  <span className={`flex items-center space-x-1.5 ${checks.length ? "text-emerald-700" : "text-slate-500"}`}>
                    {checks.length ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" /> : <XCircle className="w-3.5 h-3.5" />}
                    <span>8+ characters</span>
                  </span>
                  <span className={`flex items-center space-x-1.5 ${checks.upper ? "text-emerald-700" : "text-slate-500"}`}>
                    {checks.upper ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" /> : <XCircle className="w-3.5 h-3.5" />}
                    <span>Uppercase letter</span>
                  </span>
                  <span className={`flex items-center space-x-1.5 ${checks.lower ? "text-emerald-700" : "text-slate-500"}`}>
                    {checks.lower ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" /> : <XCircle className="w-3.5 h-3.5" />}
                    <span>Lowercase letter</span>
                  </span>
                  <span className={`flex items-center space-x-1.5 ${checks.digit ? "text-emerald-700" : "text-slate-500"}`}>
                    {checks.digit ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" /> : <XCircle className="w-3.5 h-3.5" />}
                    <span>Number</span>
                  </span>
                </div>
                <div className="pt-1 border-t border-slate-200">
                  <span className={`flex items-center space-x-1.5 ${checks.special ? "text-emerald-700" : "text-slate-500"}`}>
                    {checks.special ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" /> : <XCircle className="w-3.5 h-3.5" />}
                    <span>special: Special character (!@#$%^&*)</span>
                  </span>
                </div>
              </div>
            </div>

            <button
              type="submit"
              disabled={adminLoading || !isPasswordValid}
              className="w-full flex justify-center items-center py-2.5 px-4 border border-transparent rounded-lg shadow-sm text-sm font-semibold text-white bg-sky-700 hover:bg-sky-800 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-sky-500 transition-colors disabled:opacity-50"
            >
              {adminLoading ? (
                <span className="flex items-center space-x-2">
                  <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></span>
                  <span>Setting up account...</span>
                </span>
              ) : (
                <span className="flex items-center space-x-1">
                  <span>Complete Admin Setup</span>
                  <ArrowRight className="w-4 h-4 ml-1" />
                </span>
              )}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
