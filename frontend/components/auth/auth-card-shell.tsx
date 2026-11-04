"use client";

import React from "react";
import { GraduationCap, Sparkles } from "lucide-react";

interface AuthCardShellProps {
  title: string;
  subtitle: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}

export function AuthCardShell({
  title,
  subtitle,
  children,
  footer,
}: AuthCardShellProps) {
  return (
    <div className="relative min-h-screen w-full flex items-center justify-center p-4 sm:p-6 lg:p-8 bg-[#090D16] overflow-hidden">
      {/* Background ambient lighting */}
      <div className="pointer-events-none absolute -top-40 -left-40 h-96 w-96 rounded-full bg-blue-600/15 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-40 -right-40 h-96 w-96 rounded-full bg-indigo-600/15 blur-3xl" />
      <div className="pointer-events-none absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 h-[500px] w-[500px] rounded-full bg-cyan-600/10 blur-[120px]" />

      {/* Decorative subtle grid overlay */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage:
            "linear-gradient(#fff 1px, transparent 1px), linear-gradient(90deg, #fff 1px, transparent 1px)",
          backgroundSize: "32px 32px",
        }}
      />

      {/* Main Glassmorphic Container */}
      <div className="relative w-full max-w-md z-10">
        <div className="relative rounded-2xl border border-slate-800/80 bg-[#0F1626]/90 p-6 sm:p-8 shadow-[0_20px_60px_rgba(0,0,0,0.6)] backdrop-blur-xl">
          {/* Glowing accent border top */}
          <div className="absolute inset-x-6 top-0 h-[1px] bg-gradient-to-r from-transparent via-cyan-400/50 to-transparent" />

          {/* Brand Header */}
          <div className="text-center mb-6">
            <div className="inline-flex items-center justify-center h-12 w-12 rounded-xl bg-gradient-to-tr from-blue-600 via-indigo-600 to-cyan-400 p-[1px] shadow-lg shadow-blue-500/20 mb-3">
              <div className="h-full w-full rounded-[11px] bg-[#0A0F1D] flex items-center justify-center">
                <GraduationCap className="h-6 w-6 text-cyan-300" />
              </div>
            </div>

            <div className="flex items-center justify-center gap-1.5">
              <h1 className="text-xl font-bold tracking-tight text-white">ClassMate AI</h1>
              <span className="inline-flex items-center gap-0.5 rounded-full border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-cyan-300">
                <Sparkles className="h-2.5 w-2.5" />
                Student
              </span>
            </div>

            <p className="mt-1 text-xs font-medium text-slate-400">
              Your Smart Study Companion.
            </p>
          </div>

          {/* Form Header */}
          <div className="mb-6">
            <h2 className="text-lg font-semibold text-white tracking-tight">{title}</h2>
            <p className="mt-1 text-xs text-slate-400 leading-relaxed">{subtitle}</p>
          </div>

          {/* Main Card Content */}
          {children}

          {/* Optional Footer */}
          {footer && <div className="mt-6 pt-5 border-t border-slate-800/80 text-center text-xs text-slate-400">{footer}</div>}
        </div>

        {/* Security badge note */}
        <p className="mt-4 text-center text-[11px] text-slate-400">
          Secured with encrypted credentials & official Google APIs.
        </p>
      </div>
    </div>
  );
}
