import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  CreditCard,
  DollarSign,
  FileText,
  Loader2,
  Play,
  RefreshCw,
  CheckCircle2,
  XCircle,
  AlertTriangle,
} from "lucide-react";
import { api } from "@/lib/api";
import type { OpenInvoice, PaymentItem } from "@/lib/types";
import { formatCurrency } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";

export function BillingPage() {
  const { tenantId } = useParams<{ tenantId: string }>();
  const tid = Number(tenantId);

  // --- Tenant info ---
  const { data: tenant } = useQuery({
    queryKey: ["tenant", tid],
    queryFn: () => api.getTenant(tid),
  });

  // --- Bill run state ---
  const [billRunDate, setBillRunDate] = useState(
    () => new Date().toISOString().split("T")[0]
  );
  const [billRunId, setBillRunId] = useState<string | null>(null);
  const [billRunStatus, setBillRunStatus] = useState<string | null>(null);

  const triggerBillRun = useMutation({
    mutationFn: () => api.triggerBillRun(tid, billRunDate),
    onSuccess: (data) => {
      setBillRunId(data.id);
      setBillRunStatus(data.status);
    },
  });

  // Poll bill run status
  useEffect(() => {
    if (!billRunId || billRunStatus === "Completed" || billRunStatus === "Error") return;
    const interval = setInterval(async () => {
      try {
        const status = await api.getBillRunStatus(tid, billRunId);
        setBillRunStatus(status.status);
        if (status.status === "Completed" || status.status === "Error") {
          clearInterval(interval);
        }
      } catch {
        // ignore polling errors
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [billRunId, billRunStatus, tid]);

  // --- Open invoices ---
  const {
    data: invoices,
    isLoading: loadingInvoices,
    refetch: refetchInvoices,
    isFetching: fetchingInvoices,
    error: invoiceError,
  } = useQuery({
    queryKey: ["openInvoices", tid],
    queryFn: () => api.getOpenInvoices(tid),
    enabled: false, // manual trigger only
    retry: false,
  });

  // --- Selection & payment amounts ---
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const [paymentDate, setPaymentDate] = useState(
    () => new Date().toISOString().split("T")[0]
  );

  const toggleSelect = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleAll = useCallback(() => {
    if (!invoices) return;
    setSelected((prev) => {
      if (prev.size === invoices.length) return new Set();
      return new Set(invoices.map((inv) => inv.id));
    });
  }, [invoices]);

  // Initialize amounts when invoices load
  useEffect(() => {
    if (invoices) {
      const newAmounts: Record<string, string> = {};
      for (const inv of invoices) {
        newAmounts[inv.id] = inv.balance.toFixed(2);
      }
      setAmounts(newAmounts);
    }
  }, [invoices]);

  const selectedInvoices = useMemo(
    () => (invoices ?? []).filter((inv) => selected.has(inv.id)),
    [invoices, selected]
  );

  const totalPayment = useMemo(
    () =>
      selectedInvoices.reduce(
        (sum, inv) => sum + (parseFloat(amounts[inv.id] || "0") || 0),
        0
      ),
    [selectedInvoices, amounts]
  );

  // --- Apply payments ---
  const [paymentResults, setPaymentResults] = useState<{
    results: Array<{ payment_number: string; amount: number }>;
    errors: Array<{ invoice_id: string; error: string }>;
  } | null>(null);

  const applyPayments = useMutation({
    mutationFn: () => {
      const items: PaymentItem[] = selectedInvoices.map((inv) => ({
        invoice_id: inv.id,
        account_id: inv.account_id,
        amount: parseFloat(amounts[inv.id] || "0"),
        effective_date: paymentDate,
        currency: inv.currency || "USD",
      }));
      return api.applyPayments(tid, items);
    },
    onSuccess: (data) => {
      setPaymentResults(data);
      setSelected(new Set());
      // Refresh invoices to show updated balances
      refetchInvoices();
    },
  });

  // --- Write-off ---
  const [writeOffInvoice, setWriteOffInvoice] = useState<OpenInvoice | null>(null);
  const [writeOffResult, setWriteOffResult] = useState<{
    success: boolean;
    message: string;
  } | null>(null);

  const doWriteOff = useMutation({
    mutationFn: (inv: OpenInvoice) =>
      api.writeOffInvoice(tid, inv.id, inv.balance),
    onSuccess: (data, inv) => {
      setWriteOffInvoice(null);
      setWriteOffResult({
        success: true,
        message: `Successfully wrote off ${inv.invoice_number} (${inv.account_name}) — Credit memo ${data.credit_memo_number || "created"} for ${formatCurrency(inv.balance)}`,
      });
      refetchInvoices();
      // Auto-dismiss after 8 seconds
      setTimeout(() => setWriteOffResult(null), 8000);
    },
    onError: (err, inv) => {
      setWriteOffInvoice(null);
      setWriteOffResult({
        success: false,
        message: `Failed to write off ${inv.invoice_number}: ${(err as Error).message}`,
      });
    },
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold flex items-center gap-2">
          <CreditCard className="h-6 w-6" />
          Billing & Payments
        </h1>
        <p className="text-sm text-muted-foreground">
          {tenant
            ? `${tenant.name} — ${tenant.environment}`
            : "Loading..."}
        </p>
      </div>

      {/* Step 1: Bill Run */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Play className="h-4 w-4" />
            Step 1: Run Billing
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Trigger an ad-hoc bill run against this tenant. This creates
            invoices for all charges due through the target date.
          </p>
          <div className="flex items-end gap-3">
            <div className="space-y-1">
              <label className="text-xs font-medium">Target date</label>
              <Input
                type="date"
                value={billRunDate}
                onChange={(e) => setBillRunDate(e.target.value)}
                className="w-44"
              />
            </div>
            <Button
              onClick={() => triggerBillRun.mutate()}
              disabled={triggerBillRun.isPending || (!!billRunStatus && billRunStatus !== "Completed" && billRunStatus !== "Error")}
            >
              {triggerBillRun.isPending ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : (
                <Play className="mr-1 h-4 w-4" />
              )}
              Run billing
            </Button>
          </div>

          {triggerBillRun.isError && (
            <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-400">
              <XCircle className="mr-1 inline h-4 w-4" />
              {(triggerBillRun.error as Error).message}
            </div>
          )}

          {billRunId && (
            <div
              className={`rounded-md border px-3 py-2 text-sm flex items-center gap-2 ${
                billRunStatus === "Completed"
                  ? "border-green-500/40 bg-green-500/10 text-green-400"
                  : billRunStatus === "Error"
                  ? "border-red-500/40 bg-red-500/10 text-red-400"
                  : "border-yellow-500/40 bg-yellow-500/10 text-yellow-400"
              }`}
            >
              {billRunStatus === "Completed" ? (
                <CheckCircle2 className="h-4 w-4" />
              ) : billRunStatus === "Error" ? (
                <XCircle className="h-4 w-4" />
              ) : (
                <Loader2 className="h-4 w-4 animate-spin" />
              )}
              Bill run {billRunId.substring(0, 8)}... — {billRunStatus}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Step 2: Open Invoices */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <FileText className="h-4 w-4" />
            Step 2: Open Invoices
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              onClick={() => refetchInvoices()}
              disabled={fetchingInvoices}
            >
              {fetchingInvoices ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="mr-1 h-4 w-4" />
              )}
              {invoices ? "Refresh invoices" : "Import open invoices"}
            </Button>
            {invoices && (
              <span className="text-sm text-muted-foreground">
                {invoices.length} invoice{invoices.length !== 1 ? "s" : ""} with open balance
              </span>
            )}
          </div>

          {writeOffResult && (
            <div
              className={`rounded-md border px-3 py-2 text-sm flex items-center gap-2 ${
                writeOffResult.success
                  ? "border-green-500/40 bg-green-500/10 text-green-400"
                  : "border-red-500/40 bg-red-500/10 text-red-400"
              }`}
            >
              {writeOffResult.success ? (
                <CheckCircle2 className="h-4 w-4 shrink-0" />
              ) : (
                <XCircle className="h-4 w-4 shrink-0" />
              )}
              {writeOffResult.message}
              <button
                className="ml-auto text-xs opacity-60 hover:opacity-100"
                onClick={() => setWriteOffResult(null)}
              >
                ✕
              </button>
            </div>
          )}

          {invoiceError && (
            <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-400">
              <XCircle className="mr-1 inline h-4 w-4" />
              {(invoiceError as Error).message}
            </div>
          )}

          {loadingInvoices && !invoices && (
            <p className="text-sm text-muted-foreground">Loading invoices...</p>
          )}

          {invoices && invoices.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No open invoices found. All balances are zero.
            </p>
          )}

          {invoices && invoices.length > 0 && (
            <div className="rounded-md border overflow-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b bg-muted/50">
                    <th className="px-3 py-2 text-left w-8">
                      <Checkbox
                        checked={selected.size === invoices.length && invoices.length > 0}
                        onCheckedChange={toggleAll}
                      />
                    </th>
                    <th className="px-3 py-2 text-left">Invoice #</th>
                    <th className="px-3 py-2 text-left">Account</th>
                    <th className="px-3 py-2 text-left">Date</th>
                    <th className="px-3 py-2 text-left">Due</th>
                    <th className="px-3 py-2 text-center">Ccy</th>
                    <th className="px-3 py-2 text-right">Amount</th>
                    <th className="px-3 py-2 text-right">Balance</th>
                    <th className="px-3 py-2 text-right">Age</th>
                    <th className="px-3 py-2 text-right">Pay amount</th>
                    <th className="px-3 py-2 text-center">Write-off</th>
                  </tr>
                </thead>
                <tbody>
                  {invoices.map((inv) => (
                    <tr
                      key={inv.id}
                      className={`border-b transition-colors ${
                        selected.has(inv.id) ? "bg-primary/5" : "hover:bg-muted/30"
                      }`}
                    >
                      <td className="px-3 py-2">
                        <Checkbox
                          checked={selected.has(inv.id)}
                          onCheckedChange={() => toggleSelect(inv.id)}
                        />
                      </td>
                      <td className="px-3 py-2 font-mono text-xs">
                        {inv.invoice_number}
                      </td>
                      <td className="px-3 py-2">{inv.account_name}</td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {inv.invoice_date}
                      </td>
                      <td className="px-3 py-2 text-muted-foreground">
                        {inv.due_date ? inv.due_date.split("T")[0] : "—"}
                      </td>
                      <td className="px-3 py-2 text-center font-mono text-xs text-muted-foreground">
                        {inv.currency || "USD"}
                      </td>
                      <td className="px-3 py-2 text-right font-mono">
                        {formatCurrency(inv.amount)}
                      </td>
                      <td className="px-3 py-2 text-right font-mono font-semibold">
                        {formatCurrency(inv.balance)}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <Badge
                          variant={
                            inv.age_days > 60
                              ? "error"
                              : inv.age_days > 30
                              ? "warn"
                              : "ok"
                          }
                        >
                          {inv.age_days}d
                        </Badge>
                      </td>
                      <td className="px-3 py-2 text-right">
                        {selected.has(inv.id) ? (
                          <Input
                            type="number"
                            step="0.01"
                            min="0.01"
                            max={inv.balance}
                            value={amounts[inv.id] ?? inv.balance.toFixed(2)}
                            onChange={(e) =>
                              setAmounts((prev) => ({
                                ...prev,
                                [inv.id]: e.target.value,
                              }))
                            }
                            className="w-28 text-right font-mono text-xs h-8"
                          />
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-center">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 text-xs text-orange-400 hover:text-orange-300"
                          onClick={() => setWriteOffInvoice(inv)}
                          disabled={doWriteOff.isPending}
                        >
                          Write-off
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Step 3: Apply Payments */}
      {invoices && invoices.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <DollarSign className="h-4 w-4" />
              Step 3: Apply Payments
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex items-end gap-3">
              <div className="space-y-1">
                <label className="text-xs font-medium">Payment date</label>
                <Input
                  type="date"
                  value={paymentDate}
                  onChange={(e) => setPaymentDate(e.target.value)}
                  className="w-44"
                />
              </div>
              <Button
                onClick={() => applyPayments.mutate()}
                disabled={selected.size === 0 || applyPayments.isPending}
              >
                {applyPayments.isPending ? (
                  <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                ) : (
                  <DollarSign className="mr-1 h-4 w-4" />
                )}
                Apply {selected.size} payment{selected.size !== 1 ? "s" : ""}{" "}
                ({formatCurrency(totalPayment)})
              </Button>
            </div>

            {applyPayments.isError && (
              <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-400">
                <XCircle className="mr-1 inline h-4 w-4" />
                {(applyPayments.error as Error).message}
              </div>
            )}

            {paymentResults && (
              <div className="space-y-2">
                {paymentResults.results.length > 0 && (
                  <div className="rounded-md border border-green-500/40 bg-green-500/10 px-3 py-2 text-sm text-green-400">
                    <CheckCircle2 className="mr-1 inline h-4 w-4" />
                    {paymentResults.results.length} payment{paymentResults.results.length !== 1 ? "s" : ""} applied successfully
                    {paymentResults.results.map((r) => (
                      <span key={r.payment_number} className="ml-2 font-mono text-xs">
                        ({r.payment_number}: {formatCurrency(r.amount)})
                      </span>
                    ))}
                  </div>
                )}
                {paymentResults.errors.length > 0 && (
                  <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-400">
                    <XCircle className="mr-1 inline h-4 w-4" />
                    {paymentResults.errors.length} payment{paymentResults.errors.length !== 1 ? "s" : ""} failed:
                    {paymentResults.errors.map((e, i) => (
                      <div key={i} className="ml-4 text-xs">{e.error}</div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Write-off confirmation modal (inline) */}
      {writeOffInvoice && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <Card className="w-96">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <AlertTriangle className="h-4 w-4 text-orange-400" />
                Write-off invoice?
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="text-sm space-y-1">
                <p>
                  <span className="text-muted-foreground">Invoice:</span>{" "}
                  <span className="font-mono">{writeOffInvoice.invoice_number}</span>
                </p>
                <p>
                  <span className="text-muted-foreground">Account:</span>{" "}
                  {writeOffInvoice.account_name}
                </p>
                <p>
                  <span className="text-muted-foreground">Balance:</span>{" "}
                  <span className="font-semibold">{formatCurrency(writeOffInvoice.balance)}</span>
                </p>
              </div>
              <p className="text-xs text-muted-foreground">
                This will create a credit memo for the full balance and apply it
                to zero out the invoice.
              </p>

              {doWriteOff.isError && (
                <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-400">
                  {(doWriteOff.error as Error).message}
                </div>
              )}

              <div className="flex justify-end gap-2">
                <Button
                  variant="outline"
                  onClick={() => setWriteOffInvoice(null)}
                >
                  Cancel
                </Button>
                <Button
                  variant="destructive"
                  onClick={() => doWriteOff.mutate(writeOffInvoice)}
                  disabled={doWriteOff.isPending}
                >
                  {doWriteOff.isPending ? (
                    <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                  ) : null}
                  Write off {formatCurrency(writeOffInvoice.balance)}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
