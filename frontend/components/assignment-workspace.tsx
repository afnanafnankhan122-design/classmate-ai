"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Check,
  Download,
  FileText,
  History,
  Loader2,
  RotateCcw,
  Sparkles,
  X,
} from "lucide-react";
import { requestJson, safeUrl } from "@/lib/api";

type AssignmentRow = {
  id: number;
  title: string;
  course: string;
  deadline: string;
  processing_status?: string;
};

type Student = {
  full_name: string;
  roll_number: string | null;
  department: string | null;
  semester: string | null;
};

type AssignmentAttachment = {
  id?: string;
  title?: string;
  type?: string;
  url?: string;
};

type DraftVersion = {
  id: number;
  version: number;
  content: string;
  source: string;
  note: string | null;
  created_at: string;
};

type DocumentExport = {
  id: number;
  version: number;
  format: "pdf" | "docx" | "csv";
  created_at: string;
};

type Workspace = {
  license: {
    status: string;
    active: boolean;
  };
  assignment: {
    id: number;
    title: string;
    instructions: string | null;
    course: string | null;
    due_date: string | null;
    draft_content: string | null;
    attachments: AssignmentAttachment[];
    processing_status: string;
    processing_error: string | null;
    submission_status: string;
    approved: boolean;
    latest_version: number | null;
  };
  student: Student;
  versions: DraftVersion[];
  exports: DocumentExport[];
};

type SaveResult = {
  status: string;
  draft_content: string;
  version: DraftVersion | null;
};

type Suggestion = {
  suggestion: string;
};

type Selection = { start: number; end: number; text: string };

function renderDocumentContent(content: string) {
  return content.split(/\n{2,}/).filter(Boolean).map((block, index) => {
    const text = block.trim();
    const heading = text.match(/^#{1,3}\s+(.+)$/);
    if (heading) {
      return (
        <h3 key={index} className="mb-3 mt-6 text-lg font-semibold text-slate-900">
          {heading[1]}
        </h3>
      );
    }
    return (
      <p key={index} className="mb-4 whitespace-pre-wrap text-[15px] leading-7 text-slate-800">
        {text}
      </p>
    );
  });
}

async function fetchDocument(assignmentId: number, format: "pdf" | "docx" | "csv") {
  let response: Response;
  try {
    response = await fetch(
      `/api/assignments/${assignmentId}/documents/${format}`,
      { credentials: "include" },
    );
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error("Could not connect to ClassMate AI. Check that the app is running.");
    }
    throw error;
  }
  if (!response.ok) {
    const result = await response.json().catch(() => null) as { detail?: unknown } | null;
    throw new Error(
      typeof result?.detail === "string"
        ? result.detail
        : `Could not generate the ${format.toUpperCase()} (${response.status}).`,
    );
  }
  return {
    blob: await response.blob(),
    version: response.headers.get("X-Assignment-Version"),
    exportId: response.headers.get("X-Assignment-Export"),
  };
}

