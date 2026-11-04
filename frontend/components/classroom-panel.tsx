"use client";

import { startTransition, useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  ArrowUpRight,
  BookOpenText,
  CalendarClock,
  CheckCircle2,
  CircleDashed,
  ExternalLink,
  FileText,
  FolderOpen,
  GraduationCap,
  Layers,
  Link as LinkIcon,
  LoaderCircle,
  LogOut,
  RefreshCw,
  FileVideo,
} from "lucide-react";
import { getApiBase, requestJson } from "@/lib/api";

type UserInfo = {
  full_name: string;
  email: string;
  roll_number: string | null;
  department: string | null;
  semester: string | null;
};

type SessionInfo = {
  authenticated: boolean;
  google_connected: boolean;
  google_oauth_configured: boolean;
  user?: UserInfo;
  google_email?: string | null;
  last_synced_at?: string | null;
};

type CourseInfo = {
  id: string;
  name: string;
  section: string | null;
  course_state?: string;
  alternate_link?: string | null;
  time_zone: string | null;
};

type AttachmentInfo = {
  type: string;
  id?: string;
  title?: string;
  url?: string;
  thumbnail_url?: string;
};

type ClassroomAssignment = {
  id: number;
  google_assignment_id: string;
  title: string;
  description: string | null;
  due_date: string | null;
  due_time: string | null;
  due_today: boolean;
  deadline?: string | null;
  time_zone: string;
  course_id: string | null;
  course_name: string;
  course_section?: string | null;
  course_state?: string;
  alternate_link?: string | null;
  max_points?: number | null;
  attachments: AttachmentInfo[];
  submission_status: string;
  source: "google_classroom";
};

function safeHttpUrl(value: string | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.href : null;
  } catch {
    return null;
  }
}

function formatRelativeSyncTime(isoString: string | null | undefined): string {
  if (!isoString) return "Never synced";
  try {
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return "Recently synced";
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return "Just now";
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    return (
      date.toLocaleDateString("en-US", {
        timeZone: "Asia/Karachi",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }) + " PKT"
    );
  } catch {
    return "Recently synced";
  }
}

function formatPKTDeadline(
  isoDate: string | null | undefined,
  dueTime: string | null | undefined,
  preformatted?: string | null,
): string {
  if (preformatted) return preformatted;
  if (!isoDate) return "No due date specified";
  try {
    const d = new Date(isoDate);
    if (isNaN(d.getTime())) return isoDate;

    const datePart = new Intl.DateTimeFormat("en-US", {
      timeZone: "Asia/Karachi",
      month: "short",
      day: "numeric",
      year: "numeric",
    }).format(d);

    if (!dueTime) {
      return `${datePart} (No due time) PKT`;
    }

    if (dueTime.includes("AM") || dueTime.includes("PM")) {
      return `${datePart}, ${dueTime} PKT`;
    }

    const timePart = new Intl.DateTimeFormat("en-US", {
      timeZone: "Asia/Karachi",
      hour: "numeric",
      minute: "2-digit",
      hour12: true,
    }).format(d);

    return `${datePart}, ${timePart} PKT`;
  } catch {
    return isoDate;
  }
}

function renderAttachmentIcon(type: string) {
  switch (type.toLowerCase()) {
    case "drivefile":
      return <FolderOpen className="h-3.5 w-3.5 text-blue-400 shrink-0" />;
    case "youtubevideo":
      return <FileVideo className="h-3.5 w-3.5 text-rose-400 shrink-0" />;
    case "form":
      return <FileText className="h-3.5 w-3.5 text-purple-400 shrink-0" />;
    default:
      return <LinkIcon className="h-3.5 w-3.5 text-emerald-400 shrink-0" />;
  }
}

