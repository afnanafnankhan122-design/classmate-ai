"use client";

import React, { useState } from "react";
import {
  AlertCircle,
  Bell,
  CheckCircle2,
  ExternalLink,
  GraduationCap,
  KeyRound,
  Loader2,
  LogOut,
  RefreshCw,
  Save,
  Shield,
  Unlink,
  User as UserIcon,
} from "lucide-react";
import { getApiBase, requestJson } from "@/lib/api";

export type SessionStudent = {
  id: number;
  full_name: string;
  email: string;
  roll_number?: string | null;
  department?: string | null;
  semester?: string | null;
  avatar_url?: string | null;
  email_verified?: boolean;
};

interface AccountSettingsViewProps {
  student: SessionStudent;
  initialTab?: AccountSettingsTab;
  googleConnected: boolean;
  googleEmail?: string | null;
  lastSyncedAt?: string | null;
  onProfileUpdated: () => void;
  onLogout: () => void;
}

export type AccountSettingsTab = "profile" | "security" | "google" | "preferences";

export function AccountSettingsView({
  student,
  initialTab = "profile",
  googleConnected,
  googleEmail,
  lastSyncedAt,
  onProfileUpdated,
  onLogout,
}: AccountSettingsViewProps) {
  const [activeTab, setActiveTab] = useState<AccountSettingsTab>(initialTab);

  // Profile Form state
  const [fullName, setFullName] = useState(student.full_name || "");
  const [rollNumber, setRollNumber] = useState(student.roll_number || "");
  const [department, setDepartment] = useState(student.department || "");
  const [semester, setSemester] = useState(student.semester || "");
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileSuccess, setProfileSuccess] = useState<string | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);

  // Password Form state
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordSaving, setPasswordSaving] = useState(false);
  const [passwordSuccess, setPasswordSuccess] = useState<string | null>(null);
  const [passwordError, setPasswordError] = useState<string | null>(null);

  // Google Action state
  const [syncing, setSyncing] = useState(false);
  const [syncMessage, setSyncMessage] = useState<string | null>(null);
  const [disconnecting, setDisconnecting] = useState(false);
  const [showDisconnectModal, setShowDisconnectModal] = useState(false);

  // Preferences state
  const [dueAlerts, setDueAlerts] = useState(true);
  const [syncAlerts, setSyncAlerts] = useState(true);

  // ── Handle Save Profile ──
  async function handleSaveProfile(e: React.FormEvent) {
    e.preventDefault();
    setProfileSaving(true);
    setProfileError(null);
    setProfileSuccess(null);
    try {
      await requestJson("/auth/profile", {
        method: "PATCH",
        body: JSON.stringify({
          full_name: fullName.trim(),
          roll_number: rollNumber.trim() || null,
          department: department.trim() || null,
          semester: semester.trim() || null,
        }),
      });
      setProfileSuccess("Student profile updated successfully.");
      onProfileUpdated();
    } catch (err) {
      setProfileError(err instanceof Error ? err.message : "Failed to update profile.");
    } finally {
      setProfileSaving(false);
    }
  }

  // ── Handle Change Password ──
  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault();
    setPasswordSaving(true);
    setPasswordError(null);
    setPasswordSuccess(null);

    if (newPassword !== confirmPassword) {
      setPasswordError("New password and confirmation do not match.");
      setPasswordSaving(false);
      return;
    }
    if (newPassword.length < 8) {
      setPasswordError("New password must be at least 8 characters long.");
      setPasswordSaving(false);
      return;
    }

    try {
      await requestJson("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
          confirm_password: confirmPassword,
        }),
      });
      setPasswordSuccess("Password updated successfully.");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err) {
      setPasswordError(err instanceof Error ? err.message : "Failed to change password.");
    } finally {
      setPasswordSaving(false);
    }
  }

  // ── Handle Trigger Sync ──
  async function handleSyncNow() {
    setSyncing(true);
    setSyncMessage(null);
    try {
      await requestJson("/classroom/sync", { method: "POST" });
      setSyncMessage("Google Classroom synchronized successfully.");
      onProfileUpdated();
    } catch (err) {
      setSyncMessage(err instanceof Error ? err.message : "Sync failed.");
    } finally {
      setSyncing(false);
    }
  }

  // ── Handle Disconnect Google ──
  async function handleDisconnectGoogle() {
    setDisconnecting(true);
    try {
      await requestJson("/auth/google/disconnect", { method: "POST" });
      setShowDisconnectModal(false);
      onProfileUpdated();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to disconnect.");
    } finally {
      setDisconnecting(false);
    }
  }

  function handleConnectGoogle() {
    // This leaves Next.js for the backend's external Google OAuth endpoint.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign(`${getApiBase()}/api/auth/google/start`);
  }

  return (
    <div className="space-y-6">
      {/* Settings Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-slate-800 pb-5">
        <div>
          <h2 className="text-xl font-bold text-white tracking-tight">Account & Security Settings</h2>
          <p className="text-xs text-slate-400 mt-1">
            Manage your student credentials, profile details, Google Classroom connection, and preferences.
          </p>
          <p className={`mt-2 text-xs ${student.email_verified ? "text-emerald-300" : "text-amber-300"}`}>
            Classroom Email {student.email_verified ? "verified through Google" : "not yet verified"}
          </p>
        </div>

        <button
          onClick={onLogout}
          className="inline-flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3.5 py-2 text-xs font-medium text-rose-300 hover:bg-rose-500/20 transition cursor-pointer self-start sm:self-auto"
        >
          <LogOut className="h-3.5 w-3.5" />
          <span>Sign Out</span>
        </button>
      </div>

      {/* Tabs Navigation */}
      <div className="flex flex-wrap gap-2 border-b border-slate-800/80 pb-2">
        {[
          { id: "profile", label: "Student Profile", icon: UserIcon },
          { id: "security", label: "Security & Password", icon: Shield },
          { id: "google", label: "Google Classroom", icon: GraduationCap },
          { id: "preferences", label: "Preferences", icon: Bell },
        ].map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as typeof activeTab)}
              className={`flex items-center gap-2 rounded-xl px-4 py-2.5 text-xs font-semibold transition cursor-pointer ${
                isActive
                  ? "bg-gradient-to-r from-blue-600/30 to-cyan-500/20 text-cyan-300 border border-cyan-500/40 shadow-sm shadow-cyan-500/10"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
              }`}
            >
              <Icon className="h-4 w-4" />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* TAB 1: Student Profile */}
      {activeTab === "profile" && (
        <div className="max-w-2xl rounded-2xl border border-slate-800 bg-[#111A2B] p-6 shadow-xl">
          <h3 className="text-sm font-semibold text-white mb-1">Personal & Academic Information</h3>
          <p className="text-xs text-slate-400 mb-6">
            Keep your student academic profile updated for course assignments and PDF generators.
          </p>

          {profileSuccess && (
            <div className="mb-4 flex items-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-300">
              <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
              <span>{profileSuccess}</span>
            </div>
          )}

          {profileError && (
            <div className="mb-4 flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-300">
              <AlertCircle className="h-4 w-4 shrink-0 text-rose-400" />
              <span>{profileError}</span>
            </div>
          )}

          <form onSubmit={handleSaveProfile} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1.5">
                Full Name
              </label>
              <input
                type="text"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                required
                className="w-full rounded-xl border border-slate-700/80 bg-slate-900/80 px-3.5 py-2 text-sm text-white placeholder-slate-500 transition focus:border-cyan-400 focus:outline-none focus:ring-1 focus:ring-cyan-400"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1.5">
                Classroom Email
              </label>
              <input
                type="email"
                value={student.email}
                disabled
                className="w-full rounded-xl border border-slate-800 bg-slate-950/60 px-3.5 py-2 text-sm text-slate-400 cursor-not-allowed"
              />
              <p className="mt-1 text-[11px] text-slate-500">
                Your Classroom Email is linked to your Google Classroom account and cannot be modified directly.
              </p>
            </div>

            <div className="grid sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">
                  Roll / Registration Number
                </label>
                <input
                  type="text"
                  value={rollNumber}
                  onChange={(e) => setRollNumber(e.target.value)}
                  placeholder="e.g. BSSE-2101"
                  className="w-full rounded-xl border border-slate-700/80 bg-slate-900/80 px-3.5 py-2 text-sm text-white placeholder-slate-500 transition focus:border-cyan-400 focus:outline-none focus:ring-1 focus:ring-cyan-400"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">
                  Department
                </label>
                <input
                  type="text"
                  value={department}
                  onChange={(e) => setDepartment(e.target.value)}
                  placeholder="e.g. Software Engineering"
                  className="w-full rounded-xl border border-slate-700/80 bg-slate-900/80 px-3.5 py-2 text-sm text-white placeholder-slate-500 transition focus:border-cyan-400 focus:outline-none focus:ring-1 focus:ring-cyan-400"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-300 mb-1.5">
                Current Semester
              </label>
              <input
                type="text"
                value={semester}
                onChange={(e) => setSemester(e.target.value)}
                placeholder="e.g. 6th Semester"
                className="w-full rounded-xl border border-slate-700/80 bg-slate-900/80 px-3.5 py-2 text-sm text-white placeholder-slate-500 transition focus:border-cyan-400 focus:outline-none focus:ring-1 focus:ring-cyan-400"
              />
            </div>

            <div className="pt-2 flex justify-end">
              <button
                type="submit"
                disabled={profileSaving}
                className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-blue-600 to-cyan-500 px-5 py-2.5 text-xs font-semibold text-white shadow-lg transition hover:brightness-110 active:scale-[0.99] disabled:opacity-60 cursor-pointer"
              >
                {profileSaving ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    <span>Saving Changes...</span>
                  </>
                ) : (
                  <>
                    <Save className="h-3.5 w-3.5" />
                    <span>Save Profile Changes</span>
                  </>
                )}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* TAB 2: Security & Password */}
      {activeTab === "security" && (
        <div className="max-w-2xl space-y-6">
          <div className="rounded-2xl border border-slate-800 bg-[#111A2B] p-6 shadow-xl">
            <h3 className="text-sm font-semibold text-white mb-1">Change Account Password</h3>
            <p className="text-xs text-slate-400 mb-6">
              Ensure your account uses a secure password with at least 8 characters, uppercase letters, and digits.
            </p>

            {passwordSuccess && (
              <div className="mb-4 flex items-center gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-300">
                <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-400" />
                <span>{passwordSuccess}</span>
              </div>
            )}

            {passwordError && (
              <div className="mb-4 flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-300">
                <AlertCircle className="h-4 w-4 shrink-0 text-rose-400" />
                <span>{passwordError}</span>
              </div>
            )}

            <form onSubmit={handleChangePassword} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1.5">
                  Current Password
                </label>
                <input
                  type="password"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  placeholder="Enter current password"
                  autoComplete="current-password"
                  className="w-full rounded-xl border border-slate-700/80 bg-slate-900/80 px-3.5 py-2 text-sm text-white placeholder-slate-500 transition focus:border-cyan-400 focus:outline-none focus:ring-1 focus:ring-cyan-400"
                />
              </div>

              <div className="grid sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1.5">
                    New Password
                  </label>
                  <input
                    type="password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="At least 8 characters"
                    autoComplete="new-password"
                    required
                    className="w-full rounded-xl border border-slate-700/80 bg-slate-900/80 px-3.5 py-2 text-sm text-white placeholder-slate-500 transition focus:border-cyan-400 focus:outline-none focus:ring-1 focus:ring-cyan-400"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-300 mb-1.5">
                    Confirm New Password
                  </label>
                  <input
                    type="password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Repeat new password"
                    autoComplete="new-password"
                    required
                    className="w-full rounded-xl border border-slate-700/80 bg-slate-900/80 px-3.5 py-2 text-sm text-white placeholder-slate-500 transition focus:border-cyan-400 focus:outline-none focus:ring-1 focus:ring-cyan-400"
                  />
                </div>
              </div>

              <div className="pt-2 flex justify-end">
                <button
                  type="submit"
                  disabled={passwordSaving}
                  className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-blue-600 to-cyan-500 px-5 py-2.5 text-xs font-semibold text-white shadow-lg transition hover:brightness-110 active:scale-[0.99] disabled:opacity-60 cursor-pointer"
                >
                  {passwordSaving ? (
                    <>
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      <span>Updating Password...</span>
                    </>
                  ) : (
                    <>
                      <KeyRound className="h-3.5 w-3.5" />
                      <span>Update Password</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>

          {/* Session Overview card */}
          <div className="rounded-2xl border border-slate-800 bg-[#111A2B] p-6 shadow-xl">
            <h3 className="text-sm font-semibold text-white mb-1">Active Session Information</h3>
            <p className="text-xs text-slate-400 mb-4">
              Your session is secured using signed HTTP-only cookies with 14-day persistent lifespan.
            </p>
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 text-xs space-y-2">
              <div className="flex justify-between text-slate-300">
                <span className="text-slate-500">Authentication Method:</span>
                <span className="font-medium text-cyan-300">Session Cookie (SameSite=Lax)</span>
              </div>
              <div className="flex justify-between text-slate-300">
                <span className="text-slate-500">Token Storage:</span>
                <span className="font-medium text-emerald-300">Encrypted at rest (Fernet AES-128-CBC)</span>
              </div>
              <div className="flex justify-between text-slate-300">
                <span className="text-slate-500">Timezone Context:</span>
                <span className="font-medium text-white">Asia/Karachi (PKT, UTC+05:00)</span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TAB 3: Google Classroom */}
      {activeTab === "google" && (
        <div className="max-w-2xl rounded-2xl border border-slate-800 bg-[#111A2B] p-6 shadow-xl space-y-6">
          <div>
            <h3 className="text-sm font-semibold text-white mb-1">Google Classroom Connection</h3>
            <p className="text-xs text-slate-400">
              Synchronize your official enrolled courses, active assignments, and deadlines directly from Google Classroom.
            </p>
          </div>

          {syncMessage && (
            <div className="flex items-center gap-2 rounded-xl border border-cyan-500/30 bg-cyan-500/10 p-3 text-xs text-cyan-300">
              <CheckCircle2 className="h-4 w-4 shrink-0 text-cyan-400" />
              <span>{syncMessage}</span>
            </div>
          )}

          {/* Connection Status Box */}
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-xl bg-slate-800 flex items-center justify-center">
                  <GraduationCap className="h-5 w-5 text-cyan-400" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-white">Google Classroom API</span>
                    {googleConnected ? (
                      <span className="rounded-full bg-emerald-500/20 px-2.5 py-0.5 text-[10px] font-semibold text-emerald-300 border border-emerald-500/30">
                        Connected
                      </span>
                    ) : (
                      <span className="rounded-full bg-slate-700 px-2.5 py-0.5 text-[10px] font-semibold text-slate-400">
                        Not Connected
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-400 mt-0.5">
                    {googleConnected && googleEmail
                      ? `Linked Google Account: ${googleEmail}`
                      : "Connect your student Google account to fetch coursework."}
                  </p>
                </div>
              </div>

              {googleConnected ? (
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleSyncNow}
                    disabled={syncing}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800/80 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-slate-700 transition cursor-pointer"
                  >
                    <RefreshCw className={`h-3.5 w-3.5 ${syncing ? "animate-spin" : ""}`} />
                    <span>Sync</span>
                  </button>
                  <button
                    onClick={() => setShowDisconnectModal(true)}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-1.5 text-xs font-medium text-rose-300 hover:bg-rose-500/20 transition cursor-pointer"
                  >
                    <Unlink className="h-3.5 w-3.5" />
                    <span>Disconnect</span>
                  </button>
                </div>
              ) : (
                <button
                  onClick={handleConnectGoogle}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-blue-600 to-cyan-500 px-4 py-2 text-xs font-semibold text-white shadow transition hover:brightness-110 cursor-pointer"
                >
                  <span>Connect Google</span>
                  <ExternalLink className="h-3 w-3" />
                </button>
              )}
            </div>

            {googleConnected && lastSyncedAt && (
              <p className="mt-3 text-[11px] text-slate-500 border-t border-slate-800/80 pt-2.5">
                Last synchronized: {new Date(lastSyncedAt).toLocaleString("en-US", { timeZone: "Asia/Karachi" })} PKT
              </p>
            )}
          </div>

          <div className="rounded-xl border border-slate-800/80 bg-slate-900/40 p-4 text-xs text-slate-400 space-y-2 leading-relaxed">
            <p className="font-semibold text-slate-300">Privacy & Read-Only Access Guarantee:</p>
            <p>
              ClassMate AI requests read-only permissions (<code className="text-cyan-300">classroom.courses.readonly</code> and <code className="text-cyan-300">classroom.coursework.me.readonly</code>). Your Google account credentials are encrypted with symmetric Fernet encryption and never shared.
            </p>
          </div>
        </div>
      )}

      {/* TAB 4: Preferences */}
      {activeTab === "preferences" && (
        <div className="max-w-2xl rounded-2xl border border-slate-800 bg-[#111A2B] p-6 shadow-xl space-y-6">
          <div>
            <h3 className="text-sm font-semibold text-white mb-1">Application Preferences</h3>
            <p className="text-xs text-slate-400">
              Customize your notifications, display theme, and deadline alert thresholds.
            </p>
          </div>

          <div className="space-y-4">
            <div className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-900/50 p-4">
              <div>
                <p className="text-sm font-medium text-white">Assignments Due Today Alerts</p>
                <p className="text-xs text-slate-400 mt-0.5">
                  Receive in-app reminder badges when an assignment is due on the current day in Pakistan Time.
                </p>
              </div>
              <input
                type="checkbox"
                checked={dueAlerts}
                onChange={(e) => setDueAlerts(e.target.checked)}
                className="h-4 w-4 rounded border-slate-700 bg-slate-900 text-cyan-500 focus:ring-cyan-400 cursor-pointer"
              />
            </div>

            <div className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-900/50 p-4">
              <div>
                <p className="text-sm font-medium text-white">Classroom Sync Notifications</p>
                <p className="text-xs text-slate-400 mt-0.5">
                  Notify whenever new courses or assignments are synchronized from Google Classroom.
                </p>
              </div>
              <input
                type="checkbox"
                checked={syncAlerts}
                onChange={(e) => setSyncAlerts(e.target.checked)}
                className="h-4 w-4 rounded border-slate-700 bg-slate-900 text-cyan-500 focus:ring-cyan-400 cursor-pointer"
              />
            </div>

            <div className="flex items-center justify-between rounded-xl border border-slate-800 bg-slate-900/50 p-4">
              <div>
                <p className="text-sm font-medium text-white">Display Theme</p>
                <p className="text-xs text-slate-400 mt-0.5">
                  ClassMate AI is optimized for high-contrast academic work.
                </p>
              </div>
              <span className="rounded-lg bg-slate-800 px-3 py-1 text-xs font-semibold text-slate-300">
                Premium Dark Navy
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Disconnect Google Confirmation Modal */}
      {showDisconnectModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in">
          <div className="w-full max-w-sm rounded-2xl border border-slate-800 bg-[#0F1626] p-6 shadow-2xl">
            <div className="h-10 w-10 rounded-xl bg-rose-500/20 text-rose-400 flex items-center justify-center mb-3">
              <Unlink className="h-5 w-5" />
            </div>
            <h4 className="text-base font-bold text-white">Disconnect Google Classroom?</h4>
            <p className="text-xs text-slate-400 mt-1.5 leading-relaxed">
              Disconnecting will remove the stored OAuth credentials. Your ClassMate AI student account remains active and you can reconnect anytime.
            </p>
            <div className="mt-5 flex items-center justify-end gap-2.5">
              <button
                type="button"
                onClick={() => setShowDisconnectModal(false)}
                className="rounded-xl border border-slate-700 bg-slate-800/80 px-4 py-2 text-xs font-medium text-slate-300 hover:bg-slate-700 transition cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleDisconnectGoogle}
                disabled={disconnecting}
                className="rounded-xl bg-rose-600 hover:bg-rose-500 px-4 py-2 text-xs font-semibold text-white transition cursor-pointer disabled:opacity-60"
              >
                {disconnecting ? "Disconnecting..." : "Yes, Disconnect"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
