"use client";

import {
  startTransition,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  AlertTriangle,
  ArrowRight,
  Bell,
  BookOpenText,
  BrainCircuit,
  CalendarCheck2,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  Clock3,
  ExternalLink,
  FileText,
  GraduationCap,
  LayoutDashboard,
  ListTodo,
  Loader2,
  LogOut,
  Menu,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  User,
  UserCircle2,
  Wand2,
  X,
  XCircle,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ClassroomPanel } from "@/components/classroom-panel";
import { requestJson, safeUrl } from "@/lib/api";

// ─── Types ───────────────────────────────────────────────────────────────────

type View =
  | "dashboard"
  | "classrooms"
  | "assignments"
  | "due-today"
  | "upcoming"
  | "overdue"
  | "completed"
  | "ai-workspace"
  | "pdf-documents"
  | "submission-history"
  | "notifications";

type AssignmentFilter =
  | "all"
  | "pending"
  | "due-today"
  | "overdue"
  | "completed";

type OverviewStat = {
  label: string;
  value: string;
  delta: string;
  tone: string;
};

type AssignmentRow = {
  id: number;
  title: string;
  course: string;
  teacher: string;
  deadline: string;
  status: string;
  ai: string;
  submission: string;
  alternate_link?: string | null;
  max_points?: number | null;
};

type ActivityItem = { text: string; time: string };
type DeadlineItem = { title: string; date: string };
type ChartPoint = { day: string; value: number };

type DashboardData = {
  is_demo: boolean;
  authenticated: boolean;
  google_connected: boolean;
  google_email?: string | null;
  last_synced_at?: string | null;
  metrics?: {
    total_assignments: number;
    pending_assignments: number;
    due_today: number;
    overdue: number;
    completed: number;
    awaiting_approval: number;
    active_courses: number;
  };
  stats: OverviewStat[];
  assignments: AssignmentRow[];
  recentActivity: ActivityItem[];
  upcomingDeadlines: DeadlineItem[];
  chartData: ChartPoint[];
};

type SessionInfo = {
  authenticated: boolean;
  google_connected: boolean;
  google_oauth_configured: boolean;
  user?: {
    full_name: string;
    email: string;
    roll_number: string | null;
    department: string | null;
    semester: string | null;
  };
  google_email?: string | null;
  last_synced_at?: string | null;
};

type CourseInfo = {
  id: string;
  name: string;
  section: string | null;
  course_state?: string;
  alternate_link?: string | null;
};

type SearchResult = {
  query: string;
  assignments: {
    id: number;
    title: string;
    course: string;
    due_date: string | null;
    deadline?: string | null;
    submission_status: string;
    alternate_link: string | null;
  }[];
  courses: {
    id: string;
    name: string;
    section: string | null;
    alternate_link: string | null;
  }[];
};

// ─── Static data ─────────────────────────────────────────────────────────────

const navItems: { label: string; icon: React.ElementType; view: View }[] = [
  { label: "Dashboard", icon: LayoutDashboard, view: "dashboard" },
  { label: "My Classrooms", icon: GraduationCap, view: "classrooms" },
  { label: "All Assignments", icon: ListTodo, view: "assignments" },
  { label: "Due Today", icon: CalendarCheck2, view: "due-today" },
  { label: "Upcoming", icon: Clock3, view: "upcoming" },
  { label: "Overdue", icon: AlertTriangle, view: "overdue" },
  { label: "AI Workspace", icon: BrainCircuit, view: "ai-workspace" },
  { label: "PDF Documents", icon: FileText, view: "pdf-documents" },
  { label: "Submission History", icon: CheckCircle2, view: "submission-history" },
  { label: "Notifications", icon: Bell, view: "notifications" },
  { label: "Settings", icon: ShieldCheck, view: "dashboard" },
];

// Map stat card labels → (view, filter)
const statCardNav: Record<
  string,
  { view: View; filter?: AssignmentFilter }
> = {
  "Total Assignments": { view: "assignments", filter: "all" },
  "Pending Assignments": { view: "assignments", filter: "pending" },
  "Due Today": { view: "due-today" },
  "Overdue": { view: "overdue" },
  "Completed": { view: "completed" },
  "Awaiting Approval": { view: "assignments", filter: "all" },
};

// ─── Style helpers ────────────────────────────────────────────────────────────

const toneStyles: Record<string, string> = {
  blue: "from-blue-500/20 via-blue-500/5 to-transparent text-blue-300",
  cyan: "from-cyan-500/20 via-cyan-500/5 to-transparent text-cyan-300",
  amber: "from-amber-500/20 via-amber-500/5 to-transparent text-amber-300",
  rose: "from-rose-500/20 via-rose-500/5 to-transparent text-rose-300",
  green: "from-emerald-500/20 via-emerald-500/5 to-transparent text-emerald-300",
  violet: "from-violet-500/20 via-violet-500/5 to-transparent text-violet-300",
};

const statusTone: Record<string, string> = {
  "Turned In": "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-400/30",
  "Graded": "bg-purple-500/15 text-purple-300 ring-1 ring-purple-400/30",
  "Due Today": "bg-amber-500/15 text-amber-300 ring-1 ring-amber-400/30",
  "Overdue": "bg-rose-500/15 text-rose-300 ring-1 ring-rose-400/30",
  "In Progress": "bg-sky-500/15 text-sky-300 ring-1 ring-sky-400/30",
  "Scheduled": "bg-violet-500/15 text-violet-300 ring-1 ring-violet-400/30",
  "Needs Review": "bg-amber-500/15 text-amber-300 ring-1 ring-amber-400/30",
};

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatSkeleton() {
  return (
    <div className="rounded-2xl border border-slate-800 bg-[#111A2B] p-4 animate-pulse">
      <div className="mb-4 h-8 w-8 rounded-xl bg-slate-800" />
      <div className="flex items-end justify-between gap-3">
        <div className="space-y-2">
          <div className="h-3 w-28 rounded bg-slate-800" />
          <div className="h-8 w-12 rounded bg-slate-700" />
        </div>
        <div className="h-3 w-20 rounded bg-slate-800" />
      </div>
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <CircleDashed className="h-10 w-10 text-slate-700" />
      <p className="text-sm text-slate-500">{message}</p>
    </div>
  );
}

