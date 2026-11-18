"use client";

import React, { useState } from "react";
import { AlertCircle, ArrowLeft, CheckCircle2, KeyRound, Loader2, Mail } from "lucide-react";
import { requestJson } from "@/lib/api";
import { AuthCardShell } from "./auth-card-shell";

interface ForgotPasswordViewProps {
  onNavigateLogin: () => void;
}

export function ForgotPasswordView({
  onNavigateLogin,
}: ForgotPasswordViewProps) {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [emailDeliveryConfigured, setEmailDeliveryConfigured] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const cleanEmail = email.trim().toLowerCase();
    if (!cleanEmail || !cleanEmail.includes("@") || !cleanEmail.includes(".")) {
      setError("Please enter a valid Classroom Email.");
      return;
    }

    setLoading(true);
    try {
      const response = await requestJson<{
        status: string;
        message: string;
        email_delivery_configured: boolean;
      }>("/auth/forgot-password", {
        method: "POST",
        body: JSON.stringify({ email: cleanEmail }),
      });
      setEmailDeliveryConfigured(response.email_delivery_configured);
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to process request. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthCardShell
      title="Reset Your Password"
      subtitle="Enter the email address used for your password-enabled ClassMate AI account."
      footer={
        <button
          type="button"
          onClick={onNavigateLogin}
          className="inline-flex items-center gap-1.5 font-medium text-slate-400 hover:text-white transition"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          <span>Back to Sign In</span>
        </button>
      }
    >
      {submitted ? (
        <div className="space-y-4">
          <div className="flex items-start gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 text-xs text-emerald-200">
            <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-400 mt-0.5" />
            <div className="space-y-1">
              <p className="font-semibold text-emerald-300 text-sm">Recovery Request Received</p>
              <p className="text-slate-300 leading-relaxed">
                If an account exists and supports password sign-in, follow the reset instructions if they arrive. Google-only accounts should continue with Google Sign-In.
              </p>
            </div>
          </div>
          {emailDeliveryConfigured ? (
            <p className="text-xs leading-relaxed text-slate-400">
              If your account is eligible, check your inbox and spam folder. The link expires after 30 minutes.
            </p>
          ) : (
            <p role="status" className="text-xs leading-relaxed text-amber-200">
              Password recovery email is not configured on this deployment. Contact support or use Google Sign-In if your account uses Google.
            </p>
          )}
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4" aria-busy={loading}>
          {error && (
            <div className="flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-300">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5 text-rose-400" />
              <span>{error}</span>
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">
              Classroom Email
            </label>
            <div className="relative">
              <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-slate-500">
                <Mail className="h-4 w-4" />
              </div>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="student@gmail.com or student@aust.edu.pk"
                autoComplete="email"
                required
                className="w-full rounded-xl border border-slate-700/80 bg-slate-900/70 pl-9 pr-3 py-2.5 text-sm text-white placeholder-slate-500 transition focus:border-cyan-400 focus:outline-none focus:ring-1 focus:ring-cyan-400"
              />
            </div>
            <p className="mt-1 text-[11px] text-slate-400">
              Enter the Classroom Email you used to register.
            </p>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-blue-600 to-cyan-500 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-blue-500/25 transition hover:brightness-110 active:scale-[0.99] disabled:opacity-60 cursor-pointer"
          >
            {loading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                <span>Processing...</span>
              </>
            ) : (
              <>
                <KeyRound className="h-4 w-4" />
                <span>Request Recovery Instructions</span>
              </>
            )}
          </button>
        </form>
      )}
    </AuthCardShell>
  );
}
