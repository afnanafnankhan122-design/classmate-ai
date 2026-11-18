"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Banknote,
  CheckCircle2,
  Download,
  Loader2,
  ReceiptText,
  RefreshCw,
  Save,
  ShieldCheck,
  Upload,
  XCircle,
} from "lucide-react";
import { requestJson } from "@/lib/api";

type LicenseStatus = {
  status: string;
  active: boolean;
  source: string | null;
  starts_at: string | null;
  expires_at: string | null;
  reason: string | null;
};

type PaymentMethod = {
  id: number;
  code: string;
  name: string;
  account_holder_name: string | null;
  account_number: string | null;
  instructions: string | null;
  is_enabled?: boolean;
  details_verified_at?: string | null;
};

type Payment = {
  id: number;
  status: "pending" | "approved" | "rejected";
  amount_paisa: number;
  currency: string;
  duration_months: number;
  payment_method: string | null;
  transaction_reference: string;
  submitted_at: string | null;
  reviewed_at: string | null;
  rejection_reason: string | null;
  receipt_available: boolean;
  license_started_at: string | null;
  license_expires_at: string | null;
  refunded_at: string | null;
  refund_reason: string | null;
  student?: { id: number; full_name: string; email: string };
};

type Plan = {
  id: number;
  code: string;
  name: string;
  amount_paisa: number;
  amount_pkr: number;
  currency: string;
  duration_months: number;
};

type LicensingPolicy = {
  launch_at: string | null;
  grandfathering_days: number;
  locked: boolean;
};

type LicenseRow = {
  user_id: number;
  student_name: string;
  student_email: string;
  status: string;
  starts_at: string;
  expires_at: string;
  revoked_at: string | null;
};

type AuditEntry = {
  id: number;
  user_id: number | null;
  payment_id: number | null;
  actor: string | null;
  action: string;
  details: Record<string, unknown> | null;
  created_at: string;
};

