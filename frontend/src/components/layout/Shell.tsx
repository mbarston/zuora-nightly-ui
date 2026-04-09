import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { LogOut } from "lucide-react";
import { api } from "@/lib/api";
import type { CurrentUser } from "@/lib/types";
import { Button } from "@/components/ui/button";

interface ShellProps {
  user: CurrentUser;
  children: React.ReactNode;
}

export function Shell({ user, children }: ShellProps) {
  const nav = useNavigate();
  const qc = useQueryClient();
  const logout = useMutation({
    mutationFn: api.logout,
    onSettled: () => {
      qc.clear();
      nav("/login", { replace: true });
    },
  });

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border">
        <div className="container flex h-14 items-center justify-between">
          <Link to="/" className="flex items-center gap-2 font-semibold">
            <span className="text-lg">zuora-nightly</span>
            <span className="text-xs font-normal text-muted-foreground">internal</span>
          </Link>
          <nav className="flex items-center gap-4 text-sm">
            <Link to="/" className="hover:text-primary">
              Dashboard
            </Link>
            <Link to="/runs" className="hover:text-primary">
              History
            </Link>
            <span className="text-muted-foreground">{user.email}</span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => logout.mutate()}
              disabled={logout.isPending}
            >
              <LogOut className="mr-1 h-3.5 w-3.5" />
              Logout
            </Button>
          </nav>
        </div>
      </header>
      <main className="container py-6">{children}</main>
    </div>
  );
}
