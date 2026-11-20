"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import {
  Mic,
  ShieldCheck,
  User,
  Phone,
  Mail,
  ArrowRight,
  ArrowLeft,
  Sparkles,
  AlertCircle,
  CheckCircle2,
  KeyRound,
  RotateCcw,
  Clock,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";

export default function WelcomePage() {
  const { session, isLoading, customerOnboard, requestOtp, verifyOtp } = useAuth();
  const router = useRouter();

  // Mode: "selection" | "customer_form" | "otp_verification"
  const [viewMode, setViewMode] = useState<"selection" | "customer_form" | "otp_verification">("selection");
  const [isReturning, setIsReturning] = useState(false);

  // Customer form state
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");

  // OTP state
  const [otpCode, setOtpCode] = useState("");
  const [onboardingToken, setOnboardingToken] = useState<string | null>(null);
  const [resendCooldown, setResendCooldown] = useState(0);

  // Status & error states
  const [formError, setFormError] = useState<string | null>(null);
  const [infoMessage, setInfoMessage] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [resending, setResending] = useState(false);

  // If already authenticated with a verified session, redirect to appropriate portal
  useEffect(() => {
    if (!isLoading && session) {
      if (session.role === "customer" && session.isVerified) {
        router.push("/customer");
      } else if (session.role === "admin") {
        router.push("/admin");
      } else if (session.role === "super_owner") {
        router.push("/super-owner");
      }
    }
  }, [session, isLoading, router]);

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

  // Step 1: Submit Customer Onboarding & Trigger Email OTP
  const handleCustomerSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    setInfoMessage(null);

    const cleanName = fullName.trim();
    if (cleanName.length < 2) {
      setFormError("Please enter your full name (minimum 2 characters).");
      return;
    }

    const cleanPhone = phone.replace(/[^\d+]/g, "");
    const phoneDigits = cleanPhone.replace(/\D/g, "");
    if (phoneDigits.length < 7) {
      setFormError("Please enter a valid mobile number (at least 7 digits).");
      return;
    }

    const cleanEmail = email.trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cleanEmail)) {
      setFormError("Please enter a valid email address.");
      return;
    }

    setSubmitting(true);
    try {
      // 1. Obtain unverified onboarding session token
      const onboardSession = await customerOnboard(cleanName, cleanPhone, cleanEmail);
      const token = onboardSession.accessToken;
      setOnboardingToken(token);

      // 2. Automatically request 6-digit Email OTP (Default: Email via Gmail SMTP)
      await requestOtp(cleanPhone, "email", token);

      setResendCooldown(60);
      setInfoMessage(`A 6-digit verification code has been sent to ${cleanEmail}.`);
      setViewMode("otp_verification");
    } catch (err: any) {
      setFormError(err.message || "Failed to initialize verification. Please verify your details.");
    } finally {
      setSubmitting(false);
    }
  };

  // Step 2: Verify OTP
  const handleVerifyOtp = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    setInfoMessage(null);

    const cleanOtp = otpCode.trim();
    if (!/^\d{6}$/.test(cleanOtp)) {
      setFormError("Please enter a valid 6-digit numeric verification code.");
      return;
    }

    const cleanPhone = phone.replace(/[^\d+]/g, "");
    setVerifying(true);
    try {
      await verifyOtp(cleanOtp, cleanPhone, "email", onboardingToken || undefined);
      // verifyOtp handles setting verified token and redirects to /customer
    } catch (err: any) {
      setFormError(err.message || "Invalid or expired verification code. Please check and try again.");
    } finally {
      setVerifying(false);
    }
  };

  // Step 3: Resend OTP
  const handleResendOtp = async () => {
    if (resendCooldown > 0 || resending) return;

    setFormError(null);
    setInfoMessage(null);
    setResending(true);

    const cleanPhone = phone.replace(/[^\d+]/g, "");
    const cleanEmail = email.trim().toLowerCase();
    try {
      await requestOtp(cleanPhone, "email", onboardingToken || undefined);
      setResendCooldown(60);
      setInfoMessage(`A fresh verification code has been dispatched to ${cleanEmail}.`);
    } catch (err: any) {
      setFormError(err.message || "Failed to resend verification code. Please try again later.");
    } finally {
      setResending(false);
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div className="flex flex-col items-center space-y-3">
          <div className="w-10 h-10 border-4 border-emerald-600 border-t-transparent rounded-full animate-spin"></div>
          <p className="text-sm font-medium text-slate-500">Loading Real Estate AI...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-[90vh] flex flex-col justify-center px-4 sm:px-6 lg:px-8 py-10 bg-slate-50">
      <div className="max-w-4xl mx-auto w-full">
        {/* Brand Header */}
        <div className="text-center mb-10">
          <div className="inline-flex items-center space-x-2 px-3.5 py-1.5 rounded-full bg-sky-50 border border-sky-200 text-sky-800 text-xs font-semibold mb-4 shadow-sm">
            <span className="w-2 h-2 rounded-full bg-sky-500 animate-pulse"></span>
            <span>Voice Assistance • Bidirectional Voice AI</span>
          </div>
          <div className="flex items-center justify-center space-x-3 mb-2">
            <Image
              src="/brainmagic-logo.png"
              alt="Brain Magic Logo"
              width={32}
              height={66}
              className="h-10 sm:h-12 w-auto object-contain flex-shrink-0"
              priority
            />
            <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">
              Brain Magic RealEstate Voice AI
            </h1>
          </div>
          <p className="text-base text-slate-600 max-w-xl mx-auto">
            Autonomous multi-turn property intelligence. Speak naturally to search authentic inventory, schedule site visits, and explore real estate.
          </p>
        </div>

        {/* View 1: Welcome & Role Selection */}
        {viewMode === "selection" && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-3xl mx-auto">
            {/* Option 1: I'm a Customer */}
            <div
              onClick={() => {
                setViewMode("customer_form");
                setFormError(null);
                setInfoMessage(null);
              }}
              className="group relative bg-white p-8 rounded-2xl border-2 border-sky-100 hover:border-sky-500 shadow-sm hover:shadow-md transition-all duration-200 cursor-pointer flex flex-col justify-between"
            >
              <div>
                <div className="h-14 w-14 rounded-2xl bg-sky-50 border border-sky-200 flex items-center justify-center text-sky-600 mb-6 group-hover:scale-105 group-hover:bg-sky-600 group-hover:text-white transition-all duration-200 shadow-sm">
                  <Mic className="h-7 w-7" />
                </div>
                <div className="inline-flex items-center text-xs font-semibold text-sky-700 bg-sky-50 px-2.5 py-1 rounded-md mb-2">
                  <Sparkles className="w-3.5 h-3.5 mr-1" />
                  Voice-Only Experience
                </div>
                <h2 className="text-2xl font-bold text-slate-900 mb-2">I&apos;m a Customer</h2>
                <p className="text-slate-600 text-sm mb-6 leading-relaxed">
                  Explore properties with our AI voice assistant. Speak freely to find exact floorplans, verify live pricing, and schedule on-site viewings.
                </p>
              </div>

              <div className="pt-4 border-t border-sky-100 flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-500">Secure Email OTP</span>
                <span className="inline-flex items-center font-semibold text-sm text-sky-600 group-hover:text-sky-700 group-hover:translate-x-0.5 transition-transform">
                  Continue
                  <ArrowRight className="w-4 h-4 ml-1.5" />
                </span>
              </div>
            </div>

            {/* Option 2: Admin Login */}
            <Link
              href="/login"
              className="group relative bg-white p-8 rounded-2xl border-2 border-sky-100 hover:border-sky-400 shadow-sm hover:shadow-md transition-all duration-200 flex flex-col justify-between"
            >
              <div>
                <div className="h-14 w-14 rounded-2xl bg-sky-50 border border-sky-200 flex items-center justify-center text-sky-700 mb-6 group-hover:scale-105 group-hover:bg-sky-700 group-hover:text-white transition-all duration-200 shadow-sm">
                  <ShieldCheck className="h-7 w-7" />
                </div>
                <div className="inline-flex items-center text-xs font-semibold text-sky-700 bg-sky-50 px-2.5 py-1 rounded-md mb-2">
                  Staff & Operations
                </div>
                <h2 className="text-2xl font-bold text-slate-900 mb-2">Admin Login</h2>
                <p className="text-slate-600 text-sm mb-6 leading-relaxed">
                  Secure access to platform management. Monitor high-priority leads, manage CRM property listings, and oversee operational audit logs.
                </p>
              </div>

              <div className="pt-4 border-t border-sky-100 flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-500">Authorized personnel</span>
                <span className="inline-flex items-center font-semibold text-sm text-sky-700 group-hover:text-sky-900 group-hover:translate-x-0.5 transition-transform">
                  Sign In
                  <ArrowRight className="w-4 h-4 ml-1.5" />
                </span>
              </div>
            </Link>
          </div>
        )}

        {/* View 2: Customer Onboarding & Returning Customer Login Form */}
        {viewMode === "customer_form" && (
          <div className="max-w-md mx-auto bg-white p-8 rounded-2xl border border-sky-100 shadow-sm">
            <button
              onClick={() => {
                setViewMode("selection");
                setFormError(null);
                setInfoMessage(null);
              }}
              className="inline-flex items-center text-xs font-semibold text-slate-500 hover:text-slate-800 mb-6 transition-colors"
            >
              <ArrowLeft className="w-3.5 h-3.5 mr-1.5" />
              Back to role selection
            </button>

            {/* Mode Switcher: New Customer vs Returning Customer */}
            <div className="flex rounded-xl bg-slate-100 p-1 mb-6 text-xs font-semibold">
              <button
                type="button"
                onClick={() => {
                  setIsReturning(false);
                  setFormError(null);
                }}
                className={`flex-1 py-1.5 rounded-lg transition-all ${
                  !isReturning ? "bg-white text-sky-700 shadow-sm font-bold" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                New Customer
              </button>
              <button
                type="button"
                onClick={() => {
                  setIsReturning(true);
                  setFormError(null);
                }}
                className={`flex-1 py-1.5 rounded-lg transition-all ${
                  isReturning ? "bg-white text-sky-700 shadow-sm font-bold" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                Returning Customer
              </button>
            </div>

            <div className="mb-6">
              <div className="h-12 w-12 rounded-xl bg-sky-600 flex items-center justify-center text-white mb-3 shadow-sm">
                <Mic className="h-6 w-6" />
              </div>
              <h2 className="text-2xl font-bold text-slate-900">
                {isReturning ? "Customer Sign In" : "Customer Onboarding"}
              </h2>
              <p className="text-sm text-slate-600 mt-1">
                {isReturning
                  ? "Enter your registered contact details to receive your 6-digit Email verification code."
                  : "Provide your contact details to begin your voice session with our 3D AI assistant."}
              </p>
            </div>

            {formError && (
              <div className="mb-5 p-3.5 rounded-lg bg-red-50 border border-red-200 flex items-start space-x-2.5 text-red-700 text-sm">
                <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5 text-red-500" />
                <span>{formError}</span>
              </div>
            )}

            <form onSubmit={handleCustomerSubmit} className="space-y-4">
              {/* Field 1: Full Name */}
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
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="e.g. Ramesh Kumar"
                    className="block w-full pl-9 pr-3 py-2.5 border border-slate-300 rounded-lg text-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-500 transition-colors"
                  />
                </div>
              </div>

              {/* Field 2: Mobile Number */}
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
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    placeholder="+91-9876543210"
                    className="block w-full pl-9 pr-3 py-2.5 border border-slate-300 rounded-lg text-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-500 transition-colors"
                  />
                </div>
              </div>

              {/* Field 3: Email Address */}
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
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="ramesh.kumar@example.com"
                    className="block w-full pl-9 pr-3 py-2.5 border border-slate-300 rounded-lg text-sm placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-500 transition-colors"
                  />
                </div>
              </div>

              <div className="pt-2">
                <button
                  type="submit"
                  disabled={submitting}
                  className="w-full flex items-center justify-center py-2.5 px-4 rounded-lg bg-sky-600 hover:bg-sky-700 text-white font-semibold text-sm shadow-sm transition-colors disabled:opacity-50"
                >
                  {submitting ? (
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

              <div className="flex items-center justify-center space-x-1.5 text-xs text-slate-500 pt-2">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                <span>Passwordless • 6-Digit Email Verification</span>
              </div>
            </form>
          </div>
        )}

        {/* View 3: Six-Digit Email OTP Verification Form */}
        {viewMode === "otp_verification" && (
          <div className="max-w-md mx-auto bg-white p-8 rounded-2xl border border-sky-100 shadow-sm">
            <button
              onClick={() => {
                setViewMode("customer_form");
                setFormError(null);
                setInfoMessage(null);
              }}
              className="inline-flex items-center text-xs font-semibold text-slate-500 hover:text-slate-800 mb-6 transition-colors"
            >
              <ArrowLeft className="w-3.5 h-3.5 mr-1.5" />
              Edit contact details
            </button>

            <div className="mb-6">
              <div className="h-12 w-12 rounded-xl bg-sky-600 flex items-center justify-center text-white mb-3 shadow-sm">
                <KeyRound className="h-6 w-6" />
              </div>
              <h2 className="text-2xl font-bold text-slate-900">Verify Your Identity</h2>
              <p className="text-sm text-slate-600 mt-1">
                We sent a 6-digit verification code to <span className="font-semibold text-slate-900">{email}</span>.
              </p>
            </div>

            {infoMessage && (
              <div className="mb-5 p-3.5 rounded-lg bg-sky-50 border border-sky-200 flex items-start space-x-2.5 text-sky-800 text-sm">
                <CheckCircle2 className="w-4 h-4 flex-shrink-0 mt-0.5 text-emerald-600" />
                <span>{infoMessage}</span>
              </div>
            )}

            {formError && (
              <div className="mb-5 p-3.5 rounded-lg bg-red-50 border border-red-200 flex items-start space-x-2.5 text-red-700 text-sm">
                <AlertCircle className="w-4 h-4 flex-shrink-0 mt-0.5 text-red-500" />
                <span>{formError}</span>
              </div>
            )}

            <form onSubmit={handleVerifyOtp} className="space-y-5">
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
                <p className="mt-1.5 text-xs text-slate-500 text-center">
                  Code expires in 10 minutes. Check your spam/junk folder if not received.
                </p>
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
                      <span>Verify & Access Voice Assistant</span>
                      <ArrowRight className="w-4 h-4" />
                    </span>
                  )}
                </button>
              </div>

              {/* Resend OTP Section */}
              <div className="pt-4 border-t border-sky-100 flex items-center justify-between text-xs">
                <span className="text-slate-500 flex items-center space-x-1">
                  <Clock className="w-3.5 h-3.5 text-slate-400" />
                  <span>Didn&apos;t receive code?</span>
                </span>
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
          </div>
        )}
      </div>
    </div>
  );
}
