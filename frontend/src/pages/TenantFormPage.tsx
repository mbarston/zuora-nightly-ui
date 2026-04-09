import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface Props {
  mode: "create" | "edit";
}

interface FormState {
  name: string;
  environment: string;
  base_url: string;
  client_id: string;
  client_secret: string;
}

const EMPTY: FormState = {
  name: "",
  environment: "CSBX",
  base_url: "https://rest.test.zuora.com",
  client_id: "",
  client_secret: "",
};

export function TenantFormPage({ mode }: Props) {
  const params = useParams<{ tenantId: string }>();
  const tenantId = params.tenantId ? Number(params.tenantId) : null;
  const nav = useNavigate();
  const qc = useQueryClient();

  const [form, setForm] = useState<FormState>(EMPTY);

  const existing = useQuery({
    queryKey: ["tenant", tenantId],
    queryFn: () => api.getTenant(tenantId!),
    enabled: mode === "edit" && tenantId != null,
  });

  useEffect(() => {
    if (mode === "edit" && existing.data) {
      setForm({
        name: existing.data.name,
        environment: existing.data.environment,
        base_url: existing.data.base_url,
        client_id: existing.data.client_id,
        client_secret: "",
      });
    }
  }, [mode, existing.data]);

  const submit = useMutation({
    mutationFn: async () => {
      if (mode === "create") {
        return api.createTenant({
          name: form.name,
          environment: form.environment,
          base_url: form.base_url,
          client_id: form.client_id,
          client_secret: form.client_secret,
        });
      }
      return api.updateTenant(tenantId!, {
        name: form.name,
        environment: form.environment,
        base_url: form.base_url,
        client_id: form.client_id,
        client_secret: form.client_secret || undefined,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      nav("/");
    },
  });

  const err = submit.error as ApiError | null;

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <Button variant="ghost" size="sm" asChild>
        <Link to="/">
          <ArrowLeft className="mr-1 h-4 w-4" />
          Back to dashboard
        </Link>
      </Button>

      <Card>
        <CardHeader>
          <CardTitle>{mode === "create" ? "Add tenant" : "Edit tenant"}</CardTitle>
          <CardDescription>
            {mode === "create"
              ? "Register a new Zuora sandbox. Credentials are encrypted at rest."
              : "Update tenant connection details. Leave the secret blank to keep the existing encrypted value."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              submit.mutate();
            }}
          >
            <div>
              <Label>Display name</Label>
              <Input
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="CSBX – Acme demo"
                required
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Environment</Label>
                <Input
                  value={form.environment}
                  onChange={(e) => setForm({ ...form, environment: e.target.value })}
                  placeholder="CSBX"
                  required
                />
              </div>
              <div>
                <Label>Base URL</Label>
                <Input
                  value={form.base_url}
                  onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                  placeholder="https://rest.test.zuora.com"
                  required
                />
              </div>
            </div>
            <div>
              <Label>OAuth client ID</Label>
              <Input
                value={form.client_id}
                onChange={(e) => setForm({ ...form, client_id: e.target.value })}
                placeholder="a5c188d3-…"
                required
                className="font-mono text-xs"
              />
            </div>
            <div>
              <Label>
                OAuth client secret
                {mode === "edit" && (
                  <span className="ml-2 text-xs font-normal text-muted-foreground">
                    (leave blank to keep existing)
                  </span>
                )}
              </Label>
              <Input
                type="password"
                value={form.client_secret}
                onChange={(e) => setForm({ ...form, client_secret: e.target.value })}
                required={mode === "create"}
                className="font-mono text-xs"
              />
            </div>

            {err && (
              <p className="text-sm text-destructive">
                {err.message || "Something went wrong"}
              </p>
            )}

            <div className="flex gap-2">
              <Button type="submit" disabled={submit.isPending}>
                {submit.isPending ? "Saving…" : mode === "create" ? "Create tenant" : "Save"}
              </Button>
              <Button variant="outline" type="button" onClick={() => nav("/")}>
                Cancel
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