function renderSubmissionBadge(status: string) {
  switch (status.toLowerCase()) {
    case "turned_in":
      return (
        <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-medium text-emerald-300">
          <CheckCircle2 className="h-3 w-3" />
          Turned In
        </span>
      );
    case "graded":
    case "returned":
      return (
        <span className="inline-flex items-center gap-1 rounded-full border border-purple-500/30 bg-purple-500/10 px-2 py-0.5 text-[11px] font-medium text-purple-300">
          <CheckCircle2 className="h-3 w-3" />
          Graded
        </span>
      );
    case "unsubmitted":
      return (
        <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[11px] font-medium text-amber-300">
          Unsubmitted
        </span>
      );
    case "assigned":
    default:
      return (
        <span className="inline-flex items-center gap-1 rounded-full border border-sky-500/30 bg-sky-500/10 px-2 py-0.5 text-[11px] font-medium text-sky-300">
          Assigned
        </span>
      );
  }
}

export function ClassroomPanel({
  onSessionChange,
  onDashboardRefresh,
}: {
  onSessionChange: (session: SessionInfo) => void;
  onDashboardRefresh?: () => void;
}) {
  const apiBase = getApiBase();
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [courses, setCourses] = useState<CourseInfo[]>([]);
  const [assignments, setAssignments] = useState<ClassroomAssignment[]>([]);
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [filterView, setFilterView] = useState<"all" | "due_today" | "courses">("all");

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const currentSession = await requestJson<SessionInfo>("/auth/me");
      setSession(currentSession);
      onSessionChange(currentSession);
      setLastSyncedAt(currentSession.last_synced_at ?? null);

      if (!currentSession.authenticated || !currentSession.google_connected) {
        setCourses([]);
        setAssignments([]);
        return;
      }

      const [courseResult, assignmentResult] = await Promise.all([
        requestJson<{ courses: CourseInfo[]; last_synced_at?: string }>("/classroom/courses"),
        requestJson<{ assignments: ClassroomAssignment[]; last_synced_at?: string }>("/classroom/assignments"),
      ]);

      setCourses(courseResult.courses);
      setAssignments(assignmentResult.assignments);
      if (courseResult.last_synced_at) {
        setLastSyncedAt(courseResult.last_synced_at);
      }
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? loadError.message
          : "Could not load Google Classroom data.",
      );
    } finally {
      setLoading(false);
    }
  }, [onSessionChange]);

  useEffect(() => {
    let active = true;
    void Promise.resolve().then(() => {
      if (!active) return;
      const callbackResult = new URLSearchParams(window.location.search).get("google");
      if (callbackResult === "connected") {
        startTransition(() =>
          setNotice("Google account connected successfully! Click 'Sync classrooms' to fetch your live coursework."),
        );
      } else if (callbackResult === "denied") {
        startTransition(() =>
          setNotice("Google sign-in was cancelled or denied. No Classroom data was accessed."),
        );
      } else if (callbackResult === "error") {
        startTransition(() =>
          setNotice("Google authentication could not be completed. Check the backend environment configuration and server logs."),
        );
      }
      if (callbackResult) {
        window.history.replaceState({}, "", window.location.pathname);
      }
      void reload();
    });
    return () => {
      active = false;
    };
  }, [reload]);

  const syncClassroom = async () => {
    setSyncing(true);
    setError(null);
    try {
      const result = await requestJson<{
        status: string;
        course_count: number;
        assignment_count: number;
        new_courses: number;
        new_assignments: number;
        last_synced_at?: string;
      }>("/classroom/sync", { method: "POST" });
      if (result.last_synced_at) {
        setLastSyncedAt(result.last_synced_at);
      }
      await reload();
      onDashboardRefresh?.();
      setNotice(
        `Classroom sync complete: ${result.course_count} courses and ${result.assignment_count} coursework items synchronized.`,
      );
    } catch (syncError) {
      setError(
        syncError instanceof Error
          ? syncError.message
          : "Google Classroom could not be synced.",
      );
      if (
        syncError instanceof Error &&
        syncError.message.toLowerCase().includes("reconnect")
      ) {
        await reload();
      }
    } finally {
      setSyncing(false);
    }
  };

  const handleDisconnect = async () => {
    if (!confirm("Are you sure you want to disconnect your Google account from ClassMate AI?")) {
      return;
    }
    setDisconnecting(true);
    setError(null);
    try {
      await requestJson("/auth/google/disconnect", { method: "POST" });
      setCourses([]);
      setAssignments([]);
      setLastSyncedAt(null);
      await reload();
      setNotice("Google account disconnected successfully.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to disconnect Google account.");
    } finally {
      setDisconnecting(false);
    }
  };

  const dueTodayAssignments = assignments.filter((a) => a.due_today);
  const displayedAssignments =
    filterView === "due_today" ? dueTodayAssignments : assignments;

  return (
    <section
      aria-labelledby="classroom-heading"
      className="mt-6 rounded-2xl border border-slate-800 bg-[#111A2B] p-4 shadow-[0_18px_45px_rgba(15,23,42,0.2)] md:p-6"
    >
      {/* Header bar */}
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 id="classroom-heading" className="text-lg font-semibold text-white">
              Google Classroom Workspace
            </h2>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-blue-500/30 bg-blue-500/10 px-2.5 py-1 text-[11px] font-medium text-blue-200">
              <CircleDashed className="h-3 w-3" />
              Read-only API
            </span>
            {session?.google_connected ? (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[11px] font-medium text-emerald-200">
                <CheckCircle2 className="h-3 w-3" />
                Live Connected
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-700 bg-slate-900/60 px-2.5 py-1 text-[11px] text-slate-400">
                Not Connected
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-slate-400">
            Real coursework, deadlines, and materials synchronized directly from your Google Classroom account.
          </p>
        </div>

        {/* Top actions */}
        <div className="flex flex-wrap items-center gap-2">
          {session?.google_connected ? (
            <>
              <button
                type="button"
                onClick={syncClassroom}
                disabled={syncing || loading}
                className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-3.5 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {syncing ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                ) : (
                  <RefreshCw className="h-4 w-4" />
                )}
                {syncing ? "Syncing..." : "Sync Classrooms"}
              </button>
              <a
                href={`${apiBase}/api/auth/google/start`}
                className="inline-flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-900/70 px-3 py-2 text-xs font-medium text-slate-300 transition hover:border-slate-500 hover:text-white"
                title="Reconnect your Google account to refresh permissions"
              >
                <RefreshCw className="h-3.5 w-3.5 text-blue-400" />
                Reconnect
              </a>
              <button
                type="button"
                onClick={handleDisconnect}
                disabled={disconnecting}
                className="inline-flex items-center gap-1.5 rounded-xl border border-rose-900/40 bg-rose-950/20 px-3 py-2 text-xs font-medium text-rose-300 transition hover:bg-rose-900/40 hover:text-rose-100 disabled:opacity-50"
                title="Disconnect Google account from ClassMate AI"
              >
                <LogOut className="h-3.5 w-3.5" />
                {disconnecting ? "Disconnecting..." : "Disconnect"}
              </button>
            </>
          ) : (
            <a
              href={`${apiBase}/api/auth/google/start`}
              aria-disabled={loading || !session?.google_oauth_configured}
              tabIndex={loading || !session?.google_oauth_configured ? -1 : 0}
              onClick={(event) => {
                if (loading || !session?.google_oauth_configured) {
                  event.preventDefault();
                }
              }}
              className={`inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-medium text-white shadow-md shadow-blue-500/20 transition hover:bg-blue-500 ${
                loading || !session?.google_oauth_configured
                  ? "cursor-not-allowed opacity-50"
                  : ""
              }`}
            >
              <GraduationCap className="h-4 w-4" />
              Sign in with Google
              <ArrowUpRight className="h-4 w-4" />
            </a>
          )}
        </div>
      </div>

      {/* Notice Message */}
      {notice && (
        <div className="mt-4 flex items-start justify-between gap-3 rounded-xl border border-blue-500/20 bg-blue-500/10 px-4 py-3 text-sm text-blue-100">
          <span>{notice}</span>
          <button
            type="button"
            onClick={() => setNotice(null)}
            aria-label="Dismiss message"
            className="text-blue-200/70 hover:text-white"
          >
            ×
          </button>
        </div>
      )}

      {/* Error Alert */}
      {error && (
        <div role="alert" className="mt-4 flex items-start justify-between gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          <div className="flex items-start gap-2">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-400" />
            <span>{error}</span>
          </div>
          <button
            type="button"
            onClick={() => setError(null)}
            className="text-rose-300 hover:text-white"
          >
            ×
          </button>
        </div>
      )}

      {/* Main Body */}
      {loading ? (
        <div className="mt-6 flex items-center justify-center gap-3 rounded-xl border border-slate-800 bg-slate-900/30 py-10 text-sm text-slate-400">
          <LoaderCircle className="h-5 w-5 animate-spin text-blue-400" />
          <span>Connecting to Google Classroom services...</span>
        </div>
      ) : !session?.authenticated ? (
        <div className="mt-6 rounded-2xl border border-slate-800 bg-slate-900/40 p-6 text-slate-300">
          {session === null && error ? (
            <div className="flex items-center gap-3 text-rose-300">
              <AlertCircle className="h-5 w-5" />
              <p>ClassMate AI could not reach the backend API at {apiBase}. Ensure the FastAPI server is running.</p>
            </div>
          ) : session?.google_oauth_configured ? (
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-white font-medium">
                <GraduationCap className="h-5 w-5 text-blue-400" />
                <span>Ready to connect Google Classroom</span>
              </div>
              <p className="text-sm text-slate-400 leading-relaxed">
                Sign in with your university or student Google account to synchronize your enrolled classrooms, view real assignments, and keep track of actual submission deadlines in one unified workspace.
              </p>
              <div className="pt-2">
                <a
                  href={`${apiBase}/api/auth/google/start`}
                  className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-blue-500 shadow-md shadow-blue-500/20"
                >
                  <GraduationCap className="h-4 w-4" />
                  Sign in with Google Account
                  <ArrowUpRight className="h-4 w-4" />
                </a>
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-amber-300 font-medium">
                <AlertCircle className="h-4 w-4" />
                <span>OAuth Configuration Pending</span>
              </div>
              <p className="text-sm text-slate-400 leading-relaxed">
                Google sign-in is not configured yet. Add the Google OAuth client ID, client secret, and token encryption key to the backend environment (<code className="rounded bg-slate-800 px-1.5 py-0.5 text-xs text-slate-200">backend/.env</code>), then restart the backend API.
              </p>
            </div>
          )}
        </div>
      ) : !session.google_connected ? (
        <div className="mt-6 rounded-2xl border border-slate-800 bg-slate-900/40 p-6 text-center text-sm text-slate-300">
          <GraduationCap className="mx-auto h-8 w-8 text-blue-400 mb-2" />
          <p className="font-medium text-white">Google Account Not Connected</p>
          <p className="mt-1 text-slate-400">
            Connect a Google account to view and synchronize your active Google Classroom courses.
          </p>
          <div className="mt-4">
            <a
              href={`${apiBase}/api/auth/google/start`}
              className="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500"
            >
              Connect Google Account
            </a>
          </div>
        </div>
      ) : (
        <>
          {/* Status Metrics Bar */}
          <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3.5">
              <p className="text-xs uppercase tracking-wider text-slate-400">Connected Account</p>
              <p className="mt-1.5 truncate text-sm font-semibold text-white">
                {session.google_email ?? session.user?.email}
              </p>
              <p className="mt-0.5 truncate text-xs text-slate-400">
                {session.user?.full_name ?? "Student"}
              </p>
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3.5">
              <p className="text-xs uppercase tracking-wider text-slate-400">Enrolled Classrooms</p>
              <p className="mt-1.5 text-2xl font-bold text-white">{courses.length}</p>
              <p className="mt-0.5 text-xs text-slate-400">Active synced courses</p>
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3.5">
              <p className="text-xs uppercase tracking-wider text-slate-400">Total Coursework</p>
              <p className="mt-1.5 text-2xl font-bold text-blue-300">{assignments.length}</p>
              <p className="mt-0.5 text-xs text-slate-400">Live Classroom items</p>
            </div>

            <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3.5">
              <div className="flex items-center justify-between">
                <p className="text-xs uppercase tracking-wider text-slate-400">Due Today</p>
                {dueTodayAssignments.length > 0 && (
                  <span className="relative flex h-2 w-2">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500"></span>
                  </span>
                )}
              </div>
              <p className="mt-1.5 text-2xl font-bold text-amber-300">{dueTodayAssignments.length}</p>
              <p className="mt-0.5 text-xs text-slate-400">
                Last sync: {formatRelativeSyncTime(lastSyncedAt)}
              </p>
            </div>
          </div>

          {/* Navigation Tabs */}
          <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-3">
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setFilterView("all")}
                className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                  filterView === "all"
                    ? "bg-blue-600 text-white"
                    : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
                }`}
              >
                All Assignments ({assignments.length})
              </button>
              <button
                type="button"
                onClick={() => setFilterView("due_today")}
                className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                  filterView === "due_today"
                    ? "bg-amber-600 text-white"
                    : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
                }`}
              >
                Due Today ({dueTodayAssignments.length})
              </button>
              <button
                type="button"
                onClick={() => setFilterView("courses")}
                className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                  filterView === "courses"
                    ? "bg-blue-600 text-white"
                    : "text-slate-400 hover:bg-slate-800 hover:text-slate-200"
                }`}
              >
                Classroom Courses ({courses.length})
              </button>
            </div>

            <div className="flex items-center gap-2 text-xs text-slate-400">
              <span className="inline-block h-2 w-2 rounded-full bg-emerald-400"></span>
              Live Google Classroom Data (Separate from demo assignments)
            </div>
          </div>

          {/* Tab View: Courses */}
          {filterView === "courses" ? (
            <div className="mt-4">
              {courses.length === 0 ? (
                <div className="rounded-xl border border-dashed border-slate-800 bg-slate-900/30 p-8 text-center">
                  <GraduationCap className="mx-auto h-8 w-8 text-slate-500" />
                  <p className="mt-2 text-sm font-medium text-slate-200">No Enrolled Classrooms Found</p>
                  <p className="mt-1 text-xs text-slate-400">
                    Google returned no active courses for {session.google_email ?? "this account"}. Check your Classroom membership or sync again.
                  </p>
                </div>
              ) : (
                <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {courses.map((course) => {
                    const courseAssignments = assignments.filter((a) => a.course_id === course.id);
                    return (
                      <div
                        key={course.id}
                        className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 transition hover:border-slate-700"
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0 flex-1">
                            <h4 className="font-semibold text-white truncate" title={course.name}>
                              {course.name}
                            </h4>
                            {course.section && (
                              <p className="text-xs text-slate-400 truncate mt-0.5">
                                Section: {course.section}
                              </p>
                            )}
                          </div>
                          <span className="shrink-0 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-300">
                            {course.course_state ?? "ACTIVE"}
                          </span>
                        </div>

                        <div className="mt-4 flex items-center justify-between border-t border-slate-800/80 pt-3 text-xs text-slate-400">
                          <span className="inline-flex items-center gap-1">
                            <BookOpenText className="h-3.5 w-3.5 text-blue-400" />
                            {courseAssignments.length} assignment{courseAssignments.length === 1 ? "" : "s"}
                          </span>
                          {course.alternate_link ? (
                            <a
                              href={course.alternate_link}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-1 text-blue-400 hover:text-blue-300 transition"
                            >
                              <span>Open in Classroom</span>
                              <ExternalLink className="h-3 w-3" />
                            </a>
                          ) : (
                            <span className="text-slate-500">ID: {course.id}</span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          ) : (
            /* Tab View: Assignments (All or Due Today) */
            <div className="mt-4">
              {courses.length === 0 ? (
                <div className="rounded-xl border border-dashed border-slate-800 bg-slate-900/30 p-8 text-center">
                  <GraduationCap className="mx-auto h-8 w-8 text-slate-500" />
                  <p className="mt-2 text-sm font-medium text-slate-200">No Enrolled Classrooms Found</p>
                  <p className="mt-1 text-xs text-slate-400">
                    Google returned no courses for this account. Check your Google Classroom account or try syncing.
                  </p>
                </div>
              ) : displayedAssignments.length === 0 ? (
                <div className="rounded-xl border border-dashed border-slate-800 bg-slate-900/30 p-8 text-center text-sm text-slate-400">
                  {filterView === "due_today" ? (
                    <div>
                      <CalendarClock className="mx-auto h-8 w-8 text-slate-500 mb-2" />
                      <p className="font-medium text-slate-300">No assignments due today</p>
                      <p className="mt-1 text-xs text-slate-500">You are all caught up for today&apos;s deadlines!</p>
                    </div>
                  ) : (
                    <div>
                      <Layers className="mx-auto h-8 w-8 text-slate-500 mb-2" />
                      <p className="font-medium text-slate-300">No coursework found in your classrooms</p>
                      <p className="mt-1 text-xs text-slate-500">Teachers have not posted any active coursework items yet.</p>
                    </div>
                  )}
                </div>
              ) : (
                <div className="grid gap-4 lg:grid-cols-2">
                  {displayedAssignments.map((assignment) => (
                    <article
                      key={`${assignment.course_id}:${assignment.google_assignment_id}`}
                      className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 transition hover:border-slate-700/80 shadow-sm"
                    >
                      {/* Coursework Card Header */}
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          <h4 className="font-semibold text-white text-base leading-snug">
                            {assignment.title}
                          </h4>
                          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                            <span className="font-medium text-blue-300">
                              {assignment.course_name}
                            </span>
                            {assignment.course_section && (
                              <span>• {assignment.course_section}</span>
                            )}
                            {assignment.max_points != null && (
                              <span>• {assignment.max_points} pts</span>
                            )}
                          </div>
                        </div>

                        <div className="flex flex-col items-end gap-1.5 shrink-0">
                          {renderSubmissionBadge(assignment.submission_status)}
                          {assignment.due_today && (
                            <span className="rounded-full border border-amber-500/40 bg-amber-500/20 px-2.5 py-0.5 text-[10px] font-semibold text-amber-200 animate-pulse">
                              Due Today
                            </span>
                          )}
                        </div>
                      </div>

                      {/* Deadline bar */}
                      <div className="mt-3 flex items-center justify-between gap-2 rounded-lg bg-slate-950/40 px-3 py-2 text-xs text-slate-300">
                        <div className="flex items-center gap-2">
                          <CalendarClock className="h-4 w-4 text-slate-400 shrink-0" />
                          <span>
                            {formatPKTDeadline(assignment.due_date, assignment.due_time, assignment.deadline)}
                          </span>
                        </div>
                        {assignment.alternate_link && (
                          <a
                            href={assignment.alternate_link}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 text-blue-400 hover:text-blue-300 text-xs font-medium transition"
                          >
                            <span>Classroom</span>
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        )}
                      </div>

                      {/* Description */}
                      {assignment.description && (
                        <p className="mt-3 line-clamp-3 whitespace-pre-wrap text-xs leading-relaxed text-slate-300">
                          {assignment.description}
                        </p>
                      )}

                      {/* Attachments */}
                      {assignment.attachments.length > 0 && (
                        <div className="mt-3 border-t border-slate-800/80 pt-2.5">
                          <p className="text-[11px] font-medium uppercase tracking-wider text-slate-400 mb-1.5">
                            Attachments & Materials
                          </p>
                          <div className="flex flex-wrap gap-2">
                            {assignment.attachments.map((attachment, index) => {
                              const url = safeHttpUrl(attachment.url);
                              const label = attachment.title || `${attachment.type} attachment`;
                              return url ? (
                                <a
                                  key={`${attachment.id ?? label}:${index}`}
                                  href={url}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800/60 px-2.5 py-1.5 text-xs text-blue-200 transition hover:border-blue-500/60 hover:bg-slate-800"
                                >
                                  {renderAttachmentIcon(attachment.type)}
                                  <span className="truncate max-w-[200px]">{label}</span>
                                  <ExternalLink className="h-3 w-3 shrink-0 text-slate-400" />
                                </a>
                              ) : (
                                <span
                                  key={`${attachment.id ?? label}:${index}`}
                                  className="inline-flex items-center gap-1.5 rounded-lg border border-slate-800 bg-slate-900/40 px-2.5 py-1.5 text-xs text-slate-400"
                                >
                                  {renderAttachmentIcon(attachment.type)}
                                  <span className="truncate max-w-[180px]">{label}</span>
                                </span>
                              );
                            })}
                          </div>
                        </div>
                      )}
                    </article>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}
