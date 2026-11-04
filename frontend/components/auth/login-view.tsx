"use client";

import React, { useState } from "react";
import { AlertCircle, Eye, EyeOff, Loader2, LogIn, Mail } from "lucide-react";
import { requestJson } from "@/lib/api";
import { AuthCardShell } from "./auth-card-shell";

interface LoginViewProps {
  onSuccess: () => void;
  onNavigateRegister: () => void;
  onNavigateForgotPassword: () => void;
}

export function LoginView({
  onSuccess,
  onNavigateRegister,
  onNavigateForgotPassword,
}: LoginViewProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const cleanEmail = email.trim().toLowerCase();
    if (!cleanEmail || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cleanEmail)) {
      setError("Please enter your Classroom Email.");
      return;
    }
    if (!password) {
      setError("Please enter your password.");
      return;
    }

    setLoading(true);
    try {
      await requestJson("/auth/login", {
        method: "POST",
        body: JSON.stringify({
          email: cleanEmail,
          password,
          remember_me: rememberMe,
        }),
      });
      onSuccess();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Unable to sign in. Check your connection and try again.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthCardShell
      title="Student Sign In"
      subtitle="Access your academic assignments, deadlines, and smart AI workflow."
      footer={
        <p>
          Don&apos;t have an account?{" "}
          <button
            type="button"
            onClick={onNavigateRegister}
            className="font-medium text-cyan-400 hover:text-cyan-300 transition underline underline-offset-4"
          >
            Create an account
          </button>
        </p>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4" aria-busy={loading}>
        {error && (
          <div role="alert" aria-live="polite" className="flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-300">
            <AlertCircle className="h-4 w-4 shrink-0 mt-0.5 text-rose-400" />
            <span className="leading-relaxed">{error}</span>
          </div>
        )}

        {/* Classroom Email */}
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
              autoComplete="username"
              required
              className="w-full rounded-xl border border-slate-700/80 bg-slate-900/70 pl-9 pr-3 py-2.5 text-sm text-white placeholder-slate-500 transition focus:border-cyan-400 focus:outline-none focus:ring-1 focus:ring-cyan-400"
            />
          </div>
          <p className="mt-1 text-[11px] text-slate-400">
            Use the Google account email associated with your Google Classroom.
          </p>
        </div>

        {/* Password */}
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label className="block text-xs font-medium text-slate-300">
              Password
            </label>
            <button
              type="button"
              onClick={onNavigateForgotPassword}
              className="text-[11px] font-medium text-cyan-400 hover:text-cyan-300 transition"
            >
              Forgot password?
            </button>
          </div>
          <div className="relative">
            <input
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter your account password"
              autoComplete="current-password"
              required
              className="w-full rounded-xl border border-slate-700/80 bg-slate-900/70 pl-3 pr-10 py-2.5 text-sm text-white placeholder-slate-500 transition focus:border-cyan-400 focus:outline-none focus:ring-1 focus:ring-cyan-400"
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
        </div>

        {/* Remember Me */}
        <div className="flex items-center">
          <label className="flex items-center gap-2 cursor-pointer text-xs text-slate-300 select-none">
            <input
              type="checkbox"
              checked={rememberMe}
              onChange={(e) => setRememberMe(e.target.checked)}
              className="h-4 w-4 rounded border-slate-700 bg-slate-900 text-cyan-500 focus:ring-cyan-400 focus:ring-offset-0"
            />
            <span>Remember me for 14 days</span>
          </label>
        </div>

        {/* Sign In Button */}
        <button
          type="submit"
          disabled={loading}
          aria-disabled={loading}
          className="w-full flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-blue-600 to-cyan-500 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-blue-500/25 transition hover:brightness-110 active:scale-[0.99] disabled:opacity-60 disabled:cursor-not-allowed cursor-pointer"
        >
          {loading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>Signing in...</span>
            </>
          ) : (
            <>
              <LogIn className="h-4 w-4" />
              <span>Sign In</span>
            </>
          )}
        </button>

        <p className="text-center text-[11px] leading-relaxed text-slate-400">
          Google Classroom is connected separately after you sign in to ClassMate AI.
        </p>
      </form>
    </AuthCardShell>
  );
}
