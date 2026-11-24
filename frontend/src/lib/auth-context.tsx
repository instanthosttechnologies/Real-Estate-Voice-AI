"use client";

import React, { createContext, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, clearStoredSession, getStoredSession, setStoredSession, UserSession } from "./api";

interface AuthContextType {
  session: UserSession | null;
  isLoading: boolean;
  login: (email: string, pass: string, isAdminLogin?: boolean) => Promise<UserSession>;
  customerOnboard: (fullName: string, phone: string, email: string) => Promise<UserSession>;
  requestOtp: (phone?: string, channel?: "email" | "sms", token?: string) => Promise<{ message: string }>;
  verifyOtp: (otpCode: string, phone?: string, channel?: "email" | "sms", token?: string) => Promise<UserSession>;
  register: (email: string, pass: string, role?: string, full_name?: string, phone?: string) => Promise<any>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<UserSession | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    const saved = getStoredSession();
    if (saved) {
      setSession(saved);
    }
    setIsLoading(false);
  }, []);

  const login = async (email: string, pass: string, isAdminLogin = false): Promise<UserSession> => {
    const data = await api.auth.login({ email, password: pass, is_admin_login: isAdminLogin });
    const userSession: UserSession = {
      userId: data.user_id,
      email,
      role: data.role,
      accessToken: data.access_token,
      refreshToken: data.refresh_token,
    };
    setStoredSession(userSession);
    setSession(userSession);

    // Redirect to respective portal
    if (userSession.role === "customer") {
      router.push("/customer");
    } else if (userSession.role === "admin") {
      router.push("/admin");
    } else if (userSession.role === "super_owner") {
      router.push("/super-owner");
    }
    return userSession;
  };

  const customerOnboard = async (fullName: string, phone: string, email: string): Promise<UserSession> => {
    const data = await api.auth.customerOnboard({ full_name: fullName, phone, email });
    const userSession: UserSession = {
      userId: data.customer_id,
      customerId: data.customer_id,
      email: data.email || email,
      fullName: data.full_name,
      phone: data.phone,
      role: "customer",
      accessToken: data.access_token,
      isVerified: false,
    };
    setStoredSession(userSession);
    setSession(userSession);
    // Instruction 5: Do not redirect customers to the protected dashboard before successful verification
    return userSession;
  };

  const requestOtp = async (
    phone?: string,
    channel: "email" | "sms" = "email",
    token?: string
  ): Promise<{ message: string }> => {
    const targetPhone = phone || session?.phone || "";
    const activeToken = token || session?.accessToken || "";
    if (!targetPhone) {
      throw new Error("Phone number is required to request OTP.");
    }
    return await api.auth.requestCustomerOtp(targetPhone, channel, activeToken);
  };

  const verifyOtp = async (
    otpCode: string,
    phone?: string,
    channel: "email" | "sms" = "email",
    token?: string
  ): Promise<UserSession> => {
    const targetPhone = phone || session?.phone || "";
    const activeToken = token || session?.accessToken || "";
    if (!targetPhone) {
      throw new Error("Phone number is required to verify OTP.");
    }
    const data = await api.auth.verifyCustomerOtp(
      { phone: targetPhone, otp_code: otpCode, channel },
      activeToken
    );

    // Instruction 4: Store the verified customer token correctly after successful OTP verification
    const verifiedSession: UserSession = {
      userId: data.customer_id,
      customerId: data.customer_id,
      email: data.email || session?.email || "",
      fullName: data.full_name || session?.fullName || "",
      phone: data.phone || targetPhone,
      role: "customer",
      accessToken: data.access_token,
      isVerified: true,
      refreshToken: session?.refreshToken,
    };
    setStoredSession(verifiedSession);
    setSession(verifiedSession);
    router.push("/customer");
    return verifiedSession;
  };

  const register = async (email: string, pass: string, role = "customer", full_name?: string, phone?: string) => {
    const res = await api.auth.register({ email, password: pass, role, full_name, phone });
    return res;
  };

  const logout = async () => {
    if (session?.refreshToken) {
      await api.auth.logout(session.refreshToken);
    } else {
      clearStoredSession();
    }
    setSession(null);
    router.push("/");
  };

  return (
    <AuthContext.Provider
      value={{
        session,
        isLoading,
        login,
        customerOnboard,
        requestOtp,
        verifyOtp,
        register,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
