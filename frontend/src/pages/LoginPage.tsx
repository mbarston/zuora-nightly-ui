import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api, ApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export function LoginPage() {
  const nav = useNavigate();
  const qc = useQueryClient();

  const devLogin = useMutation({
    mutationFn: api.devLogin,
    onSuccess: (user) => {
      qc.setQueryData(["currentUser"], user);
      nav("/", { replace: true });
    },
  });

  const err = devLogin.error as ApiError | null;

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Zuora SE Demo Data Agent</CardTitle>
          <CardDescription>
            Generate realistic demo data in your Zuora sandbox. Sign in to continue.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <Button
            className="w-full"
            disabled={devLogin.isPending}
            onClick={() => devLogin.mutate()}
          >
            {devLogin.isPending ? "Signing in…" : "Dev login"}
          </Button>
          {err && (
            <p className="text-sm text-destructive">
              {err.status === 403
                ? "Dev bypass is disabled on this server."
                : err.message}
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            Google SSO goes here once DEV_AUTH_BYPASS is off.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
