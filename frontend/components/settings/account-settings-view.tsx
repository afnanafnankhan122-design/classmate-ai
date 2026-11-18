"use client";

import React, { useEffect, useState } from "react";
import {
  AlertCircle,
  Bell,
  CheckCircle2,
  ExternalLink,
  GraduationCap,
  KeyRound,
  Loader2,
  LogOut,
  Monitor,
  RefreshCw,
  Save,
  Shield,
  Unlink,
  User as UserIcon,
} from "lucide-react";
import { requestJson } from "@/lib/api";

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
  googleMissingScopes: string[];
  googleEmail?: string | null;
  lastSyncedAt?: string | null;
  onProfileUpdated: () => void;
  onLogout: () => void;
}

export type AccountSettingsTab = "profile" | "security" | "google" | "preferences";

type DeviceSession = {
  id: number;
  device_name: string;
  registered_at: string;
  last_activity: string;
  expires_at: string;
  status: "active" | "revoked" | "expired";
  is_current: boolean;
};

type DeviceSessionList = {
  devices: DeviceSession[];
  active_count: number;
  max_devices: number;
  policy_applies: boolean;
};

export function AccountSettingsView({
  student,
  initialTab = "profile",
  googleConnected,
  googleMissingScopes,
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

  // Device management state
  const [deviceSessions, setDeviceSessions] = useState<DeviceSessionList | null>(null);
  const [devicesLoading, setDevicesLoading] = useState(true);
  const [devicesError, setDevicesError] = useState<string | null>(null);
  const [deviceToRevoke, setDeviceToRevoke] = useState<DeviceSession | null>(null);
  const [revokingDevice, setRevokingDevice] = useState(false);

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

  useEffect(() => {
    if (activeTab !== "security") return;
    let cancelled = false;
    requestJson<DeviceSessionList>("/auth/devices")
      .then((data) => {
        if (!cancelled) setDeviceSessions(data);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setDevicesError(err instanceof Error ? err.message : "Could not load registered devices.");
        }
      })
      .finally(() => {
        if (!cancelled) setDevicesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeTab]);

  async function handleRevokeDevice() {
    if (!deviceToRevoke) return;
    setRevokingDevice(true);
    setDevicesError(null);
    try {
      await requestJson(`/auth/devices/${deviceToRevoke.id}`, { method: "DELETE" });
      setDeviceToRevoke(null);
      setDevicesLoading(true);
      const updated = await requestJson<DeviceSessionList>("/auth/devices");
      setDeviceSessions(updated);
    } catch (err) {
      setDevicesError(err instanceof Error ? err.message : "Could not revoke this device.");
    } finally {
      setDevicesLoading(false);
      setRevokingDevice(false);
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
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign("/api/auth/google/start");
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
              onClick={() => {
                const nextTab = tab.id as typeof activeTab;
                setActiveTab(nextTab);
                if (nextTab === "security" && activeTab !== "security") {
                  setDevicesLoading(true);
                  setDevicesError(null);
                }
              }}
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
              Sessions use signed HTTP-only cookies and a server-registered device record. They expire after 8 hours by default or 14 days when Remember me is enabled.
            </p>
            <div className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 text-xs space-y-2">
              <div className="flex justify-between text-slate-300">
                <span className="text-slate-500">Authentication Method:</span>
                <span className="font-medium text-cyan-300">Session Cookie (SameSite=Lax)</span>
              </div>
              <div className="flex justify-between text-slate-300">
                <span className="text-slate-500">Student Device Limit:</span>
                <span className="font-medium text-cyan-300">2 active devices</span>
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

          <div className="rounded-2xl border border-slate-800 bg-[#111A2B] p-6 shadow-xl">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h3 className="text-sm font-semibold text-white mb-1">Device Management</h3>
                <p className="text-xs text-slate-400">
                  Review registered browsers and revoke a session to remove its access immediately.
                </p>
              </div>
              <span className="w-fit rounded-full border border-cyan-500/30 bg-cyan-500/10 px-3 py-1 text-[11px] font-semibold text-cyan-200">
                {deviceSessions?.policy_applies === false
                  ? "Student device cap not applied"
                  : `Maximum devices: ${deviceSessions?.max_devices ?? 2}`}
              </span>
            </div>

            {devicesError && (
              <div role="alert" className="mt-4 flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-300">
                <AlertCircle className="h-4 w-4 shrink-0" />
                <span>{devicesError}</span>
              </div>
            )}

            {deviceSessions && (
              <>
                <p className="mt-4 text-xs text-slate-300">
                  {deviceSessions.policy_applies
                    ? `${deviceSessions.active_count} of ${deviceSessions.max_devices} device slots are active.`
                    : "Administrator accounts are not subject to the student device limit."}
                </p>
                {deviceSessions.policy_applies && deviceSessions.active_count >= deviceSessions.max_devices && (
                  <p className="mt-2 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs leading-relaxed text-amber-200">
                    You have reached your maximum of 2 registered devices. Sign in from an existing device and revoke an old session before registering another device.
                  </p>
                )}
              </>
            )}

            {devicesLoading && !deviceSessions ? (
              <div className="mt-5 flex items-center gap-2 text-xs text-slate-400">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading registered devices...
              </div>
            ) : deviceSessions?.devices.length ? (
              <ul className="mt-4 space-y-3">
                {deviceSessions.devices.map((device) => (
                  <li
                    key={device.id}
                    className="flex flex-col gap-3 rounded-xl border border-slate-800 bg-slate-900/50 p-4 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="flex min-w-0 items-start gap-3">
                      <div className="mt-0.5 rounded-lg bg-slate-800 p-2 text-cyan-300">
                        <Monitor className="h-4 w-4" />
                      </div>
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-medium text-white">{device.device_name}</span>
                          {device.is_current && (
                            <span className="rounded-full bg-cyan-500/15 px-2 py-0.5 text-[10px] font-semibold text-cyan-200">
                              This device
                            </span>
                          )}
                          <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                            device.status === "active"
                              ? "bg-emerald-500/15 text-emerald-300"
                              : "bg-slate-700 text-slate-300"
                          }`}>
                            {device.status === "active" ? "Active" : device.status === "revoked" ? "Revoked" : "Expired"}
                          </span>
                        </div>
                        <p className="mt-1 text-[11px] text-slate-400">
                          Registered {new Date(device.registered_at).toLocaleString()}
                        </p>
                        <p className="text-[11px] text-slate-400">
                          Last active {new Date(device.last_activity).toLocaleString()}
                        </p>
                      </div>
                    </div>
                    {device.status === "active" && !device.is_current && (
                      <button
                        type="button"
                        onClick={() => setDeviceToRevoke(device)}
                        disabled={revokingDevice}
                        className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-medium text-rose-300 transition hover:bg-rose-500/20 disabled:opacity-50"
                      >
                        <LogOut className="h-3.5 w-3.5" /> Revoke
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            ) : !devicesLoading ? (
              <p className="mt-4 rounded-xl border border-slate-800 bg-slate-900/50 p-4 text-xs text-slate-400">
                No registered devices were found.
              </p>
            ) : null}
            <p className="mt-4 text-[11px] leading-relaxed text-slate-500">
              A device is identified by a secure browser cookie. Separate browser profiles may count as separate devices. If both slots are occupied, revoke another active session before signing in on a new browser.
            </p>
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
                        {googleMissingScopes.length ? "Reconnect required" : "Connected"}
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
                  {googleMissingScopes.length > 0 && (
                    <button
                      onClick={handleConnectGoogle}
                      className="rounded-lg bg-amber-500/15 px-3 py-1.5 text-xs font-medium text-amber-200 hover:bg-amber-500/25"
                    >
                      Reconnect
                    </button>
                  )}
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

            {googleConnected && googleMissingScopes.length > 0 && (
              <div role="alert" className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-100">
                Some Google API scopes are missing. Course synchronization or approved student submission may be limited. Reconnect and approve the exact missing scopes below. Google permission descriptions can look similar while representing different API scopes.
                <ul className="mt-2 list-inside list-disc break-all text-amber-200/80">
                  {googleMissingScopes.map((scope) => <li key={scope}>{scope}</li>)}
                </ul>
              </div>
            )}

            {googleConnected && lastSyncedAt && (
              <p className="mt-3 text-[11px] text-slate-500 border-t border-slate-800/80 pt-2.5">
                Last synchronized: {new Date(lastSyncedAt).toLocaleString("en-US", { timeZone: "Asia/Karachi" })} PKT
              </p>
            )}
          </div>

          <div className="rounded-xl border border-slate-800/80 bg-slate-900/40 p-4 text-xs text-slate-400 space-y-2 leading-relaxed">
            <p className="font-semibold text-slate-300">Google permissions and privacy:</p>
            <p>
              Course access uses <code className="text-cyan-300">classroom.courses.readonly</code>. Student coursework and own-submission access use <code className="text-cyan-300">classroom.coursework.me</code>; no teacher or other-student scopes are requested. Sign-in also uses <code className="text-cyan-300">openid</code>, <code className="text-cyan-300">email</code>, and <code className="text-cyan-300">profile</code>.
            </p>
            <p>
              Submission is optional and only runs after your explicit approval. The student coursework permission also allows attaching and turning in your work; <code className="text-cyan-300">drive.file</code> allows the app to upload the approved PDF. Your Google tokens are encrypted and never shown in logs or responses.
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

      {deviceToRevoke && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-2xl border border-slate-800 bg-[#0F1626] p-6 shadow-2xl">
            <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-rose-500/20 text-rose-400">
              <LogOut className="h-5 w-5" />
            </div>
            <h4 className="text-base font-bold text-white">Revoke this device?</h4>
            <p className="mt-1.5 text-xs leading-relaxed text-slate-400">
              {deviceToRevoke.device_name} will lose access immediately. You can sign in again after a device slot is available.
            </p>
            <div className="mt-5 flex items-center justify-end gap-2.5">
              <button
                type="button"
                onClick={() => setDeviceToRevoke(null)}
                disabled={revokingDevice}
                className="rounded-xl border border-slate-700 bg-slate-800/80 px-4 py-2 text-xs font-medium text-slate-300 hover:bg-slate-700 disabled:opacity-60"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleRevokeDevice}
                disabled={revokingDevice}
                className="rounded-xl bg-rose-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-rose-500 disabled:opacity-60"
              >
                {revokingDevice ? "Revoking..." : "Revoke Device"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