// Assignment table used across multiple views
function AssignmentTable({
  rows,
  loading,
  emptyMessage,
}: {
  rows: AssignmentRow[];
  loading: boolean;
  emptyMessage: string;
}) {
  if (loading)
    return (
      <div className="flex items-center justify-center gap-2 py-16 text-sm text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading…
      </div>
    );
  if (rows.length === 0) return <EmptyState message={emptyMessage} />;
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-left">
        <thead>
          <tr className="border-b border-slate-800 text-xs uppercase tracking-[0.12em] text-slate-400">
            <th className="pb-3 pr-4 font-medium">Assignment</th>
            <th className="pb-3 pr-4 font-medium">Course</th>
            <th className="pb-3 pr-4 font-medium">Deadline</th>
            <th className="pb-3 pr-4 font-medium">Status</th>
            <th className="pb-3 pr-4 font-medium">AI</th>
            <th className="pb-3 font-medium">Submission</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => {
            const link = safeUrl(a.alternate_link);
            return (
              <tr
                key={a.id}
                className="border-b border-slate-800/80 text-sm last:border-none"
              >
                <td className="py-3 pr-4">
                  <div>
                    <p className="font-medium text-white">
                      {link ? (
                        <a
                          href={link}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 hover:text-blue-300 hover:underline"
                        >
                          {a.title}
                          <ExternalLink className="h-3 w-3 opacity-60" />
                        </a>
                      ) : (
                        a.title
                      )}
                    </p>
                    <p className="text-xs text-slate-400">{a.teacher}</p>
                  </div>
                </td>
                <td className="py-3 pr-4 text-slate-300">{a.course}</td>
                <td className="py-3 pr-4 text-slate-300">{a.deadline}</td>
                <td className="py-3 pr-4">
                  <span
                    className={`inline-flex rounded-full px-2.5 py-1 text-xs ${
                      statusTone[a.status] ??
                      "bg-slate-700/50 text-slate-300"
                    }`}
                  >
                    {a.status}
                  </span>
                </td>
                <td className="py-3 pr-4 text-slate-300">{a.ai}</td>
                <td className="py-3 text-slate-300">{a.submission}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Page views ───────────────────────────────────────────────────────────────

function PageShell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-[#111A2B] p-5">
      <div className="mb-5 border-b border-slate-800 pb-4">
        <h2 className="text-lg font-semibold text-white">{title}</h2>
        {subtitle && <p className="mt-1 text-sm text-slate-400">{subtitle}</p>}
      </div>
      {children}
    </div>
  );
}

function AssignmentsView({
  allRows,
  loading,
  initialFilter,
}: {
  allRows: AssignmentRow[];
  loading: boolean;
  initialFilter: AssignmentFilter;
}) {
  const [filter, setFilter] = useState<AssignmentFilter>(initialFilter);

  // Sync if parent changes initialFilter (e.g. card click)
  useEffect(() => {
    setFilter(initialFilter);
  }, [initialFilter]);

  const filters: { label: string; key: AssignmentFilter }[] = [
    { label: "All", key: "all" },
    { label: "Pending", key: "pending" },
    { label: "Due Today", key: "due-today" },
    { label: "Overdue", key: "overdue" },
    { label: "Completed", key: "completed" },
  ];

  const filtered = allRows.filter((a) => {
    if (filter === "all") return true;
    if (filter === "pending")
      return (
        a.status !== "Turned In" &&
        a.status !== "Graded" &&
        a.status !== "Overdue"
      );
    if (filter === "due-today") return a.status === "Due Today";
    if (filter === "overdue") return a.status === "Overdue";
    if (filter === "completed")
      return a.status === "Turned In" || a.status === "Graded";
    return true;
  });

  return (
    <PageShell
      title="All Assignments"
      subtitle="Your complete Google Classroom coursework"
    >
      <div className="mb-4 flex flex-wrap gap-2">
        {filters.map(({ label, key }) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            className={`rounded-full px-3 py-1.5 text-xs transition ${
              filter === key
                ? "bg-blue-500/20 text-blue-300 ring-1 ring-blue-400/40"
                : "border border-slate-700 text-slate-400 hover:border-slate-500 hover:text-slate-200"
            }`}
          >
            {label}
          </button>
        ))}
        <span className="ml-auto text-xs text-slate-500 self-center">
          {filtered.length} record{filtered.length !== 1 ? "s" : ""}
        </span>
      </div>
      <AssignmentTable
        rows={filtered}
        loading={loading}
        emptyMessage={
          filter === "all"
            ? "No assignments found. Sync your Google Classroom to load coursework."
            : `No assignments match the "${label(filter)}" filter.`
        }
      />
    </PageShell>
  );
}

function label(f: AssignmentFilter) {
  return (
    { all: "All", pending: "Pending", "due-today": "Due Today", overdue: "Overdue", completed: "Completed" }[f]
  );
}

function ClassroomsView({
  courses,
  loading,
}: {
  courses: CourseInfo[];
  loading: boolean;
}) {
  return (
    <PageShell
      title="My Classrooms"
      subtitle="All enrolled Google Classroom courses"
    >
      {loading ? (
        <div className="flex items-center justify-center gap-2 py-16 text-sm text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading courses…
        </div>
      ) : courses.length === 0 ? (
        <EmptyState message="No classrooms found. Connect Google Classroom and sync to see your courses." />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {courses.map((c) => {
            const link = safeUrl(c.alternate_link);
            return (
              <div
                key={c.id}
                className="rounded-xl border border-slate-800 bg-slate-900/50 p-4 transition hover:border-slate-600"
              >
                <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500/30 to-cyan-500/30 text-blue-300">
                  <GraduationCap className="h-5 w-5" />
                </div>
                <p className="font-medium text-white leading-snug">{c.name}</p>
                {c.section && (
                  <p className="mt-0.5 text-xs text-slate-400">{c.section}</p>
                )}
                <div className="mt-3 flex items-center justify-between">
                  <span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-300">
                    Active
                  </span>
                  {link && (
                    <a
                      href={link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300"
                    >
                      Open <ExternalLink className="h-3 w-3" />
                    </a>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </PageShell>
  );
}

function UpcomingView({ rows, loading }: { rows: AssignmentRow[]; loading: boolean }) {
  const upcoming = rows.filter(
    (a) => a.status !== "Turned In" && a.status !== "Graded" && a.status !== "Overdue",
  );
  return (
    <PageShell title="Upcoming" subtitle="Pending assignments sorted by deadline">
      <AssignmentTable
        rows={upcoming}
        loading={loading}
        emptyMessage="No upcoming assignments. Great work!"
      />
    </PageShell>
  );
}

function DueTodayView({ rows, loading }: { rows: AssignmentRow[]; loading: boolean }) {
  const today = rows.filter((a) => a.status === "Due Today");
  return (
    <PageShell title="Due Today" subtitle="Assignments due before midnight today">
      <AssignmentTable
        rows={today}
        loading={loading}
        emptyMessage="Nothing due today — you're all caught up!"
      />
    </PageShell>
  );
}

function OverdueView({ rows, loading }: { rows: AssignmentRow[]; loading: boolean }) {
  const overdue = rows.filter((a) => a.status === "Overdue");
  return (
    <PageShell title="Overdue" subtitle="Assignments past their deadline and not submitted">
      {overdue.length > 0 && !loading && (
        <div className="mb-4 flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-2.5 text-sm text-rose-300">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {overdue.length} overdue assignment{overdue.length !== 1 ? "s" : ""} require your attention.
        </div>
      )}
      <AssignmentTable
        rows={overdue}
        loading={loading}
        emptyMessage="No overdue assignments — excellent!"
      />
    </PageShell>
  );
}

function CompletedView({ rows, loading }: { rows: AssignmentRow[]; loading: boolean }) {
  const completed = rows.filter((a) => a.status === "Turned In" || a.status === "Graded");
  return (
    <PageShell title="Completed" subtitle="Assignments you have submitted or had graded">
      <AssignmentTable
        rows={completed}
        loading={loading}
        emptyMessage="No completed assignments yet."
      />
    </PageShell>
  );
}

function SubmissionHistoryView({ rows, loading }: { rows: AssignmentRow[]; loading: boolean }) {
  const submitted = rows.filter((a) => a.status === "Turned In" || a.status === "Graded");
  return (
    <PageShell title="Submission History" subtitle="A record of all submitted work">
      <AssignmentTable
        rows={submitted}
        loading={loading}
        emptyMessage="No submission history yet."
      />
    </PageShell>
  );
}

function NotificationsView({
  dashData,
  session,
}: {
  dashData: DashboardData | null;
  session: SessionInfo | null;
}) {
  const items: { text: string; time: string; type: "info" | "warn" | "ok" }[] = [];

  if (dashData && !dashData.is_demo) {
    if (dashData.last_synced_at) {
      items.push({ text: "Google Classroom sync completed", time: dashData.last_synced_at, type: "ok" });
    }
    if (dashData.metrics) {
      const { overdue, due_today } = dashData.metrics;
      if (overdue > 0)
        items.push({
          text: `${overdue} overdue assignment${overdue !== 1 ? "s" : ""} — submit as soon as possible`,
          time: "Now",
          type: "warn",
        });
      if (due_today > 0)
        items.push({
          text: `${due_today} assignment${due_today !== 1 ? "s" : ""} due today`,
          time: "Today",
          type: "warn",
        });
    }
    dashData.recentActivity.forEach((a) => {
      items.push({ text: a.text, time: a.time, type: "info" });
    });
  }

  if (session?.google_connected) {
    items.push({
      text: `Google account connected (${session.google_email ?? "linked"})`,
      time: "Active",
      type: "ok",
    });
  }

  return (
    <PageShell title="Notifications" subtitle="System events and assignment alerts">
      {items.length === 0 ? (
        <EmptyState message="No notifications. Connect Google Classroom to receive alerts." />
      ) : (
        <div className="space-y-3">
          {items.map((item, i) => (
            <div
              key={i}
              className="flex items-start gap-3 rounded-xl border border-slate-800 bg-slate-900/50 p-3"
            >
              <div
                className={`mt-0.5 rounded-full p-1.5 ${
                  item.type === "warn"
                    ? "bg-amber-500/15 text-amber-300"
                    : item.type === "ok"
                    ? "bg-emerald-500/15 text-emerald-300"
                    : "bg-blue-500/15 text-blue-300"
                }`}
              >
                {item.type === "warn" ? (
                  <AlertTriangle className="h-3.5 w-3.5" />
                ) : item.type === "ok" ? (
                  <CheckCircle2 className="h-3.5 w-3.5" />
                ) : (
                  <Bell className="h-3.5 w-3.5" />
                )}
              </div>
              <div className="flex-1">
                <p className="text-sm text-slate-100">{item.text}</p>
                <p className="text-xs text-slate-400">{item.time}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </PageShell>
  );
}

function PlaceholderView({ title, description }: { title: string; description: string }) {
  return (
    <PageShell title={title}>
      <EmptyState message={description} />
    </PageShell>
  );
}

// ─── Search bar ───────────────────────────────────────────────────────────────

function SearchBar({
  onNavigate,
}: {
  onNavigate: (view: View, filter?: AssignmentFilter) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult | null>(null);
  const [searching, setSearching] = useState(false);
  const [open, setOpen] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const doSearch = useCallback(async (q: string) => {
    if (q.trim().length < 2) {
      setResults(null);
      setOpen(false);
      return;
    }
    setSearching(true);
    try {
      const r = await requestJson<SearchResult>(
        `/search?q=${encodeURIComponent(q)}`,
      );
      setResults(r);
      setOpen(true);
    } catch {
      setResults(null);
    } finally {
      setSearching(false);
    }
  }, []);

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const val = e.target.value;
    setQuery(val);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => void doSearch(val), 300);
  }

  // Close on outside click
  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  function clear() {
    setQuery("");
    setResults(null);
    setOpen(false);
  }

  const hasResults =
    results && (results.assignments.length > 0 || results.courses.length > 0);

  return (
    <div ref={containerRef} className="relative w-full max-w-md">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
      <input
        aria-label="Search assignments and courses"
        className="w-full rounded-xl border border-slate-700 bg-slate-900/70 py-2.5 pl-9 pr-8 text-sm text-slate-100 placeholder:text-slate-500 outline-none ring-0 transition focus:border-blue-500"
        placeholder="Search assignments, courses…"
        value={query}
        onChange={handleChange}
        onFocus={() => results && setOpen(true)}
        onKeyDown={(e) => e.key === "Escape" && clear()}
      />
      {searching && (
        <Loader2 className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-slate-400" />
      )}
      {!searching && query && (
        <button
          onClick={clear}
          className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200"
          aria-label="Clear search"
        >
          <X className="h-4 w-4" />
        </button>
      )}

      {open && (
        <div className="absolute left-0 right-0 top-full z-50 mt-2 overflow-hidden rounded-xl border border-slate-700 bg-[#0D1322] shadow-2xl shadow-slate-950/60">
          {!hasResults ? (
            <p className="px-4 py-3 text-sm text-slate-500">
              No results for &ldquo;{query}&rdquo;
            </p>
          ) : (
            <>
              {results.assignments.length > 0 && (
                <div>
                  <p className="border-b border-slate-800 px-4 py-2 text-[10px] uppercase tracking-widest text-slate-500">
                    Assignments
                  </p>
                  {results.assignments.map((a) => {
                    const link = safeUrl(a.alternate_link);
                    return (
                      <button
                        key={a.id}
                        className="flex w-full items-center gap-3 px-4 py-2.5 text-left transition hover:bg-slate-800/60"
                        onClick={() => {
                          clear();
                          if (link) window.open(link, "_blank", "noopener");
                          else onNavigate("assignments", "all");
                        }}
                      >
                        <ListTodo className="h-4 w-4 shrink-0 text-blue-400" />
                        <div className="min-w-0">
                          <p className="truncate text-sm text-slate-100">{a.title}</p>
                          <p className="text-xs text-slate-400">
                            {a.course}
                            {a.deadline ? ` • ${a.deadline}` : ""}
                          </p>
                        </div>
                        {link && (
                          <ExternalLink className="ml-auto h-3.5 w-3.5 shrink-0 text-slate-500" />
                        )}
                      </button>
                    );
                  })}
                </div>
              )}
              {results.courses.length > 0 && (
                <div>
                  <p className="border-b border-slate-800 border-t border-t-slate-800/60 px-4 py-2 text-[10px] uppercase tracking-widest text-slate-500">
                    Classrooms
                  </p>
                  {results.courses.map((c) => {
                    const link = safeUrl(c.alternate_link);
                    return (
                      <button
                        key={c.id}
                        className="flex w-full items-center gap-3 px-4 py-2.5 text-left transition hover:bg-slate-800/60"
                        onClick={() => {
                          clear();
                          if (link) window.open(link, "_blank", "noopener");
                          else onNavigate("classrooms");
                        }}
                      >
                        <GraduationCap className="h-4 w-4 shrink-0 text-cyan-400" />
                        <div className="min-w-0">
                          <p className="truncate text-sm text-slate-100">{c.name}</p>
                          {c.section && (
                            <p className="text-xs text-slate-400">{c.section}</p>
                          )}
                        </div>
                        {link && (
                          <ExternalLink className="ml-auto h-3.5 w-3.5 shrink-0 text-slate-500" />
                        )}
                      </button>
                    );
                  })}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Profile dropdown ─────────────────────────────────────────────────────────

function ProfileDropdown({
  session,
  onLogout,
}: {
  session: SessionInfo | null;
  onLogout: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const user = session?.user;
  const initials = user?.full_name
    ? user.full_name
        .split(" ")
        .map((w) => w[0])
        .slice(0, 2)
        .join("")
        .toUpperCase()
    : "SA";

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((p) => !p)}
        className="flex items-center gap-3 rounded-xl border border-slate-700 bg-slate-900/60 px-2 py-1.5 transition hover:border-slate-500"
        aria-label="Profile menu"
      >
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-sky-500 to-cyan-300 text-xs font-semibold text-slate-950">
          {initials}
        </div>
        <div className="hidden text-left sm:block">
          <p className="text-sm font-medium text-white">
            {user?.full_name.split(" ")[0] ?? "Student"}
          </p>
          <p className="text-[10px] uppercase tracking-[0.14em] text-slate-400">Student</p>
        </div>
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-2 w-64 overflow-hidden rounded-xl border border-slate-700 bg-[#0D1322] shadow-2xl shadow-slate-950/60">
          <div className="border-b border-slate-800 px-4 py-3">
            <p className="font-medium text-white">{user?.full_name ?? "Student"}</p>
            <p className="text-xs text-slate-400 truncate">{user?.email ?? "—"}</p>
          </div>
          {(user?.roll_number || user?.department || user?.semester) && (
            <div className="border-b border-slate-800 px-4 py-3 space-y-1">
              {user.roll_number && (
                <p className="text-xs text-slate-400">
                  <span className="text-slate-500">Roll: </span>{user.roll_number}
                </p>
              )}
              {user.department && (
                <p className="text-xs text-slate-400">
                  <span className="text-slate-500">Dept: </span>{user.department}
                </p>
              )}
              {user.semester && (
                <p className="text-xs text-slate-400">
                  <span className="text-slate-500">Semester: </span>{user.semester}
                </p>
              )}
            </div>
          )}
          {session?.google_email && (
            <div className="border-b border-slate-800 px-4 py-3">
              <p className="text-xs text-slate-400">
                <span className="text-slate-500">Google: </span>
                {session.google_email}
              </p>
            </div>
          )}
          <button
            onClick={() => {
              setOpen(false);
              onLogout();
            }}
            className="flex w-full items-center gap-3 px-4 py-3 text-sm text-rose-400 transition hover:bg-rose-500/10"
          >
            <LogOut className="h-4 w-4" />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

// ─── Main shell ───────────────────────────────────────────────────────────────

export function DashboardShell() {
  const [view, setView] = useState<View>("dashboard");
  const [assignmentFilter, setAssignmentFilter] = useState<AssignmentFilter>("all");
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Session / auth
  const [session, setSession] = useState<SessionInfo | null>(null);

  // Dashboard API data
  const [dashData, setDashData] = useState<DashboardData | null>(null);
  const [dashLoading, setDashLoading] = useState(true);
  const [dashError, setDashError] = useState<string | null>(null);

  // Courses (for classrooms view)
  const [courses, setCourses] = useState<CourseInfo[]>([]);
  const [coursesLoading, setCoursesLoading] = useState(false);

  // ── Fetch dashboard overview ──
  const fetchDashboard = useCallback(async () => {
    setDashLoading(true);
    setDashError(null);
    try {
      const data = await requestJson<DashboardData>("/dashboard/overview");
      setDashData(data);
    } catch (err) {
      setDashError(err instanceof Error ? err.message : "Could not load dashboard.");
    } finally {
      setDashLoading(false);
    }
  }, []);

  // ── Fetch session ──
  const fetchSession = useCallback(async () => {
    try {
      const s = await requestJson<SessionInfo>("/auth/me");
      setSession(s);
    } catch {
      setSession(null);
    }
  }, []);

  // ── Fetch courses for classrooms view ──
  const fetchCourses = useCallback(async () => {
    setCoursesLoading(true);
    try {
      const r = await requestJson<{ courses: CourseInfo[] }>("/classroom/courses");
      setCourses(r.courses);
    } catch {
      setCourses([]);
    } finally {
      setCoursesLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchDashboard();
    void fetchSession();
  }, [fetchDashboard, fetchSession]);

  // Load courses when switching to classrooms view
  useEffect(() => {
    if (view === "classrooms" && courses.length === 0) {
      void fetchCourses();
    }
  }, [view, courses.length, fetchCourses]);

  // ── Logout ──
  const handleLogout = useCallback(async () => {
    try {
      await requestJson("/auth/logout", { method: "POST" });
    } catch { /* ignore */ }
    setSession(null);
    setDashData(null);
    void fetchDashboard();
    void fetchSession();
  }, [fetchDashboard, fetchSession]);

  // ── Navigation helper ──
  const navigate = useCallback(
    (target: View, filter?: AssignmentFilter) => {
      startTransition(() => {
        setView(target);
        if (filter) setAssignmentFilter(filter);
        setSidebarOpen(false);
      });
    },
    [],
  );

  // ── Stat card click handler ──
  function handleStatClick(label: string) {
    const nav = statCardNav[label];
    if (!nav) return;
    if (nav.view === "assignments") {
      navigate("assignments", nav.filter ?? "all");
    } else {
      navigate(nav.view);
    }
  }

  // ── ClassroomPanel session callback ──
  const handleSessionChange = useCallback((s: SessionInfo) => {
    setSession(s);
  }, []);

  const googleConnected = session?.google_connected ?? false;
  const student = session?.user ?? null;
  const isDemo = dashData?.is_demo !== false;
  const stats = dashData?.stats ?? [];
  const allRows = dashData?.assignments ?? [];
  const recentActivity = dashData?.recentActivity ?? [];
  const upcomingDeadlines = dashData?.upcomingDeadlines ?? [];
  const chartData = dashData?.chartData ?? [];

  const initials = student?.full_name
    ? student.full_name.split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase()
    : "SA";

  // ── Render view content ──
  function renderMain() {
    if (view === "classrooms") {
      return <ClassroomsView courses={courses} loading={coursesLoading} />;
    }
    if (view === "assignments") {
      return (
        <AssignmentsView
          allRows={allRows}
          loading={dashLoading}
          initialFilter={assignmentFilter}
        />
      );
    }
    if (view === "due-today") {
      return <DueTodayView rows={allRows} loading={dashLoading} />;
    }
    if (view === "upcoming") {
      return <UpcomingView rows={allRows} loading={dashLoading} />;
    }
    if (view === "overdue") {
      return <OverdueView rows={allRows} loading={dashLoading} />;
    }
    if (view === "completed") {
      return <CompletedView rows={allRows} loading={dashLoading} />;
    }
    if (view === "submission-history") {
      return <SubmissionHistoryView rows={allRows} loading={dashLoading} />;
    }
    if (view === "notifications") {
      return <NotificationsView dashData={dashData} session={session} />;
    }
    if (view === "ai-workspace") {
      return (
        <PlaceholderView
          title="AI Workspace"
          description="AI-powered assignment generation and review will be available here."
        />
      );
    }
    if (view === "pdf-documents") {
      return (
        <PlaceholderView
          title="PDF Documents"
          description="Generated and uploaded PDF documents will appear here."
        />
      );
    }

    // ── Dashboard (default) ──
    return (
      <>
        {/* Stats grid */}
        <section className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {dashLoading
            ? Array.from({ length: 6 }).map((_, i) => <StatSkeleton key={i} />)
            : dashError
            ? (
              <div className="col-span-3 rounded-2xl border border-rose-800/50 bg-rose-900/20 p-4 text-sm text-rose-300">
                <AlertTriangle className="mb-1 inline h-4 w-4" /> {dashError}
                <button
                  onClick={() => void fetchDashboard()}
                  className="ml-3 underline hover:no-underline"
                >
                  Retry
                </button>
              </div>
            )
            : stats.map(({ label, value, delta, tone }) => {
                const nav = statCardNav[label];
                return (
                  <button
                    key={label}
                    onClick={() => handleStatClick(label)}
                    className={`w-full rounded-2xl border border-slate-800 bg-[#111A2B] p-4 text-left shadow-[0_18px_45px_rgba(15,23,42,0.25)] transition hover:border-slate-600 hover:shadow-[0_18px_45px_rgba(15,23,42,0.4)] focus:outline-none focus:ring-2 focus:ring-blue-500/50 ${nav ? "cursor-pointer" : "cursor-default"}`}
                    tabIndex={nav ? 0 : -1}
                    aria-label={`${label}: ${value} — navigate to ${nav?.view ?? "dashboard"}`}
                  >
                    <div
                      className={`mb-4 inline-flex rounded-xl bg-gradient-to-r ${toneStyles[tone] ?? toneStyles.blue} p-2`}
                    >
                      <BookOpenText className="h-4 w-4" />
                    </div>
                    <div className="flex items-end justify-between gap-3">
                      <div>
                        <p className="text-sm text-slate-400">{label}</p>
                        <p className="mt-2 text-3xl font-semibold text-white">{value}</p>
                      </div>
                      <span className="flex items-center gap-1 text-xs text-slate-300">
                        {delta}
                        {nav && <ChevronRight className="h-3 w-3 text-slate-500" />}
                      </span>
                    </div>
                  </button>
                );
              })}
        </section>

        {/* Classroom panel */}
        <ClassroomPanel
          onSessionChange={handleSessionChange}
          onDashboardRefresh={fetchDashboard}
        />

        {/* Assignment table + sidebar widgets */}
        <section className="mt-6 grid gap-6 xl:grid-cols-[1.6fr_0.8fr]">
          <div className="rounded-2xl border border-slate-800 bg-[#111A2B] p-4 md:p-5">
            <div className="mb-4 flex items-center justify-between gap-3">
              <div>
                <p className="text-sm font-medium text-white">Assignment overview</p>
                <p className="text-sm text-slate-400">Current workload and submission status</p>
              </div>
              <button
                onClick={() => navigate("assignments", "all")}
                className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2 text-xs text-slate-300 transition hover:border-slate-500 hover:text-white"
              >
                View all <ArrowRight className="h-3.5 w-3.5" />
              </button>
            </div>
            <AssignmentTable
              rows={allRows.slice(0, 5)}
              loading={dashLoading}
              emptyMessage={
                googleConnected
                  ? "No assignments found. Try syncing your Classroom."
                  : "Connect Google Classroom to see your assignments here."
              }
            />
          </div>

          <div className="space-y-6">
            {/* Recent activity */}
            <div className="rounded-2xl border border-slate-800 bg-[#111A2B] p-4 md:p-5">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-white">Recent activity</p>
                  <p className="text-xs text-slate-400">Latest Classroom events</p>
                </div>
                <UserCircle2 className="h-4 w-4 text-slate-400" />
              </div>
              <div className="space-y-3">
                {recentActivity.length === 0 ? (
                  <p className="text-center text-xs text-slate-500 py-4">No recent activity</p>
                ) : (
                  recentActivity.map((item, i) => (
                    <div
                      key={i}
                      className="flex items-start gap-3 rounded-xl border border-slate-800 bg-slate-900/50 p-3"
                    >
                      <div className="mt-0.5 rounded-full bg-blue-500/15 p-1.5 text-blue-300">
                        <CheckCircle2 className="h-3.5 w-3.5" />
                      </div>
                      <div className="flex-1">
                        <p className="text-sm text-slate-100">{item.text}</p>
                        <p className="text-xs text-slate-400">{item.time}</p>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Upcoming deadlines */}
            <div className="rounded-2xl border border-slate-800 bg-[#111A2B] p-4 md:p-5">
              <div className="mb-4 flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-white">Upcoming deadlines</p>
                  <p className="text-xs text-slate-400">Priority scheduling</p>
                </div>
                <CalendarCheck2 className="h-4 w-4 text-slate-400" />
              </div>
              <div className="space-y-3">
                {upcomingDeadlines.length === 0 ? (
                  <p className="text-center text-xs text-slate-500 py-4">No upcoming deadlines</p>
                ) : (
                  upcomingDeadlines.map((item, i) => (
                    <button
                      key={i}
                      onClick={() => navigate("upcoming")}
                      className="flex w-full items-center justify-between rounded-xl border border-slate-800 bg-slate-900/50 p-3 text-left transition hover:border-slate-700"
                    >
                      <div>
                        <p className="text-sm text-slate-100">{item.title}</p>
                        <p className="text-xs text-slate-400">Due in {item.date}</p>
                      </div>
                      <div className="rounded-full bg-blue-500/10 p-2 text-blue-300">
                        <Clock3 className="h-3.5 w-3.5" />
                      </div>
                    </button>
                  ))
                )}
              </div>
            </div>
          </div>
        </section>

        {/* Chart + Quick actions */}
        <section className="mt-6 grid gap-6 xl:grid-cols-[1.3fr_0.7fr]">
          <div className="rounded-2xl border border-slate-800 bg-[#111A2B] p-4 md:p-5">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-white">Assignment workload</p>
                <p className="text-xs text-slate-400">7-day due-date distribution</p>
              </div>
              <button
                onClick={() => void fetchDashboard()}
                className="rounded-full border border-slate-700 p-1.5 text-slate-400 transition hover:border-slate-500 hover:text-slate-200"
                aria-label="Refresh chart"
              >
                <RefreshCw className="h-3.5 w-3.5" />
              </button>
            </div>
            <div className="h-56 w-full">
              {dashLoading ? (
                <div className="flex h-full items-center justify-center">
                  <Loader2 className="h-6 w-6 animate-spin text-slate-600" />
                </div>
              ) : (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData}>
                    <defs>
                      <linearGradient id="metricFill" x1="0" x2="0" y1="0" y2="1">
                        <stop offset="0%" stopColor="#3B82F6" stopOpacity={0.45} />
                        <stop offset="100%" stopColor="#3B82F6" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke="#1E293B" strokeDasharray="4 4" vertical={false} />
                    <XAxis dataKey="day" stroke="#64748B" tickLine={false} axisLine={false} />
                    <YAxis stroke="#64748B" tickLine={false} axisLine={false} allowDecimals={false} />
                    <Tooltip
                      contentStyle={{
                        backgroundColor: "#0F172A",
                        border: "1px solid rgba(148,163,184,0.2)",
                        borderRadius: 12,
                        color: "#E2E8F0",
                      }}
                    />
                    <Area
                      type="monotone"
                      dataKey="value"
                      stroke="#3B82F6"
                      strokeWidth={3}
                      fill="url(#metricFill)"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              )}
            </div>
          </div>

          <div className="rounded-2xl border border-slate-800 bg-[#111A2B] p-4 md:p-5">
            <div className="mb-4">
              <p className="text-sm font-medium text-white">Quick actions</p>
              <p className="text-xs text-slate-400">Take the next step</p>
            </div>
            <div className="space-y-3">
              {(
                [
                  { label: "My Classrooms", icon: GraduationCap, view: "classrooms" as View },
                  { label: "All Assignments", icon: ListTodo, view: "assignments" as View },
                  { label: "AI Workspace", icon: BrainCircuit, view: "ai-workspace" as View },
                  { label: "PDF Documents", icon: FileText, view: "pdf-documents" as View },
                ] as const
              ).map(({ label, icon: Icon, view: target }) => (
                <button
                  key={label}
                  onClick={() => navigate(target)}
                  className="flex w-full items-center justify-between rounded-xl border border-slate-800 bg-slate-900/60 px-3 py-3 text-left text-sm text-slate-100 transition hover:border-slate-600 hover:bg-slate-900"
                >
                  <span className="flex items-center gap-3">
                    <span className="rounded-lg bg-blue-500/10 p-2 text-blue-300">
                      <Icon className="h-4 w-4" />
                    </span>
                    {label}
                  </span>
                  <ArrowRight className="h-4 w-4 text-slate-400" />
                </button>
              ))}
            </div>
          </div>
        </section>
      </>
    );
  }

  // ── Page titles for non-dashboard views ──
  const viewTitles: Partial<Record<View, string>> = {
    classrooms: "My Classrooms",
    assignments: "All Assignments",
    "due-today": "Due Today",
    upcoming: "Upcoming",
    overdue: "Overdue",
    completed: "Completed",
    "ai-workspace": "AI Workspace",
    "pdf-documents": "PDF Documents",
    "submission-history": "Submission History",
    notifications: "Notifications",
  };
  const pageTitle = view === "dashboard" ? "Dashboard" : (viewTitles[view] ?? "Dashboard");

  return (
    <div className="min-h-screen bg-[#090D18] text-slate-100">
      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-slate-950/60 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <div className="flex min-h-screen">
        {/* ── Sidebar ── */}
        <aside
          className={`fixed inset-y-0 left-0 z-50 flex w-72 flex-col border-r border-slate-800/80 bg-[#0D1322] transition-transform md:static md:translate-x-0 ${
            sidebarOpen ? "translate-x-0" : "-translate-x-full"
          }`}
        >
          <div className="flex items-center gap-3 border-b border-slate-800/80 px-5 py-5">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-cyan-400 shadow-lg shadow-blue-500/30">
              <BookOpenText className="h-5 w-5 text-white" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-[0.2em] text-slate-400">AUST</p>
              <h2 className="text-lg font-semibold text-white">ClassMate AI</h2>
            </div>
            <button
              className="ml-auto rounded-lg p-1 text-slate-400 hover:text-slate-200 md:hidden"
              onClick={() => setSidebarOpen(false)}
              aria-label="Close sidebar"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
            {navItems.map(({ label, icon: Icon, view: target }) => {
              const active = view === target && !(target === "dashboard" && view !== "dashboard");
              const isActive = view === target;
              return (
                <button
                  key={label}
                  onClick={() => navigate(target)}
                  className={`flex w-full items-center justify-between rounded-xl px-3 py-2.5 text-sm transition ${
                    isActive
                      ? "bg-slate-800/90 text-white shadow-inner shadow-slate-700/60"
                      : "text-slate-300 hover:bg-slate-800/70 hover:text-white"
                  }`}
                  aria-current={isActive ? "page" : undefined}
                >
                  <span className="flex items-center gap-3">
                    <Icon className="h-4 w-4" />
                    {label}
                  </span>
                  {isActive && <ChevronRight className="h-4 w-4 text-slate-300" />}
                </button>
              );
            })}
          </nav>

          <div className="border-t border-slate-800/80 p-4">
            <div className="flex items-center gap-3 rounded-xl border border-slate-800 bg-slate-900/65 p-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-blue-500 to-cyan-300 text-sm font-semibold text-white">
                {initials}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-white">
                  {student?.full_name ?? "AUST Student"}
                </p>
                <p className="truncate text-xs text-slate-400">
                  {student?.email ?? "Demo workspace"}
                </p>
              </div>
            </div>
            <div className="mt-3 flex gap-2 text-xs text-slate-300">
              <button
                onClick={() => setView("dashboard")}
                className="flex-1 rounded-lg border border-slate-700 bg-slate-900/60 px-2 py-2 hover:border-slate-500"
              >
                Account
              </button>
              <button
                onClick={() => void handleLogout()}
                className="flex-1 rounded-lg border border-slate-700 bg-slate-900/60 px-2 py-2 hover:border-rose-600/50 hover:text-rose-400"
              >
                Logout
              </button>
            </div>
          </div>
        </aside>

        {/* ── Main content ── */}
        <main className="flex-1 overflow-x-hidden">
          {/* Header */}
          <header className="sticky top-0 z-30 border-b border-slate-800/80 bg-[#0D1322]/80 backdrop-blur-sm">
            <div className="flex items-center justify-between gap-4 px-4 py-4 md:px-6">
              <div className="flex items-center gap-3">
                <button
                  className="rounded-lg border border-slate-700 bg-slate-900/60 p-2 text-slate-300 md:hidden"
                  onClick={() => setSidebarOpen(true)}
                  aria-label="Open sidebar"
                >
                  <Menu className="h-4 w-4" />
                </button>
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-blue-500 to-cyan-400 text-sm font-semibold text-white md:hidden">
                  C
                </div>
              </div>

              <SearchBar onNavigate={navigate} />

              <div className="flex items-center gap-2 md:gap-3">
                {/* Pakistan Timezone badge */}
                <div
                  className="hidden items-center gap-1.5 rounded-full border border-sky-500/30 bg-sky-500/10 px-3 py-1.5 text-xs text-sky-300 md:flex"
                  title="Application display timezone: Pakistan Standard Time (UTC+05:00)"
                >
                  <Clock3 className="h-3.5 w-3.5 text-sky-400" />
                  <span>PKT (UTC+5)</span>
                </div>

                {/* Google status badge */}
                <div
                  className={`hidden items-center gap-2 rounded-full border px-3 py-1.5 text-xs md:flex ${
                    googleConnected
                      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                      : "border-slate-700 bg-slate-900/60 text-slate-400"
                  }`}
                >
                  {googleConnected ? (
                    <CheckCircle2 className="h-3.5 w-3.5" />
                  ) : (
                    <CircleDashed className="h-3.5 w-3.5" />
                  )}
                  {googleConnected ? "Google connected" : "Not connected"}
                </div>

                {/* Notification bell */}
                <button
                  onClick={() => navigate("notifications")}
                  className="relative rounded-xl border border-slate-700 bg-slate-900/60 p-2.5 text-slate-300 transition hover:border-slate-500"
                  aria-label="Notifications"
                >
                  <Bell className="h-4 w-4" />
                  {dashData?.metrics &&
                    (dashData.metrics.overdue > 0 || dashData.metrics.due_today > 0) && (
                      <span className="absolute right-2 top-2 h-2 w-2 rounded-full bg-rose-500" />
                    )}
                </button>

                {/* Profile dropdown */}
                <ProfileDropdown session={session} onLogout={handleLogout} />
              </div>
            </div>
          </header>

          {/* Page content */}
          <div className="px-4 pb-8 pt-6 md:px-6">
            {/* Page header */}
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-slate-400">
                  Student workspace
                </p>
                <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">
                  {pageTitle}
                </h1>
              </div>
              <div className="inline-flex w-fit items-center gap-2 rounded-full border border-slate-700 bg-slate-900/60 px-3 py-1.5 text-xs">
                <Sparkles className="h-3.5 w-3.5 text-cyan-300" />
                {dashLoading ? (
                  <span className="text-slate-400">Loading…</span>
                ) : dashData && !isDemo ? (
                  <span className="text-emerald-300">Live Classroom data</span>
                ) : (
                  <span className="text-slate-300">Demo data — development preview</span>
                )}
              </div>
            </div>

            {/* View content */}
            {renderMain()}
          </div>
        </main>
      </div>
    </div>
  );
}

export default DashboardShell;
