import "./globals.css";
import React from "react";
import { AuthProvider } from "@/lib/auth-context";
import { Navbar } from "@/components/Navbar";
import { RobotVoiceWidget } from "@/components/RobotVoiceWidget";

export const metadata = {
  title: "Real Estate Agentic Voice AI",
  description: "Production Voice AI Agent powered by Amazon Nova 2.5 Sonic",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-slate-50 min-h-screen text-slate-900 font-sans antialiased">
        <AuthProvider>
          <Navbar />
          <main className="min-h-[calc(100vh-4rem)]">{children}</main>
          <RobotVoiceWidget />
        </AuthProvider>
      </body>
    </html>
  );
}