function formatDate(value: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

function StatusBadge({ status }: { status: string }) {
  const style =
    status === "approved" || status === "active"
      ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
      : status === "rejected" || status === "expired" || status === "revoked"
        ? "border-rose-500/30 bg-rose-500/10 text-rose-300"
        : "border-amber-500/30 bg-amber-500/10 text-amber-200";
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs capitalize ${style}`}>
      {status.replaceAll("_", " ")}
    </span>
  );
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-slate-800 bg-[#111A2B] p-4 md:p-5">
      <div className="mb-4 border-b border-slate-800 pb-3">
        <h2 className="font-semibold text-white">{title}</h2>
        {description && <p className="mt-1 text-sm text-slate-400">{description}</p>}
      </div>
      {children}
    </section>
  );
}

export function LicensingView() {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [methods, setMethods] = useState<PaymentMethod[]>([]);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [license, setLicense] = useState<LicenseStatus | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selectedMethod, setSelectedMethod] = useState("");
  const [reference, setReference] = useState("");
  const [receipt, setReceipt] = useState<File | null>(null);

  const loadStudentData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [planResult, methodResult, paymentResult, licenseResult, adminResult] =
        await Promise.all([
          requestJson<{ plans: Plan[] }>("/plans"),
          requestJson<{ payment_methods: PaymentMethod[] }>("/payments/methods"),
          requestJson<{ payments: Payment[] }>("/payments/my"),
          requestJson<LicenseStatus>("/licenses/status"),
          requestJson<{ is_admin: boolean }>("/admin/access"),
        ]);
      setPlans(planResult.plans);
      setMethods(methodResult.payment_methods);
      setPayments(paymentResult.payments);
      setLicense(licenseResult);
      setIsAdmin(adminResult.is_admin);
      setSelectedMethod((current) =>
        methodResult.payment_methods.some((method) => String(method.id) === current)
          ? current
          : String(methodResult.payment_methods[0]?.id ?? ""),
      );
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Could not load payment information.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadStudentData(), 0);
    return () => window.clearTimeout(timer);
  }, [loadStudentData]);

  const activePlan = plans[0];
  const pendingPayment = payments.some((payment) => payment.status === "pending");
  const chosenMethod = useMemo(
    () => methods.find((method) => String(method.id) === selectedMethod) ?? null,
    [methods, selectedMethod],
  );

  async function submitPayment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    if (!receipt || !chosenMethod) {
      setError("Choose an enabled payment method and attach your receipt.");
      return;
    }
    if (receipt.size > 5 * 1024 * 1024) {
      setError("The receipt must be 5 MiB or smaller.");
      return;
    }
    setBusy(true);
    const formData = new FormData();
    formData.set("payment_method_id", String(chosenMethod.id));
    formData.set("transaction_reference", reference);
    formData.set("receipt", receipt);
    try {
      await requestJson<Payment>("/payments/submit", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: formData,
      });
      setReference("");
      setReceipt(null);
      const input = document.getElementById("payment-receipt") as HTMLInputElement | null;
      if (input) input.value = "";
      setNotice("Payment submitted. Your license will begin only after an administrator approves it.");
      await loadStudentData();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Payment could not be submitted.");
    } finally {
      setBusy(false);
    }
  }

  async function downloadReceipt(paymentId: number) {
    setError(null);
    try {
      const response = await fetch(`/api/payments/${paymentId}/receipt`, {
        credentials: "include",
      });
      if (!response.ok) {
        throw new Error(response.status === 404 ? "Receipt is not available." : "Receipt could not be downloaded.");
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = `classmate-payment-${paymentId}-receipt.${blob.type === "image/png" ? "png" : "jpg"}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Receipt could not be downloaded.");
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-slate-400">Manual payment verification</p>
          <p className="mt-1 text-2xl font-semibold text-white">Semester license</p>
        </div>
        <button
          type="button"
          onClick={() => void loadStudentData()}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/60 px-3 py-2 text-sm text-slate-200 hover:border-slate-500 disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {error && (
        <div role="alert" className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-sm text-rose-200">
          <AlertTriangle className="mr-2 inline h-4 w-4" />
          {error}
        </div>
      )}
      {notice && (
        <div role="status" className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-200">
          <CheckCircle2 className="mr-2 inline h-4 w-4" />
          {notice}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[0.8fr_1.2fr]">
        <Section title="Your access" description="Your current license status and access period.">
          {loading && !license ? (
            <div className="flex items-center gap-2 py-4 text-sm text-slate-400">
              <Loader2 className="h-4 w-4 animate-spin" /> Checking license…
            </div>
          ) : license ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm text-slate-400">Status</span>
                <StatusBadge status={license.status} />
              </div>
              {license.source && (
                <p className="text-sm text-slate-300">
                  Access type: <span className="capitalize">{license.source}</span>
                </p>
              )}
              {license.expires_at && (
                <p className="text-sm text-slate-300">Access until: {formatDate(license.expires_at)}</p>
              )}
              {!license.active && (
                <p className="rounded-lg border border-amber-500/20 bg-amber-500/5 p-3 text-sm text-amber-100">
                  Your saved Classroom information remains available read-only. Payment verification is required to resume syncing.
                </p>
              )}
            </div>
          ) : (
            <p className="text-sm text-slate-400">License status is unavailable.</p>
          )}
        </Section>

        <Section title="Semester payment" description="Pay PKR 500 for six calendar months. An administrator must verify every payment.">
          <div className="mb-4 flex flex-wrap items-center gap-3 rounded-xl border border-blue-500/20 bg-blue-500/5 p-3">
            <Banknote className="h-5 w-5 text-blue-300" />
            <p className="text-sm text-slate-200">
              {activePlan
                ? `${activePlan.currency} ${activePlan.amount_pkr.toLocaleString()} · ${activePlan.duration_months} months`
                : "PKR 500 · 6 months"}
            </p>
          </div>
          {pendingPayment ? (
            <p className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-100">
              You have a payment awaiting verification. A duplicate request cannot be submitted until it is approved or rejected.
            </p>
          ) : methods.length === 0 ? (
            <p className="rounded-xl border border-slate-700 bg-slate-900/50 p-4 text-sm text-slate-300">
              No verified payment methods are available yet. Please check back after an administrator configures the real payment details.
            </p>
          ) : (
            <form className="space-y-4" onSubmit={(event) => void submitPayment(event)}>
              <label className="block space-y-1.5 text-sm">
                <span className="text-slate-300">Payment method</span>
                <select
                  value={selectedMethod}
                  onChange={(event) => setSelectedMethod(event.target.value)}
                  className="w-full rounded-xl border border-slate-700 bg-slate-950/70 px-3 py-2.5 text-slate-100 outline-none focus:border-blue-500"
                  required
                >
                  {methods.map((method) => (
                    <option key={method.id} value={method.id}>{method.name}</option>
                  ))}
                </select>
              </label>

              {chosenMethod && (
                <div className="space-y-2 rounded-xl border border-slate-800 bg-slate-900/55 p-4 text-sm">
                  <p className="font-medium text-white">{chosenMethod.name} payment details</p>
                  <p className="text-slate-300">
                    Account holder: <span className="text-slate-100">{chosenMethod.account_holder_name}</span>
                  </p>
                  <p className="text-slate-300">
                    Account / wallet: <span className="break-all font-mono text-slate-100">{chosenMethod.account_number}</span>
                  </p>
                  <p className="whitespace-pre-wrap text-slate-400">{chosenMethod.instructions}</p>
                  <p className="text-xs text-amber-200">Enter the payment transaction/reference ID. Do not upload sensitive account credentials.</p>
                </div>
              )}

              <label className="block space-y-1.5 text-sm">
                <span className="text-slate-300">Transaction / reference ID</span>
                <input
                  value={reference}
                  onChange={(event) => setReference(event.target.value)}
                  minLength={3}
                  maxLength={128}
                  required
                  autoComplete="off"
                  className="w-full rounded-xl border border-slate-700 bg-slate-950/70 px-3 py-2.5 text-slate-100 outline-none placeholder:text-slate-500 focus:border-blue-500"
                  placeholder="Enter the reference shown by your payment service"
                />
              </label>

              <label className="block space-y-1.5 text-sm">
                <span className="text-slate-300">Receipt screenshot (JPG, JPEG, or PNG; max 5 MiB)</span>
                <span className="flex items-center gap-2 rounded-xl border border-dashed border-slate-700 bg-slate-950/50 px-3 py-3 text-slate-400">
                  <Upload className="h-4 w-4 shrink-0" />
                  <input
                    id="payment-receipt"
                    type="file"
                    accept=".jpg,.jpeg,.png,image/jpeg,image/png"
                    required
                    onChange={(event) => setReceipt(event.target.files?.[0] ?? null)}
                    className="min-w-0 flex-1 text-xs file:mr-3 file:rounded-lg file:border-0 file:bg-slate-800 file:px-3 file:py-2 file:text-xs file:text-slate-200"
                  />
                </span>
              </label>

              <button
                type="submit"
                disabled={busy || loading || pendingPayment}
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-3 text-sm font-medium text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
              >
                {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ReceiptText className="h-4 w-4" />}
                Submit for verification
              </button>
            </form>
          )}
        </Section>
      </div>

      <Section title="Payment history" description="Rejected payments include the administrator's reason and can be resubmitted with a new reference.">
        {payments.length === 0 ? (
          <p className="py-5 text-center text-sm text-slate-500">No payment submissions yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-[700px] w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-slate-500">
                <tr className="border-b border-slate-800">
                  <th className="pb-3 pr-4">Submitted</th>
                  <th className="pb-3 pr-4">Method / reference</th>
                  <th className="pb-3 pr-4">Amount</th>
                  <th className="pb-3 pr-4">Status</th>
                  <th className="pb-3">Receipt</th>
                </tr>
              </thead>
              <tbody>
                {payments.map((payment) => (
                  <tr key={payment.id} className="border-b border-slate-800/70 align-top last:border-0">
                    <td className="py-3 pr-4 text-slate-400">{formatDate(payment.submitted_at)}</td>
                    <td className="py-3 pr-4">
                      <p className="text-slate-200">{payment.payment_method}</p>
                      <p className="break-all font-mono text-xs text-slate-500">{payment.transaction_reference}</p>
                      {payment.rejection_reason && (
                        <p className="mt-2 max-w-sm text-xs text-rose-300">Reason: {payment.rejection_reason}</p>
                      )}
                    </td>
                    <td className="py-3 pr-4 text-slate-300">{payment.currency} {(payment.amount_paisa / 100).toLocaleString()}</td>
                    <td className="py-3 pr-4">
                      <StatusBadge status={payment.refunded_at ? "refunded" : payment.status} />
                      <p className="mt-1 max-w-xs text-xs text-slate-400">
                        {payment.refunded_at
                          ? "Refund recorded."
                          : payment.status === "pending"
                            ? "Awaiting administrator verification."
                            : payment.status === "approved"
                              ? `Verified. License through ${formatDate(payment.license_expires_at)}.`
                              : "Not approved. Review the reason and resubmit with a new reference."}
                      </p>
                    </td>
                    <td className="py-3">
                      {payment.receipt_available ? (
                        <button
                          type="button"
                          onClick={() => void downloadReceipt(payment.id)}
                          className="inline-flex items-center gap-1.5 text-xs text-blue-300 hover:text-blue-200"
                        >
                          <Download className="h-3.5 w-3.5" /> Download
                        </button>
                      ) : (
                        <span className="text-xs text-slate-500">Retained metadata only</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {isAdmin && (
        <AdminLicensingPanel
          onError={setError}
          onNotice={setNotice}
          onRefresh={loadStudentData}
          onDownloadReceipt={downloadReceipt}
        />
      )}
    </div>
  );
}

function AdminLicensingPanel({
  onError,
  onNotice,
  onRefresh,
  onDownloadReceipt,
}: {
  onError: (message: string | null) => void;
  onNotice: (message: string | null) => void;
  onRefresh: () => Promise<void>;
  onDownloadReceipt: (paymentId: number) => Promise<void>;
}) {
  const [payments, setPayments] = useState<Payment[]>([]);
  const [methods, setMethods] = useState<PaymentMethod[]>([]);
  const [licenses, setLicenses] = useState<LicenseRow[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditEntry[]>([]);
  const [policy, setPolicy] = useState<LicensingPolicy | null>(null);
  const [password, setPassword] = useState("");
  const [statusFilter, setStatusFilter] = useState("pending");
  const [reasons, setReasons] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);

  const loadAdminData = useCallback(async () => {
    setLoading(true);
    onError(null);
    try {
      const [paymentResult, methodResult, licenseResult, auditResult, policyResult] =
        await Promise.all([
          requestJson<{ payments: Payment[] }>(`/admin/payments?status=${statusFilter}`),
          requestJson<{ payment_methods: PaymentMethod[] }>("/admin/payment-methods"),
          requestJson<{ licenses: LicenseRow[] }>("/admin/licenses"),
          requestJson<{ audit_logs: AuditEntry[] }>("/admin/audit-logs?limit=100"),
          requestJson<LicensingPolicy>("/admin/license-policy"),
        ]);
      setPayments(paymentResult.payments);
      setMethods(methodResult.payment_methods);
      setLicenses(licenseResult.licenses);
      setAuditLogs(auditResult.audit_logs);
      setPolicy(policyResult);
    } catch (requestError) {
      onError(requestError instanceof Error ? requestError.message : "Could not load administrator data.");
    } finally {
      setLoading(false);
    }
  }, [onError, statusFilter]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadAdminData(), 0);
    return () => window.clearTimeout(timer);
  }, [loadAdminData]);

  async function decide(paymentId: number, decision: "approve" | "reject" | "refund") {
    onError(null);
    onNotice(null);
    setBusy(true);
    try {
      const path = `/admin/payments/${paymentId}/${decision}`;
      const body: Record<string, string> = { password };
      if (decision !== "approve") {
        const reason = reasons[paymentId]?.trim();
        if (!reason) {
          onError(decision === "reject" ? "A rejection reason is required." : "A refund reason is required.");
          return;
        }
        body.reason = reason;
      }
      await requestJson(path, { method: "POST", body: JSON.stringify(body) });
      onNotice(
        decision === "approve"
          ? "Payment approved and license activated."
          : decision === "reject"
            ? "Payment rejected; the student can resubmit."
            : "Refund recorded. A license backed by this payment may have been revoked.",
      );
      await Promise.all([loadAdminData(), onRefresh()]);
    } catch (requestError) {
      onError(requestError instanceof Error ? requestError.message : "Administrator action failed.");
    } finally {
      setBusy(false);
    }
  }

  async function updateMethod(method: PaymentMethod, form: HTMLFormElement) {
    const data = new FormData(form);
    const body = {
      password,
      name: String(data.get("name") ?? ""),
      account_holder_name: String(data.get("account_holder_name") ?? ""),
      account_number: String(data.get("account_number") ?? ""),
      instructions: String(data.get("instructions") ?? ""),
      is_enabled: data.get("is_enabled") === "on",
      confirm_details_verified: data.get("confirm_details_verified") === "on",
    };
    setBusy(true);
    onError(null);
    try {
      await requestJson(`/admin/payment-methods/${method.id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      onNotice(`${method.name} payment configuration saved.`);
      await loadAdminData();
    } catch (requestError) {
      onError(requestError instanceof Error ? requestError.message : "Payment method could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  async function updatePolicy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!policy) {
      onError("Enter the official licensing launch date and time.");
      return;
    }
    const form = new FormData(event.currentTarget);
    const launchValue = String(form.get("launch_at") ?? "");
    const days = Number(form.get("grandfathering_days"));
    if (!launchValue || !Number.isInteger(days) || days < 1 || days > 365) {
      onError("Enter a valid launch time and a grandfather period between 1 and 365 days.");
      return;
    }
    setBusy(true);
    onError(null);
    try {
      await requestJson("/admin/license-policy", {
        method: "PATCH",
        body: JSON.stringify({
          password,
          launch_at: new Date(launchValue).toISOString(),
          grandfathering_days: days,
        }),
      });
      onNotice("Grandfathering policy saved. It locks when the launch time is reached.");
      await loadAdminData();
    } catch (requestError) {
      onError(requestError instanceof Error ? requestError.message : "Licensing policy could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  function localDateTime(value: string | null) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
    return local.toISOString().slice(0, 16);
  }

  return (
    <div className="space-y-5 border-t border-slate-800 pt-5">
      <Section title="Administrator payment review" description="Every sensitive action requires your current account password again. Verify the transaction independently; a receipt image is not proof of payment.">
        <div className="mb-4 grid gap-3 sm:grid-cols-[1fr_auto]">
          <label className="space-y-1.5 text-sm">
            <span className="text-slate-300">Reauthenticate for administrator actions</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="w-full rounded-xl border border-slate-700 bg-slate-950/70 px-3 py-2.5 text-slate-100 outline-none focus:border-blue-500"
              placeholder="Administrator password"
            />
          </label>
          <div className="flex items-end gap-2">
            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
              className="rounded-xl border border-slate-700 bg-slate-950/70 px-3 py-2.5 text-sm text-slate-100"
            >
              <option value="pending">Pending</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
              <option value="all">All</option>
            </select>
            <button type="button" onClick={() => void loadAdminData()} className="rounded-xl border border-slate-700 p-2.5 text-slate-300 hover:border-slate-500" aria-label="Refresh admin payments">
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            </button>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center gap-2 py-6 text-sm text-slate-400"><Loader2 className="h-4 w-4 animate-spin" /> Loading reviews…</div>
        ) : payments.length === 0 ? (
          <p className="py-5 text-center text-sm text-slate-500">No payments match this status.</p>
        ) : (
          <div className="space-y-3">
            {payments.map((payment) => (
              <article key={payment.id} className="rounded-xl border border-slate-800 bg-slate-950/35 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-medium text-white">{payment.student?.full_name ?? "Student"}</p>
                    <p className="text-xs text-slate-400">{payment.student?.email}</p>
                  </div>
                  <StatusBadge status={payment.refunded_at ? "refunded" : payment.status} />
                </div>
                <div className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
                  <p className="text-slate-300">Amount: {payment.currency} {(payment.amount_paisa / 100).toLocaleString()}</p>
                  <p className="text-slate-300">Method: {payment.payment_method}</p>
                  <p className="break-all font-mono text-xs text-slate-400">Reference: {payment.transaction_reference}</p>
                  <p className="text-slate-400">Submitted: {formatDate(payment.submitted_at)}</p>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  {payment.receipt_available && (
                    <button type="button" onClick={() => void onDownloadReceipt(payment.id)} className="inline-flex items-center gap-1.5 text-xs text-blue-300 hover:text-blue-200">
                      <Download className="h-3.5 w-3.5" /> Inspect receipt
                    </button>
                  )}
                  {payment.status === "pending" && (
                    <>
                      <input
                        value={reasons[payment.id] ?? ""}
                        onChange={(event) => setReasons((current) => ({ ...current, [payment.id]: event.target.value }))}
                        className="min-w-48 flex-1 rounded-lg border border-slate-700 bg-slate-950/70 px-3 py-2 text-xs text-slate-100 placeholder:text-slate-500"
                        placeholder="Required reason if rejecting"
                        aria-label={`Rejection reason for payment ${payment.id}`}
                      />
                      <button type="button" disabled={busy || !password} onClick={() => void decide(payment.id, "approve")} className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-700 px-3 py-2 text-xs font-medium text-white hover:bg-emerald-600 disabled:opacity-50">
                        <CheckCircle2 className="h-3.5 w-3.5" /> Approve
                      </button>
                      <button type="button" disabled={busy || !password} onClick={() => void decide(payment.id, "reject")} className="inline-flex items-center gap-1.5 rounded-lg border border-rose-500/30 px-3 py-2 text-xs text-rose-200 hover:bg-rose-500/10 disabled:opacity-50">
                        <XCircle className="h-3.5 w-3.5" /> Reject
                      </button>
                    </>
                  )}
                  {payment.status === "approved" && !payment.refunded_at && (
                    <>
                      <input
                        value={reasons[payment.id] ?? ""}
                        onChange={(event) => setReasons((current) => ({ ...current, [payment.id]: event.target.value }))}
                        className="min-w-48 flex-1 rounded-lg border border-slate-700 bg-slate-950/70 px-3 py-2 text-xs text-slate-100 placeholder:text-slate-500"
                        placeholder="Required reason to record refund"
                        aria-label={`Refund reason for payment ${payment.id}`}
                      />
                      <button type="button" disabled={busy || !password} onClick={() => void decide(payment.id, "refund")} className="rounded-lg border border-amber-500/30 px-3 py-2 text-xs text-amber-200 hover:bg-amber-500/10 disabled:opacity-50">
                        Record refund
                      </button>
                    </>
                  )}
                </div>
                {payment.rejection_reason && <p className="mt-3 text-xs text-rose-300">Rejection reason: {payment.rejection_reason}</p>}
                {payment.refund_reason && <p className="mt-3 text-xs text-amber-200">Refund reason: {payment.refund_reason}</p>}
              </article>
            ))}
          </div>
        )}
      </Section>

      <Section title="Verified payment methods" description="Only enable a method after confirming that the account or wallet details belong to the institution.">
        <div className="grid gap-4 xl:grid-cols-2">
          {methods.map((method) => (
            <form
              key={method.id}
              className="space-y-3 rounded-xl border border-slate-800 bg-slate-950/35 p-4"
              onSubmit={(event) => {
                event.preventDefault();
                void updateMethod(method, event.currentTarget);
              }}
            >
              <div className="flex items-center justify-between gap-3">
                <p className="font-medium text-white">{method.name}</p>
                <StatusBadge status={method.is_enabled ? "active" : "disabled"} />
              </div>
              <input name="name" defaultValue={method.name} maxLength={120} required className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white" aria-label={`${method.name} display name`} />
              <input name="account_holder_name" defaultValue={method.account_holder_name ?? ""} maxLength={255} className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white" placeholder="Account / wallet holder" aria-label={`${method.name} holder name`} />
              <input name="account_number" defaultValue={method.account_number ?? ""} maxLength={100} className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white" placeholder="Account / wallet number" aria-label={`${method.name} account number`} />
              <textarea name="instructions" defaultValue={method.instructions ?? ""} maxLength={4000} rows={3} className="w-full resize-y rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white" placeholder="Student payment instructions" aria-label={`${method.name} instructions`} />
              <label className="flex items-center gap-2 text-xs text-slate-300">
                <input name="is_enabled" type="checkbox" defaultChecked={method.is_enabled} className="accent-blue-500" />
                Enable after verifying real details
              </label>
              <label className="flex items-start gap-2 text-xs text-amber-200">
                <input name="confirm_details_verified" type="checkbox" className="mt-0.5 accent-amber-500" />
                I independently verified these account details
              </label>
              <button type="submit" disabled={busy || !password} className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-200 hover:border-slate-500 disabled:opacity-50">
                <Save className="h-3.5 w-3.5" /> Save method
              </button>
            </form>
          ))}
        </div>
      </Section>

      <div className="grid gap-5 xl:grid-cols-2">
        <Section title="Grandfathering policy" description="Existing accounts receive the configured read/write access period from the official launch time. Policy changes lock at launch.">
          {policy && (
            <form className="space-y-3" onSubmit={(event) => void updatePolicy(event)}>
              <label className="block space-y-1.5 text-sm">
                <span className="text-slate-300">Official launch date and time (your local timezone)</span>
                <input
                  name="launch_at"
                  type="datetime-local"
                  defaultValue={localDateTime(policy.launch_at)}
                  disabled={policy.locked}
                  required
                  className="w-full rounded-xl border border-slate-700 bg-slate-950/70 px-3 py-2.5 text-slate-100 disabled:opacity-60"
                />
              </label>
              <label className="block space-y-1.5 text-sm">
                <span className="text-slate-300">Grandfather period (days)</span>
                <input
                  name="grandfathering_days"
                  type="number"
                  min={1}
                  max={365}
                  defaultValue={policy.grandfathering_days}
                  disabled={policy.locked}
                  required
                  className="w-full rounded-xl border border-slate-700 bg-slate-950/70 px-3 py-2.5 text-slate-100 disabled:opacity-60"
                />
              </label>
              <p className="text-xs text-slate-500">Default: 30 days. Set this before the system launch; after launch, the policy is immutable through this API.</p>
              <button type="submit" disabled={busy || policy.locked || !password} className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-200 hover:border-slate-500 disabled:opacity-50">
                <Save className="h-3.5 w-3.5" /> Save policy
              </button>
            </form>
          )}
        </Section>

        <Section title="License ledger" description="Paid current licenses; grandfather eligibility is evaluated from the immutable launch policy.">
          <div className="max-h-80 space-y-2 overflow-auto">
            {licenses.length === 0 ? (
              <p className="text-sm text-slate-500">No paid licenses have been activated.</p>
            ) : licenses.map((item) => (
              <div key={item.user_id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-800 bg-slate-950/40 p-3 text-sm">
                <div>
                  <p className="text-slate-200">{item.student_name}</p>
                  <p className="text-xs text-slate-500">{item.student_email}</p>
                </div>
                <div className="text-right">
                  <StatusBadge status={item.status} />
                  <p className="mt-1 text-xs text-slate-500">Until {formatDate(item.expires_at)}</p>
                </div>
              </div>
            ))}
          </div>
        </Section>
      </div>

      <Section title="Administrative audit history" description="Payment and licensing actions are retained separately from receipt images.">
        <div className="max-h-72 space-y-2 overflow-auto">
          {auditLogs.slice(0, 100).map((entry) => (
            <div key={entry.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800/70 py-2 text-xs last:border-0">
              <div className="flex items-center gap-2 text-slate-300">
                <ShieldCheck className="h-3.5 w-3.5 text-cyan-300" />
                <span>{entry.action.replaceAll("_", " ")}</span>
                {entry.payment_id && <span className="text-slate-500">Payment #{entry.payment_id}</span>}
              </div>
              <span className="text-slate-500">{entry.actor ?? "System"} · {formatDate(entry.created_at)}</span>
            </div>
          ))}
          {auditLogs.length === 0 && <p className="text-sm text-slate-500">No audit entries.</p>}
        </div>
      </Section>
    </div>
  );
}
