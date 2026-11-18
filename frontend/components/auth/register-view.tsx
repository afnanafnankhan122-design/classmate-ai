"use client";

import React, { useMemo, useState } from "react";
import { AlertCircle, Check, Eye, EyeOff, Loader2, Mail, ShieldCheck, User as UserIcon } from "lucide-react";
import { requestJson } from "@/lib/api";
import { AuthCardShell } from "./auth-card-shell";

interface RegisterViewProps {
  onSuccess: () => void;
  onGoogleSignIn: () => void;
  onNavigateLogin: () => void;
}

export function RegisterView({
  onSuccess,
  onGoogleSignIn,
  onNavigateLogin,
}: RegisterViewProps) {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [agreeTerms, setAgreeTerms] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Real-time password strength evaluation
  const strength = useMemo(() => {
    const hasMinLength = password.length >= 8;
    const hasUpper = /[A-Z]/.test(password);
    const hasLower = /[a-z]/.test(password);
    const hasDigitOrSpecial = /[0-9!@#$%^&*(),.?":{}|<>]/.test(password);

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

    return {
      score,
      label,
      color,
      width,
      hasMinLength,
      hasUpper,
      hasLower,
      hasDigitOrSpecial,
    };
  }, [password]);

  const passwordsMatch = confirmPassword.length > 0 && password === confirmPassword;

  function handleGoogleSignIn() {
    if (!agreeTerms) {
      setError("Please agree to the Terms of Use and acknowledge the Privacy Policy before continuing with Google.");
      return;
    }
    onGoogleSignIn();
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const cleanName = fullName.trim();
    const cleanEmail = email.trim().toLowerCase();

    if (!cleanName || cleanName.length < 2) {
      setError("Please enter your full name.");
      return;
    }
    if (!cleanEmail || !cleanEmail.includes("@") || !cleanEmail.includes(".")) {
      setError("Please enter a valid Classroom Email.");
      return;
    }
    if (strength.score < 3) {
      setError("Please choose a stronger password (at least 8 characters, with uppercase and numbers/symbols).");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    if (!agreeTerms) {
      setError("Please agree to the Terms of Service and Privacy Policy.");
      return;
    }

    setLoading(true);
    try {
      await requestJson("/auth/register", {
        method: "POST",
        body: JSON.stringify({
          full_name: cleanName,
          email: cleanEmail,
          password,
          confirm_password: confirmPassword,
          terms_accepted: agreeTerms,
        }),
      });
      onSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed. Please check your information.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthCardShell
      title="Create Student Account"
      subtitle="Register with your Classroom Email to connect courses and organize assignments."
      onGoogleSignIn={handleGoogleSignIn}
      footer={
        <p>
          Already have an account?{" "}
          <button
            type="button"
            onClick={onNavigateLogin}
            className="font-medium text-cyan-400 hover:text-cyan-300 transition underline underline-offset-4"
          >
            Sign In
          </button>
        </p>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-3.5">
        {error && (
          <div className="flex items-start gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-300">
            <AlertCircle className="h-4 w-4 shrink-0 mt-0.5 text-rose-400" />
            <span className="leading-relaxed">{error}</span>
          </div>
        )}

        {/* Full Name */}
        <div>
          <label className="block text-xs font-medium text-slate-300 mb-1">
            Full Name
          </label>
          <div className="relative">
            <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-3 text-slate-500">
              <UserIcon className="h-4 w-4" />
            </div>
            <input
              type="text"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              placeholder="e.g. Afnan Khan"
              autoComplete="name"
              required
              className="w-full rounded-xl border border-slate-700/80 bg-slate-900/70 pl-9 pr-3 py-2 text-sm text-white placeholder-slate-500 transition focus:border-cyan-400 focus:outline-none focus:ring-1 focus:ring-cyan-400"
            />
          </div>
        </div>

        {/* Classroom Email */}
        <div>
          <label className="block text-xs font-medium text-slate-300 mb-1">
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
              className="w-full rounded-xl border border-slate-700/80 bg-slate-900/70 pl-9 pr-3 py-2 text-sm text-white placeholder-slate-500 transition focus:border-cyan-400 focus:outline-none focus:ring-1 focus:ring-cyan-400"
            />
          </div>
          <p className="mt-1 text-[11px] text-slate-400">
            Register using the Google account you use for Google Classroom.
          </p>
        </div>

        {/* Password */}
        <div>
          <label className="block text-xs font-medium text-slate-300 mb-1">
            Password
          </label>
          <div className="relative">
            <input
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Create a secure password"
              autoComplete="new-password"
              required
              className="w-full rounded-xl border border-slate-700/80 bg-slate-900/70 pl-3 pr-10 py-2 text-sm text-white placeholder-slate-500 transition focus:border-cyan-400 focus:outline-none focus:ring-1 focus:ring-cyan-400"
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

          {/* Password strength visual meter */}
          {password.length > 0 && (
            <div className="mt-2 space-y-1.5">
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-slate-400">Password strength:</span>
                <span className="font-semibold text-slate-200">{strength.label}</span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-slate-800 overflow-hidden">
                <div
                  className={`h-full ${strength.color} ${strength.width} transition-all duration-300`}
                />
              </div>
              <div className="grid grid-cols-2 gap-1 pt-1 text-[10px] text-slate-400">
                <span className={strength.hasMinLength ? "text-emerald-400 flex items-center gap-1" : "flex items-center gap-1"}>
                  <Check className="h-2.5 w-2.5" /> 8+ characters
                </span>
                <span className={strength.hasUpper ? "text-emerald-400 flex items-center gap-1" : "flex items-center gap-1"}>
                  <Check className="h-2.5 w-2.5" /> Uppercase letter
                </span>
                <span className={strength.hasLower ? "text-emerald-400 flex items-center gap-1" : "flex items-center gap-1"}>
                  <Check className="h-2.5 w-2.5" /> Lowercase letter
                </span>
                <span className={strength.hasDigitOrSpecial ? "text-emerald-400 flex items-center gap-1" : "flex items-center gap-1"}>
                  <Check className="h-2.5 w-2.5" /> Number / Symbol
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Confirm Password */}
        <div>
          <label className="block text-xs font-medium text-slate-300 mb-1">
            Confirm Password
          </label>
          <div className="relative">
            <input
              type={showPassword ? "text" : "password"}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Re-enter your password"
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

        {/* Terms acceptance */}
        <div className="pt-1">
          <label className="flex items-start gap-2 cursor-pointer text-xs text-slate-300 select-none">
            <input
              type="checkbox"
              checked={agreeTerms}
              onChange={(e) => setAgreeTerms(e.target.checked)}
              required
              aria-describedby="legal-consent-text"
              className="mt-0.5 h-4 w-4 rounded border-slate-700 bg-slate-900 text-cyan-500 focus:ring-cyan-400 focus:ring-offset-0"
            />
            <span id="legal-consent-text" className="leading-relaxed">
              I agree to the{" "}
              <a
                href="/terms"
                target="_blank"
                rel="noreferrer"
                className="text-cyan-300 underline underline-offset-2 hover:text-cyan-200"
              >
                Terms of Use
              </a>{" "}
              and acknowledge that I have read the{" "}
              <a
                href="/privacy"
                target="_blank"
                rel="noreferrer"
                className="text-cyan-300 underline underline-offset-2 hover:text-cyan-200"
              >
                Privacy Policy
              </a>
              .
            </span>
          </label>
        </div>

        {/* Submit button */}
        <button
          type="submit"
          disabled={loading}
          className="w-full flex items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-blue-600 via-indigo-600 to-cyan-500 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-blue-500/25 transition hover:brightness-110 active:scale-[0.99] disabled:opacity-60 disabled:cursor-not-allowed cursor-pointer mt-2"
        >
          {loading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>Creating your account...</span>
            </>
          ) : (
            <>
              <ShieldCheck className="h-4 w-4" />
              <span>Create Account</span>
            </>
          )}
        </button>
      </form>
    </AuthCardShell>
  );
}