export function AssignmentWorkspace({
  assignments,
  initialAssignmentId,
  onSelectAssignment,
  student,
}: {
  assignments: AssignmentRow[];
  initialAssignmentId: number | null;
  onSelectAssignment: (assignmentId: number | null) => void;
  student: Student | null;
}) {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [content, setContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [recoverableContent, setRecoverableContent] = useState<string | null>(null);
  const [suggestion, setSuggestion] = useState("");
  const [suggestionSelection, setSuggestionSelection] = useState<Selection | null>(null);
  const [suggestionSourceContent, setSuggestionSourceContent] = useState("");
  const [selectedVersion, setSelectedVersion] = useState<DraftVersion | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [length, setLength] = useState("standard");
  const [style, setStyle] = useState("academic");
  const [instruction, setInstruction] = useState("");
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [exporting, setExporting] = useState<"pdf" | "docx" | "csv" | null>(null);
  const [savedPdfUrl, setSavedPdfUrl] = useState<string | null>(null);
  const [pdfPreviewContent, setPdfPreviewContent] = useState<string | null>(null);
  const [documentVersion, setDocumentVersion] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const activeAssignmentId = initialAssignmentId;
  const licenseActive = Boolean(
    workspace &&
    workspace.assignment.id === activeAssignmentId &&
    workspace.license.active,
  );

  useEffect(() => {
    if (!activeAssignmentId) return;

    let cancelled = false;

    void requestJson<Workspace>(`/assignments/${activeAssignmentId}/workspace`)
      .then((result) => {
        if (cancelled) return;
        const draft = result.assignment.draft_content ?? "";
        const localDraft = window.localStorage.getItem(
          `classmate-ai:draft:${activeAssignmentId}`,
        );
        setWorkspace(result);
        setContent(draft);
        setSavedContent(draft);
        setRecoverableContent(localDraft && localDraft !== draft ? localDraft : null);
        setSuggestion("");
        setSuggestionSourceContent("");
        setSavedPdfUrl(null);
        setPdfPreviewContent(null);
        setDocumentVersion(null);
        setError(null);
        setNotice(null);
      })
      .catch((cause) => {
        if (!cancelled) {
          setError(cause instanceof Error ? cause.message : "Could not load this assignment.");
        }
      });

    return () => {
      cancelled = true;
    };
  }, [activeAssignmentId]);

  useEffect(() => {
    if (!savedPdfUrl) return;
    return () => URL.revokeObjectURL(savedPdfUrl);
  }, [savedPdfUrl]);

  const persistDraft = useCallback(
    async (nextContent: string, source: "student" | "ai" = "student") => {
      if (!activeAssignmentId || !licenseActive) return;
      setSaving(true);
      setError(null);
      try {
        const result = await requestJson<SaveResult>(
          `/assignments/${activeAssignmentId}/draft`,
          {
            method: "PUT",
            body: JSON.stringify({ content: nextContent, source }),
          },
        );
        setSavedContent(nextContent);
        setRecoverableContent(null);
        window.localStorage.setItem(
          `classmate-ai:draft:${activeAssignmentId}`,
          nextContent,
        );
        if (result.version) {
          const newVersion = result.version;
          setWorkspace((current) => {
            if (!current) return current;
            const wasReadyOrApproved = ["ready_for_review", "approved"].includes(
              current.assignment.processing_status,
            );
            return {
              ...current,
              assignment: {
                ...current.assignment,
                draft_content: nextContent,
                latest_version: newVersion.version,
                approved: false,
                processing_status: wasReadyOrApproved
                  ? "editing"
                  : current.assignment.processing_status,
              },
              versions: [
                newVersion,
                ...current.versions.filter((version) => version.id !== newVersion.id),
              ].slice(0, 50),
            };
          });
        } else {
          setWorkspace((current) => current && ({
            ...current,
            assignment: { ...current.assignment, draft_content: nextContent },
          }));
        }
        return result;
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "Could not save your draft.");
        throw cause;
      } finally {
        setSaving(false);
      }
    },
    [activeAssignmentId, licenseActive],
  );

  useEffect(() => {
    if (
      !activeAssignmentId ||
      !workspace ||
      workspace.assignment.id !== activeAssignmentId ||
      recoverableContent !== null
    ) {
      return;
    }
    window.localStorage.setItem(
      `classmate-ai:draft:${activeAssignmentId}`,
      content,
    );
    if (workspace.license.active !== true) return;
    if (content === savedContent || saving) return;
    const timer = window.setTimeout(() => {
      void persistDraft(content).catch(() => undefined);
    }, 900);
    return () => window.clearTimeout(timer);
  }, [
    activeAssignmentId,
    content,
    persistDraft,
    recoverableContent,
    savedContent,
    saving,
    workspace,
  ]);

  const saveBeforeAction = useCallback(async () => {
    if (content !== savedContent) await persistDraft(content);
  }, [content, persistDraft, savedContent]);

  async function requestSuggestion(selected: Selection | null) {
    if (!activeAssignmentId || !workspace || !workspace.license.active) return;
    setGenerating(true);
    setSuggestion("");
    setError(null);
    setNotice(null);
    try {
      await saveBeforeAction();
      const result = await requestJson<Suggestion>(
        `/assignments/${activeAssignmentId}/suggestions`,
        {
          method: "POST",
          body: JSON.stringify({
            action: content.trim() ? "rewrite" : "generate",
            length,
            style,
            selected_text: selected?.text ?? null,
            instruction: instruction.trim() || null,
          }),
        },
      );
      setSuggestion(result.suggestion);
      setSuggestionSelection(selected);
      setSuggestionSourceContent(content);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not generate a suggestion.");
    } finally {
      setGenerating(false);
    }
  }

  async function acceptSuggestion() {
    if (!suggestion || workspace?.license.active !== true) return;
    if (content !== suggestionSourceContent) {
      if (suggestionSelection) {
        setError("Your draft changed after this section suggestion was created. Generate a new suggestion for the current text.");
        return;
      }
      if (!window.confirm("Your draft changed after this suggestion was created. Applying it will replace the current draft. Continue?")) {
        return;
      }
    }
    let nextContent = suggestion;
    if (suggestionSelection) {
      nextContent =
        content.slice(0, suggestionSelection.start) +
        suggestion +
        content.slice(suggestionSelection.end);
    }
    setContent(nextContent);
    setSuggestion("");
    setSuggestionSelection(null);
    setSuggestionSourceContent("");
    setNotice("Suggestion accepted and saved as a new version.");
    try {
      await persistDraft(nextContent, "ai");
    } catch {
      setNotice(null);
    }
  }

  async function restoreVersion(version: DraftVersion) {
    if (!activeAssignmentId || workspace?.license.active !== true) return;
    if (!window.confirm(`Restore version ${version.version}? Your current text will remain in version history.`)) {
      return;
    }
    try {
      const result = await requestJson<SaveResult>(
        `/assignments/${activeAssignmentId}/versions/restore`,
        {
          method: "POST",
          body: JSON.stringify({ version_id: version.id }),
        },
      );
      setContent(result.draft_content);
      setSavedContent(result.draft_content);
      setSelectedVersion(null);
      setNotice(`Restored version ${version.version}; your previous versions remain available.`);
      const refreshed = await requestJson<Workspace>(
        `/assignments/${activeAssignmentId}/workspace`,
      );
      setWorkspace(refreshed);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not restore this version.");
    }
  }

  async function exportDocument(format: "pdf" | "docx" | "csv", preview = false) {
    if (!activeAssignmentId || workspace?.license.active !== true) return;
    setExporting(format);
    setError(null);
    try {
      await saveBeforeAction();
      const result = await fetchDocument(activeAssignmentId, format);
      const refreshedWorkspace = await requestJson<Workspace>(
        `/assignments/${activeAssignmentId}/workspace`,
      );
      setWorkspace(refreshedWorkspace);
      if (preview) {
        if (format !== "pdf") return;
        setSavedPdfUrl(URL.createObjectURL(result.blob));
        setPdfPreviewContent(content);
        setDocumentVersion(result.version);
      } else {
        const url = URL.createObjectURL(result.blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `${workspace?.assignment.title || "assignment"}.${format}`;
        link.click();
        window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
        setDocumentVersion(result.version);
        setNotice(
          `${format.toUpperCase()} downloaded from saved version ${result.version ?? "latest"}.`,
        );
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : `Could not export ${format.toUpperCase()}.`);
    } finally {
      setExporting(null);
    }
  }

  async function approveCurrentPdf() {
    if (!activeAssignmentId || workspace?.license.active !== true) return;
    try {
      await requestJson(`/assignments/${activeAssignmentId}/approve`, { method: "POST" });
      setWorkspace(await requestJson<Workspace>(`/assignments/${activeAssignmentId}/workspace`));
      setNotice("The latest PDF is approved. Submit it to Google Classroom when you are ready.");
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not approve this PDF.");
    }
  }

  async function submitApprovedPdf() {
    if (!activeAssignmentId || workspace?.license.active !== true) return;
    if (!window.confirm("Submit the approved PDF to Google Classroom now?")) return;
    try {
      const result = await requestJson<{ message: string }>(
        `/assignments/${activeAssignmentId}/submit`,
        { method: "POST" },
      );
      setWorkspace(await requestJson<Workspace>(`/assignments/${activeAssignmentId}/workspace`));
      setNotice(result.message);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not submit this assignment.");
    }
  }

  async function downloadSavedExport(exportId: number, format: "pdf" | "docx" | "csv") {
    if (!activeAssignmentId || workspace?.license.active !== true) return;
    try {
      const response = await fetch(
        `/api/assignments/${activeAssignmentId}/exports/${exportId}`,
        { credentials: "include" },
      );
      if (!response.ok) {
        const result = await response.json().catch(() => null) as { detail?: unknown } | null;
        throw new Error(
          typeof result?.detail === "string" ? result.detail : "Could not download the saved document.",
        );
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `${workspace?.assignment.title || "assignment"}.${format}`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not download the saved document.");
    }
  }

  const currentStudent = workspace?.student ?? student;
  const currentAssignment = workspace?.assignment.id === activeAssignmentId
    ? workspace.assignment
    : undefined;
  const currentVersion = workspace?.versions[0]?.version;
  const hasLatestPdf = Boolean(
    currentVersion &&
    workspace?.exports.some(
      (exported) => exported.format === "pdf" && exported.version === currentVersion,
    ),
  );

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-slate-800 bg-[#111A2B] p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-white">Assignment Workspace</h2>
            <p className="mt-1 text-sm text-slate-400">
              Edit your draft, review AI suggestions, and preview or export saved content.
            </p>
            {currentAssignment && (
              <>
                <p className="mt-2 text-xs text-cyan-200">
                  Processing: {currentAssignment.processing_status.replaceAll("_", " ")}
                  {currentAssignment.submission_status === "turned_in" ? " · Submitted" : ""}
                </p>
                {currentAssignment.processing_error && (
                  <p role="alert" className="mt-1 text-xs text-rose-300">
                    {currentAssignment.processing_error}
                  </p>
                )}
              </>
            )}
          </div>
          {currentAssignment && (
            <button
              onClick={() => onSelectAssignment(null)}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:border-slate-500"
            >
              <ArrowLeft className="h-4 w-4" /> Choose another
            </button>
          )}
        </div>
        {!currentAssignment && (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {assignments.length === 0 ? (
              <p className="text-sm text-slate-400">
                Sync Google Classroom to load assignments into your workspace.
              </p>
            ) : assignments.map((assignment) => (
              <button
                key={assignment.id}
                onClick={() => onSelectAssignment(assignment.id)}
                className="rounded-xl border border-slate-700 bg-slate-900/50 p-4 text-left transition hover:border-blue-500/60 hover:bg-slate-900"
              >
                <span className="block font-medium text-slate-100">{assignment.title}</span>
                <span className="mt-1 block text-xs text-slate-400">{assignment.course}</span>
                <span className="mt-2 block text-xs text-slate-500">{assignment.deadline}</span>
                {assignment.processing_status && (
                  <span className="mt-2 block text-xs text-cyan-200">
                    {assignment.processing_status.replaceAll("_", " ")}
                  </span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {error && (
        <div role="alert" className="rounded-xl border border-rose-800/60 bg-rose-900/20 p-3 text-sm text-rose-200">
          {error}
        </div>
      )}
      {notice && (
        <div role="status" className="rounded-xl border border-emerald-800/60 bg-emerald-900/20 p-3 text-sm text-emerald-200">
          {notice}
        </div>
      )}

      {activeAssignmentId && !workspace && !error && (
        <div className="flex items-center justify-center gap-2 py-12 text-sm text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading assignment…
        </div>
      )}

      {currentAssignment && (
        <>
          <div className="rounded-2xl border border-slate-800 bg-[#111A2B] p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="text-xl font-semibold text-white">{currentAssignment.title}</h3>
                <p className="mt-1 text-sm text-slate-400">
                  {currentAssignment.course ?? "Course not provided"}
                  {currentAssignment.due_date
                    ? ` · Due ${new Date(currentAssignment.due_date).toLocaleDateString()}`
                    : ""}
                </p>
              </div>
              <span className="text-xs text-slate-400" role="status">
                {saving ? "Saving…" : content === savedContent ? "All changes saved" : "Unsaved changes"}
                {currentVersion ? ` · Version ${currentVersion}` : ""}
              </span>
            </div>
            {currentAssignment.instructions && (
              <details className="mt-4 rounded-lg border border-slate-800 bg-slate-900/50 p-3">
                <summary className="cursor-pointer text-sm font-medium text-slate-300">
                  Assignment instructions
                </summary>
                <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-400">
                  {currentAssignment.instructions}
                </p>
              </details>
            )}
            {currentAssignment && !licenseActive && workspace && (
              <p
                role="status"
                className="mt-4 rounded-lg border border-amber-700/50 bg-amber-900/20 p-3 text-sm text-amber-100"
              >
                {workspace.license.status === "expired"
                  ? "Your semester license has expired."
                  : `Your semester license is ${workspace.license.status.replaceAll("_", " ")}.`}{" "}
                Assignment editing, AI generation, version restoration, exports, approval, and submission are read-only.
                Cached Google Classroom data remains available. Renew or check your status in Payments &amp; License.
              </p>
            )}
            {currentAssignment.attachments.length > 0 && (
              <div className="mt-3 rounded-lg border border-slate-800 bg-slate-900/50 p-3">
                <h4 className="text-sm font-medium text-slate-300">Classroom materials</h4>
                <ul className="mt-2 space-y-1">
                  {currentAssignment.attachments.map((attachment, index) => {
                    const link = safeUrl(attachment.url);
                    return (
                      <li key={`${attachment.id ?? attachment.title ?? "material"}-${index}`}>
                        {link ? (
                          <a
                            href={link}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-sm text-blue-300 hover:underline"
                          >
                            {attachment.title || "Open classroom material"}
                          </a>
                        ) : (
                          <span className="text-sm text-slate-400">
                            {attachment.title || "Classroom material"}
                          </span>
                        )}
                        {attachment.type && (
                          <span className="ml-2 text-xs text-slate-500">{attachment.type}</span>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
            {recoverableContent !== null && (
              <div className="mt-4 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-700/50 bg-amber-900/20 p-3">
                <p className="text-sm text-amber-100">Unsaved browser recovery text is available.</p>
                <div className="flex gap-2">
                  <button
                    onClick={() => {
                      setContent(recoverableContent);
                      setRecoverableContent(null);
                    }}
                    className="rounded-md bg-amber-500/20 px-3 py-1.5 text-xs text-amber-100 hover:bg-amber-500/30"
                  >
                    Recover edits
                  </button>
                  <button
                    onClick={() => {
                      setRecoverableContent(null);
                      window.localStorage.setItem(
                        `classmate-ai:draft:${activeAssignmentId}`,
                        content,
                      );
                    }}
                    className="rounded-md px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            )}
            <div className="mt-4 grid gap-5 xl:grid-cols-2">
              <div className="space-y-3">
                <label htmlFor="assignment-editor" className="block text-sm font-medium text-slate-200">
                  Your assignment draft
                </label>
                <textarea
                  ref={editorRef}
                  id="assignment-editor"
                  value={content}
                  readOnly={!licenseActive}
                  onChange={(event) => setContent(event.target.value)}
                  onSelect={(event) => {
                    const target = event.currentTarget;
                    const start = target.selectionStart;
                    const end = target.selectionEnd;
                    const text = target.value.slice(start, end);
                    setSelection(text.trim() ? { start, end, text } : null);
                  }}
                  placeholder="Generate a draft from the assignment instructions, or start writing here…"
                  maxLength={100_000}
                  className="min-h-[420px] w-full resize-y rounded-xl border border-slate-700 bg-slate-950/70 p-4 text-sm leading-6 text-slate-100 outline-none focus:border-blue-500"
                />
                <p className="text-xs text-slate-500">
                  Changes save automatically. Unsaved text is also kept in this browser for recovery.
                </p>
                <div className="flex flex-wrap gap-2">
                  <button
                    onClick={() => void persistDraft(content).catch(() => undefined)}
                    disabled={saving || !licenseActive}
                    className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 hover:border-slate-500 disabled:opacity-50"
                  >
                    {saving ? "Saving…" : "Save now"}
                  </button>
                  <button
                    onClick={() => void requestSuggestion(null)}
                    disabled={generating || saving || !licenseActive}
                    className="inline-flex items-center gap-2 rounded-lg bg-blue-500 px-3 py-2 text-sm font-medium text-white hover:bg-blue-400 disabled:opacity-50"
                  >
                    {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                    {content.trim() ? "Regenerate full draft" : "Generate draft"}
                  </button>
                  <button
                    onClick={() => void requestSuggestion(selection)}
                    disabled={generating || saving || !selection || !licenseActive}
                    className="inline-flex items-center gap-2 rounded-lg border border-blue-500/50 px-3 py-2 text-sm text-blue-200 hover:bg-blue-500/10 disabled:opacity-40"
                  >
                    <Sparkles className="h-4 w-4" /> Rewrite selection
                  </button>
                </div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <label className="text-xs text-slate-400">
                    Length
                    <select
                      value={length}
                      onChange={(event) => setLength(event.target.value)}
                      className="mt-1 block w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-sm text-slate-200"
                    >
                      <option value="short">Short</option>
                      <option value="standard">Standard</option>
                      <option value="detailed">Detailed</option>
                    </select>
                  </label>
                  <label className="text-xs text-slate-400">
                    Writing style
                    <select
                      value={style}
                      onChange={(event) => setStyle(event.target.value)}
                      className="mt-1 block w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-sm text-slate-200"
                    >
                      <option value="academic">Academic</option>
                      <option value="simple">Simple English</option>
                      <option value="formal">Formal</option>
                    </select>
                  </label>
                  <label className="text-xs text-slate-400">
                    Custom instructions
                    <input
                      value={instruction}
                      onChange={(event) => setInstruction(event.target.value)}
                      maxLength={2_000}
                      placeholder="e.g. improve the conclusion"
                      className="mt-1 block w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-2 text-sm text-slate-200 placeholder:text-slate-600"
                    />
                  </label>
                </div>
                {suggestion && (
                  <div className="rounded-xl border border-blue-500/40 bg-blue-950/20 p-4">
                    <div className="mb-3 flex items-center justify-between">
                      <h4 className="font-medium text-blue-100">AI suggestion — review before applying</h4>
                      <button
                        onClick={() => {
                          setSuggestion("");
                          setSuggestionSelection(null);
                          setSuggestionSourceContent("");
                        }}
                        aria-label="Reject suggestion"
                        className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
                      >
                        <X className="h-4 w-4" />
                      </button>
                    </div>
                    <div className="max-h-72 overflow-y-auto whitespace-pre-wrap text-sm leading-6 text-slate-200">
                      {suggestion}
                    </div>
                    <button
                      onClick={() => void acceptSuggestion()}
                      disabled={!licenseActive}
                      className="mt-3 inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-500"
                    >
                      <Check className="h-4 w-4" /> Accept and save as new version
                    </button>
                  </div>
                )}
              </div>

              <div className="space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h4 className="text-sm font-medium text-slate-200">Live document preview</h4>
                    <p className="mt-1 text-xs text-slate-500">
                      This preview uses your current text; export a PDF for the final page layout.
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button
                      onClick={() => void exportDocument("pdf", true)}
                      disabled={exporting !== null || saving || !licenseActive}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-2.5 py-2 text-xs text-slate-200 hover:border-slate-500 disabled:opacity-50"
                    >
                      {exporting === "pdf" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <FileText className="h-3.5 w-3.5" />}
                      Preview PDF
                    </button>
                    <button
                      onClick={() => void exportDocument("pdf")}
                      disabled={exporting !== null || saving || !licenseActive}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-rose-600 px-2.5 py-2 text-xs font-medium text-white hover:bg-rose-500 disabled:opacity-50"
                    >
                      <Download className="h-3.5 w-3.5" /> Download PDF
                    </button>
                    <button
                      onClick={() => void exportDocument("docx")}
                      disabled={exporting !== null || saving || !licenseActive}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-2.5 py-2 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-50"
                    >
                      <Download className="h-3.5 w-3.5" /> Download DOCX
                    </button>
                    <button
                      onClick={() => void exportDocument("csv")}
                      disabled={exporting !== null || saving || !licenseActive}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-700 px-2.5 py-2 text-xs font-medium text-white hover:bg-emerald-600 disabled:opacity-50"
                    >
                      {exporting === "csv"
                        ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        : <Download className="h-3.5 w-3.5" />}
                      Download Project Schedule CSV
                    </button>
                    <button
                      onClick={() => void approveCurrentPdf()}
                      disabled={
                        exporting !== null ||
                        saving ||
                        !licenseActive ||
                        !currentAssignment.latest_version ||
                        currentAssignment.latest_version !== currentVersion ||
                        !hasLatestPdf ||
                        currentAssignment.approved ||
                        content !== savedContent
                      }
                      className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/50 px-2.5 py-2 text-xs text-emerald-200 hover:bg-emerald-500/10 disabled:opacity-40"
                    >
                      <Check className="h-3.5 w-3.5" />
                      {currentAssignment.approved ? "PDF approved" : "Approve latest PDF"}
                    </button>
                    {currentAssignment.approved && (
                      <button
                        onClick={() => void submitApprovedPdf()}
                        disabled={
                          !licenseActive ||
                          currentAssignment.submission_status === "turned_in" ||
                          saving ||
                          content !== savedContent
                        }
                        className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-2.5 py-2 text-xs font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
                      >
                        {currentAssignment.submission_status === "turned_in"
                          ? "Submitted"
                          : "Submit to Classroom"}
                      </button>
                    )}
                  </div>
                </div>
                <div className="max-h-[560px] overflow-y-auto rounded-xl bg-slate-800 p-3">
                  {savedPdfUrl && pdfPreviewContent === content ? (
                    <iframe
                      src={savedPdfUrl}
                      title={`PDF preview for ${currentAssignment.title}`}
                      className="h-[540px] w-full rounded-lg bg-white"
                    />
                  ) : (
                    <article className="mx-auto min-h-[480px] max-w-[620px] bg-white px-8 py-10 shadow-xl sm:px-12">
                      <header className="mb-10 border-b border-slate-200 pb-6 text-center">
                        <h2 className="text-xl font-bold text-slate-900">{currentAssignment.title}</h2>
                        <p className="mt-3 text-sm text-slate-600">
                          {currentStudent?.full_name || "Student name not provided"}
                        </p>
                        {currentStudent?.roll_number && (
                          <p className="mt-1 text-sm text-slate-600">
                            Roll number: {currentStudent.roll_number}
                          </p>
                        )}
                        {currentStudent?.department && (
                          <p className="mt-1 text-sm text-slate-600">{currentStudent.department}</p>
                        )}
                        {currentStudent?.semester && (
                          <p className="mt-1 text-sm text-slate-600">
                            Semester: {currentStudent.semester}
                          </p>
                        )}
                        {currentAssignment.course && (
                          <p className="mt-1 text-sm text-slate-600">{currentAssignment.course}</p>
                        )}
                      </header>
                      {content ? renderDocumentContent(content) : (
                        <p className="text-sm text-slate-400">
                          Your assignment content will appear here as you write.
                        </p>
                      )}
                    </article>
                  )}
                  {savedPdfUrl && documentVersion && (
                    <p className="mt-2 text-center text-xs text-slate-400">
                      PDF generated from saved version {documentVersion}.
                    </p>
                  )}
                </div>
              </div>
            </div>
          </div>

          <section className="rounded-2xl border border-slate-800 bg-[#111A2B] p-5">
            <div className="mb-4 flex items-center gap-2">
              <History className="h-4 w-4 text-slate-400" />
              <h3 className="font-semibold text-white">Version history</h3>
            </div>
            {workspace?.versions.length ? (
              <div className="space-y-2">
                {workspace.versions.map((version) => (
                  <div
                    key={version.id}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-800 bg-slate-900/40 p-3"
                  >
                    <div>
                      <p className="text-sm font-medium text-slate-200">
                        Version {version.version} · {version.source}
                      </p>
                      <p className="mt-1 text-xs text-slate-500">
                        {new Date(version.created_at).toLocaleString()}
                        {version.note ? ` · ${version.note}` : ""}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setSelectedVersion(version)}
                        className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:border-slate-500"
                      >
                        View
                      </button>
                      <button
                        onClick={() => void restoreVersion(version)}
                        disabled={!licenseActive}
                        className="inline-flex items-center gap-1 rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:border-amber-500/60 hover:text-amber-100"
                      >
                        <RotateCcw className="h-3.5 w-3.5" /> Restore
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-slate-500">Saved drafts and accepted suggestions will appear here.</p>
            )}
          </section>

          <section className="rounded-2xl border border-slate-800 bg-[#111A2B] p-5">
            <div className="mb-4 flex items-center gap-2">
              <FileText className="h-4 w-4 text-slate-400" />
              <h3 className="font-semibold text-white">Generated document history</h3>
            </div>
            {workspace?.exports.length ? (
              <div className="space-y-2">
                {workspace.exports.map((exported) => (
                  <div
                    key={exported.id}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-800 bg-slate-900/40 p-3"
                  >
                    <p className="text-sm text-slate-200">
                      {exported.format.toUpperCase()} · saved version {exported.version}
                    </p>
                    <div className="flex items-center gap-3">
                      <p className="text-xs text-slate-500">
                        {new Date(exported.created_at).toLocaleString()}
                      </p>
                      <button
                        type="button"
                        onClick={() => void downloadSavedExport(exported.id, exported.format)}
                        disabled={!licenseActive}
                        className="text-xs text-blue-300 hover:underline"
                      >
                        Download
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-slate-500">
                Your exported PDF and DOCX versions will be listed here.
              </p>
            )}
          </section>
        </>
      )}

      {selectedVersion && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="version-preview-title"
          className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/80 p-4"
          onClick={(event) => {
            if (event.target === event.currentTarget) setSelectedVersion(null);
          }}
        >
          <div className="w-full max-w-3xl rounded-2xl border border-slate-700 bg-[#111A2B] p-5 shadow-2xl">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h3 id="version-preview-title" className="font-semibold text-white">
                  Version {selectedVersion.version}
                </h3>
                <p className="mt-1 text-xs text-slate-400">
                  {selectedVersion.source} · {new Date(selectedVersion.created_at).toLocaleString()}
                </p>
              </div>
              <button
                onClick={() => setSelectedVersion(null)}
                aria-label="Close version preview"
                className="rounded p-1 text-slate-400 hover:bg-slate-800 hover:text-white"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-xl bg-slate-950 p-4 text-sm leading-6 text-slate-200">
              {selectedVersion.content}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}
