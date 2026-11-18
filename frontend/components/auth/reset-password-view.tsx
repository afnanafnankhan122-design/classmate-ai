"use client";

import React, { useMemo, useState } from "react";
import { AlertCircle, ArrowLeft, Check, CheckCircle2, Eye, EyeOff, KeyRound, Loader2, Lock } from "lucide-react";
import { requestJson } from "@/lib/api";
import { AuthCardShell } from "./auth-card-shell";

interface ResetPasswordViewProps {
  initialToken?: string;
  onNavigateLogin: () => void;
}

export function ResetPasswordView({
  initialToken = "",
  onNavigateLogin,
}: ResetPasswordViewProps) {
  const [token, setToken] = useState(initialToken);
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const strength = useMemo(() => {
    const hasMinLength = newPassword.length >= 8;
    const hasUpper = /[A-Z]/.test(newPassword);
    const hasLower = /[a-z]/.test(newPassword);
    const hasDigitOrSpecial = /[0-9!@#$%^&*(),.?":{}|<>]/.test(newPassword);

    const score = [hasMinLength, hasUpper, hasLower, hasDigitOrSpecial].filter(Boolean).length;
    let label = "Weak";
    let color = "bg-rose-500";
    let width = "w-1/4";

    if (score === 2) {
      label = "Fair";
      color = "bg-amber-500";
      width = "w-2/4";
    } else if (score === 3) {
      label = "Good";
      color = "bg-cyan-500";
      width = "w-3/4";
    } else if (score === 4) {
      label = "Strong";
      color = "bg-emerald-500";
      width = "w-full";
    }

    return { score, label, color, width, hasMinLength, hasUpper, hasLower, hasDigitOrSpecial };
  }, [newPassword]);

  const passwordsMatch = confirmPassword.length > 0 && newPassword === confirmPassword;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    if (!token.trim()) {
      setError("Please provide the recovery token from your email.");
      return;
    }
    if (strength.score < 4) {
      setError("Use at least 8 characters with lowercase, uppercase, and a digit or special character.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);
    try {
      await requestJson("/auth/reset-password", {
        method: "POST",
        body: JSON.stringify({
          token: token.trim(),
          new_password: newPassword,
          confirm_password: confirmPassword,
        }),
      });
      setSuccess(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to reset password. The token may be expired or invalid.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthCardShell
      title="Set New Password"
      subtitle="Use the one-time link in your recovery email and choose a new, strong password."
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
      {success ? (
        <div className="space-y-4">
          <div className="flex items-start gap-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 text-xs text-emerald-200">
            <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-400 mt-0.5" />
            <div className="space-y-1">
              <p className="font-semibold text-emerald-300 text-sm">Password Updated!</p>
              <p className="text-slate-300 leading-relaxed">
                Your ClassMate AI account password has been reset successfully. You can now log in with your new credentials.
              </p>
            </div>
          </div>

          <button
            type="button"
            onClick={onNavigateLogin}
            className="w-full flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-blue-600 to-cyan-500 px-4 py-2.5 text-sm font-semibold text-white shadow-lg transition hover:brightness-110 active:scale-[0.99] cursor-pointer"
          >
            <span>Proceed to Sign In</span>
          </button>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4" aria-busy={loading}>
          {error && (
            <div className="flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-300">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5 text-rose-400" />
              <span>{error}</span>
            </div>
          )}

          {/* Reset Token */}
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">
              Recovery Token
            </label>
            <div className="relative">
              <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-slate-500">
                <KeyRound className="h-4 w-4" />
              </div>
              <input
                type="text"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="Paste the reset token"
                required
                className="w-full rounded-xl border border-slate-700/80 bg-slate-900/70 pl-9 pr-3 py-2 text-sm text-white font-mono placeholder-slate-500 transition focus:border-cyan-400 focus:outline-none focus:ring-1 focus:ring-cyan-400"
              />
            </div>
            <p className="mt-1 text-[11px] text-slate-400">
              Reset links are single-use and expire after 30 minutes. If this link is expired or invalid, request another from Sign In.
            </p>
          </div>

          {/* New Password */}
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">
              New Password
            </label>
            <div className="relative">
              <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-slate-500">
                <Lock className="h-4 w-4" />
              </div>
              <input
                type={showPassword ? "text" : "password"}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="Enter new password"
                autoComplete="new-password"
                required
                className="w-full rounded-xl border border-slate-700/80 bg-slate-900/70 pl-9 pr-10 py-2 text-sm text-white placeholder-slate-500 transition focus:border-cyan-400 focus:outline-none focus:ring-1 focus:ring-cyan-400"
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="absolute inset-y-0 right-0 flex items-center pr-3 text-slate-500 hover:text-slate-300 transition"
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>

            {/* Strength meter */}
            {newPassword.length > 0 && (
              <div className="mt-2 space-y-1">
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-slate-400">Strength:</span>
                  <span className="font-semibold text-slate-200">{strength.label}</span>
                </div>
                <div className="h-1.5 w-full rounded-full bg-slate-800 overflow-hidden">
                  <div className={`h-full ${strength.color} ${strength.width} transition-all duration-300`} />
                </div>
              </div>
            )}
          </div>

          {/* Confirm Password */}
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">
              Confirm New Password
            </label>
            <div className="relative">
              <input
                type={showPassword ? "text" : "password"}
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Re-enter new password"
                autoComplete="new-password"
                required
                className={`w-full rounded-xl border bg-slate-900/70 pl-3 pr-9 py-2 text-sm text-white placeholder-slate-500 transition focus:outline-none focus:ring-1 ${
                  confirmPassword.length > 0
                    ? passwordsMatch
                      ? "border-emerald-500/80 focus:border-emerald-400 focus:ring-emerald-400"
                      : "border-rose-500/80 focus:border-rose-400 focus:ring-rose-400"
                    : "border-slate-700/80 focus:border-cyan-400 focus:ring-cyan-400"
                }`}
              />
              {confirmPassword.length > 0 && (
                <div className="absolute inset-y-0 right-0 flex items-center pr-3 pointer-events-none">
                  {passwordsMatch ? (
                    <Check className="h-4 w-4 text-emerald-400" />
                  ) : (
                    <AlertCircle className="h-4 w-4 text-rose-400" />
                  )}
                </div>
              )}
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-blue-600 to-cyan-500 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-blue-500/25 transition hover:brightness-110 active:scale-[0.99] disabled:opacity-60 cursor-pointer"
          >
            {loading ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                <span>Updating password...</span>
              </>
            ) : (
              <>
                <KeyRound className="h-4 w-4" />
                <span>Save New Password</span>
              </>
            )}
          </button>
        </form>
      )}
    </AuthCardShell>
  );
}
