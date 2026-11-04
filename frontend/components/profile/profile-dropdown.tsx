"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  ChevronDown,
  GraduationCap,
  KeyRound,
  LogOut,
  Settings,
  User as UserIcon,
} from "lucide-react";

interface StudentInfo {
  id?: number;
  full_name: string;
  email: string;
  roll_number?: string | null;
  department?: string | null;
  semester?: string | null;
}

interface ProfileDropdownProps {
  student: StudentInfo;
  googleConnected: boolean;
  googleEmail?: string | null;
  onNavigateSettings: (tab?: "profile" | "security" | "google" | "preferences") => void;
  onLogout: () => void;
}

export function ProfileDropdown({
  student,
  googleConnected,
  googleEmail,
  onNavigateSettings,
  onLogout,
}: ProfileDropdownProps) {
  const [open, setOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [open]);

  // Compute student initials
  const initials = student.full_name
    ? student.full_name
        .split(" ")
        .map((p) => p[0])
        .slice(0, 2)
        .join("")
        .toUpperCase()
    : "ST";

  return (
    <div className="relative" ref={dropdownRef}>
      {/* Trigger Button */}
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-2.5 rounded-xl border border-slate-700/80 bg-slate-800/60 pl-2 pr-3 py-1.5 transition hover:bg-slate-800 hover:border-slate-600 focus:outline-none focus:ring-2 focus:ring-cyan-500/40 cursor-pointer"
        aria-expanded={open}
        aria-haspopup="true"
      >
        <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-tr from-blue-600 to-cyan-400 text-xs font-bold text-white shadow-sm shadow-blue-500/30">
          {initials}
        </div>
        <div className="hidden sm:block text-left">
          <p className="text-xs font-semibold text-white leading-tight truncate max-w-[120px]">
            {student.full_name}
          </p>
          <p className="text-[10px] text-slate-400 truncate max-w-[120px]">
            {student.email}
          </p>
        </div>
        <ChevronDown className={`h-3.5 w-3.5 text-slate-400 transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
      </button>

      {/* Dropdown Menu */}
      {open && (
        <div className="absolute right-0 mt-2 w-64 rounded-2xl border border-slate-800 bg-[#0F1626]/95 p-2 shadow-2xl backdrop-blur-xl z-50 animate-in fade-in zoom-in-95 duration-150">
          {/* Header section with student info */}
          <div className="border-b border-slate-800/80 px-3 py-2.5 mb-1">
            <p className="text-xs font-bold text-white leading-snug truncate">
              {student.full_name}
            </p>
            <p className="text-[11px] text-slate-400 truncate">
              {student.email}
            </p>
            {student.department && (
              <span className="mt-1.5 inline-block rounded-md bg-slate-800/80 px-2 py-0.5 text-[10px] text-cyan-300 font-medium">
                {student.department} {student.semester ? `• ${student.semester}` : ""}
              </span>
            )}
          </div>

          {/* Google Classroom Connection Status Pill */}
          <div className="px-3 py-2 my-1 rounded-xl bg-slate-900/60 border border-slate-800/60 text-xs">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-slate-300 text-[11px]">
                <GraduationCap className="h-3.5 w-3.5 text-cyan-400" />
                <span>Classroom</span>
              </span>
              {googleConnected ? (
                <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-[9px] font-semibold text-emerald-300 border border-emerald-500/30">
                  Connected
                </span>
              ) : (
                <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[9px] font-medium text-slate-400">
                  Not Linked
                </span>
              )}
            </div>
            {googleConnected && googleEmail && (
              <p className="text-[10px] text-slate-500 truncate mt-1">
                {googleEmail}
              </p>
            )}
          </div>

          {/* Menu Items */}
          <div className="space-y-0.5 pt-1">
            <button
              onClick={() => {
                setOpen(false);
                onNavigateSettings("profile");
              }}
              className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-xs font-medium text-slate-200 hover:bg-slate-800/80 hover:text-white transition cursor-pointer text-left"
            >
              <UserIcon className="h-4 w-4 text-blue-400" />
              <span>Student Profile</span>
            </button>

            <button
              onClick={() => {
                setOpen(false);
                onNavigateSettings("security");
              }}
              className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-xs font-medium text-slate-200 hover:bg-slate-800/80 hover:text-white transition cursor-pointer text-left"
            >
              <KeyRound className="h-4 w-4 text-cyan-400" />
              <span>Change Password</span>
            </button>

            <button
              onClick={() => {
                setOpen(false);
                onNavigateSettings("google");
              }}
              className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-xs font-medium text-slate-200 hover:bg-slate-800/80 hover:text-white transition cursor-pointer text-left"
            >
              <Settings className="h-4 w-4 text-slate-400" />
              <span>Account & Settings</span>
            </button>
          </div>

          {/* Divider */}
          <div className="my-1.5 border-t border-slate-800/80" />

          {/* Logout */}
          <button
            onClick={() => {
              setOpen(false);
              onLogout();
            }}
            className="flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-xs font-medium text-rose-300 hover:bg-rose-500/10 hover:text-rose-200 transition cursor-pointer text-left"
          >
            <LogOut className="h-4 w-4 text-rose-400" />
            <span>Sign Out</span>
          </button>
        </div>
      )}
    </div>
  );
}
