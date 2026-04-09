import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Download, Plus, Trash2 } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type {
  Addon,
  MandatorySub,
  Product,
  RatePlan,
  TenantConfig,
} from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { CatalogImportModal } from "@/components/tenants/CatalogImportModal";
import { SchedulesSection } from "@/components/schedules/SchedulesSection";

export function TenantConfigPage() {
  const { tenantId: tenantIdParam } = useParams();
  const tenantId = Number(tenantIdParam);
  const qc = useQueryClient();

  const tenantQ = useQuery({
    queryKey: ["tenant", tenantId],
    queryFn: () => api.getTenant(tenantId),
  });
  const envQ = useQuery({
    queryKey: ["config", tenantId],
    queryFn: () => api.getConfig(tenantId),
  });

  const [cfg, setCfg] = useState<TenantConfig | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [saveOk, setSaveOk] = useState(false);

  useEffect(() => {
    if (envQ.data && !cfg) {
      setCfg(envQ.data.config);
    }
  }, [envQ.data, cfg]);

  const save = useMutation({
    mutationFn: () => api.saveConfig(tenantId, cfg!),
    onSuccess: (env) => {
      setCfg(env.config);
      setSaveOk(true);
      setTimeout(() => setSaveOk(false), 2000);
      qc.invalidateQueries({ queryKey: ["config", tenantId] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });

  if (envQ.isLoading || !cfg || !tenantQ.data) {
    return <p className="text-muted-foreground">Loading configuration…</p>;
  }

  const issues = envQ.data?.issues ?? [];
  const errors = issues.filter((i) => i.severity === "error");
  const warnings = issues.filter((i) => i.severity === "warning");

  // Local state mutators
  const upd = (partial: Partial<TenantConfig>) => setCfg({ ...cfg, ...partial });

  const updateProduct = (idx: number, patch: Partial<Product>) =>
    upd({
      products: cfg.products.map((p, i) => (i === idx ? { ...p, ...patch } : p)),
    });

  const updateRatePlan = (pi: number, rpi: number, patch: Partial<RatePlan>) =>
    upd({
      products: cfg.products.map((p, i) =>
        i !== pi
          ? p
          : {
              ...p,
              rate_plans: p.rate_plans.map((rp, j) =>
                j === rpi ? { ...rp, ...patch } : rp
              ),
            }
      ),
    });

  const addProduct = () => {
    const tier = Math.max(0, ...cfg.products.map((p) => p.tier)) + 1;
    upd({
      products: [
        ...cfg.products,
        {
          label: "",
          tier,
          rate_plans: [{ name: "", period: "Annual", product_rate_plan_id: "" }],
        },
      ],
    });
  };

  const removeProduct = (idx: number) =>
    upd({ products: cfg.products.filter((_, i) => i !== idx) });

  const addRatePlan = (idx: number) =>
    upd({
      products: cfg.products.map((p, i) =>
        i !== idx
          ? p
          : {
              ...p,
              rate_plans: [
                ...p.rate_plans,
                { name: "", period: "Annual", product_rate_plan_id: "" },
              ],
            }
      ),
    });

  const removeRatePlan = (pi: number, rpi: number) =>
    upd({
      products: cfg.products.map((p, i) =>
        i !== pi ? p : { ...p, rate_plans: p.rate_plans.filter((_, j) => j !== rpi) }
      ),
    });

  const addAddon = () => upd({ addons: [...cfg.addons, { name: "", product_rate_plan_id: "" }] });
  const updateAddon = (idx: number, patch: Partial<Addon>) =>
    upd({ addons: cfg.addons.map((a, i) => (i === idx ? { ...a, ...patch } : a)) });
  const removeAddon = (idx: number) => upd({ addons: cfg.addons.filter((_, i) => i !== idx) });

  const addMandSub = () =>
    upd({
      mandatory_subs: [
        ...cfg.mandatory_subs,
        { subscription_number: "", use_case: "", notes: "" },
      ],
    });
  const updateMandSub = (idx: number, patch: Partial<MandatorySub>) =>
    upd({
      mandatory_subs: cfg.mandatory_subs.map((s, i) => (i === idx ? { ...s, ...patch } : s)),
    });
  const removeMandSub = (idx: number) =>
    upd({ mandatory_subs: cfg.mandatory_subs.filter((_, i) => i !== idx) });

  const saveError = save.error as ApiError | null;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <Button variant="ghost" size="sm" asChild>
            <Link to="/">
              <ArrowLeft className="mr-1 h-4 w-4" />
              Back to dashboard
            </Link>
          </Button>
          <h1 className="mt-2 text-2xl font-semibold">Configure {tenantQ.data.name}</h1>
          <p className="text-xs text-muted-foreground">
            <span className="mr-2 rounded bg-muted px-1.5 py-0.5 font-mono text-[0.65rem]">
              {tenantQ.data.environment}
            </span>
            {tenantQ.data.base_url}
          </p>
        </div>
        <Button variant="outline" onClick={() => setImportOpen(true)}>
          <Download className="mr-1 h-4 w-4" />
          Import from Zuora
        </Button>
      </div>

      {/* Health banner */}
      {errors.length > 0 && (
        <Card className="border-destructive">
          <CardContent className="py-4">
            <p className="mb-2 font-semibold text-destructive">
              ⛔ {errors.length} error{errors.length !== 1 ? "s" : ""} — runs are blocked until these are fixed:
            </p>
            <ul className="ml-5 list-disc space-y-0.5 text-sm text-destructive">
              {errors.map((e, i) => (
                <li key={i}>
                  <code className="text-xs">{e.field}</code>: {e.message}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
      {errors.length === 0 && warnings.length > 0 && (
        <Card className="border-amber-500/50">
          <CardContent className="py-4">
            <p className="mb-2 font-semibold text-amber-400">
              ⚠️ {warnings.length} warning{warnings.length !== 1 ? "s" : ""}:
            </p>
            <ul className="ml-5 list-disc space-y-0.5 text-sm text-amber-400">
              {warnings.map((w, i) => (
                <li key={i}>
                  <code className="text-xs">{w.field}</code>: {w.message}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
      {errors.length === 0 && warnings.length === 0 && (
        <Card className="border-emerald-500/50">
          <CardContent className="py-3">
            <p className="text-sm font-semibold text-emerald-400">
              ✓ This configuration is valid and ready to run.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Products */}
      <Card>
        <CardHeader>
          <CardTitle>Products</CardTitle>
          <p className="text-xs text-muted-foreground">
            Tier-based SaaS plans used for new subscriptions and upgrades/downgrades.
          </p>
        </CardHeader>
        <CardContent className="space-y-4">
          {cfg.products.length === 0 && (
            <p className="text-sm text-muted-foreground">
              No products yet. Click <em>Import from Zuora</em> above to auto-populate, or add rows manually.
            </p>
          )}
          {cfg.products.map((p, pi) => (
            <div key={pi} className="rounded-md border p-3">
              <div className="grid grid-cols-[1fr_6rem_auto] items-end gap-2">
                <div>
                  <Label className="text-xs">Label</Label>
                  <Input
                    value={p.label}
                    onChange={(e) => updateProduct(pi, { label: e.target.value })}
                    placeholder="CloudStream SaaS Basic"
                  />
                </div>
                <div>
                  <Label className="text-xs">Tier</Label>
                  <Input
                    type="number"
                    min={1}
                    max={10}
                    value={p.tier}
                    onChange={(e) => updateProduct(pi, { tier: Number(e.target.value) })}
                  />
                </div>
                <Button
                  variant="outline"
                  size="icon"
                  onClick={() => {
                    if (confirm("Delete this product and all its rate plans?")) removeProduct(pi);
                  }}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
              <div className="mt-3 pl-4">
                <p className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">Rate plans</p>
                {p.rate_plans.map((rp, rpi) => (
                  <div key={rpi} className="mb-1 grid grid-cols-[1fr_7rem_2fr_auto] items-end gap-2">
                    <Input
                      value={rp.name}
                      onChange={(e) => updateRatePlan(pi, rpi, { name: e.target.value })}
                      placeholder="Annual Plan"
                    />
                    <Select
                      value={rp.period}
                      onValueChange={(v) => updateRatePlan(pi, rpi, { period: v })}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="MTM">MTM</SelectItem>
                        <SelectItem value="Annual">Annual</SelectItem>
                        <SelectItem value="Other">Other</SelectItem>
                      </SelectContent>
                    </Select>
                    <Input
                      value={rp.product_rate_plan_id}
                      onChange={(e) =>
                        updateRatePlan(pi, rpi, { product_rate_plan_id: e.target.value })
                      }
                      placeholder="8a8aa…"
                      className="font-mono text-xs"
                    />
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => removeRatePlan(pi, rpi)}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
                <Button variant="outline" size="sm" onClick={() => addRatePlan(pi)}>
                  <Plus className="mr-1 h-3 w-3" />
                  Rate plan
                </Button>
              </div>
            </div>
          ))}
          <Button variant="outline" onClick={addProduct}>
            <Plus className="mr-1 h-4 w-4" />
            Add product
          </Button>
        </CardContent>
      </Card>

      {/* Add-ons */}
      <Card>
        <CardHeader>
          <CardTitle>Add-ons</CardTitle>
          <p className="text-xs text-muted-foreground">
            Rate plans the skill attaches via add-product amendments.
          </p>
        </CardHeader>
        <CardContent className="space-y-2">
          {cfg.addons.length === 0 && (
            <p className="text-sm text-muted-foreground">No add-ons yet.</p>
          )}
          {cfg.addons.map((a, i) => (
            <div key={i} className="grid grid-cols-[1fr_2fr_auto] items-end gap-2">
              <Input
                value={a.name}
                onChange={(e) => updateAddon(i, { name: e.target.value })}
                placeholder="CloudStream Analytics Annual"
              />
              <Input
                value={a.product_rate_plan_id}
                onChange={(e) => updateAddon(i, { product_rate_plan_id: e.target.value })}
                placeholder="8a8aa…"
                className="font-mono text-xs"
              />
              <Button variant="ghost" size="icon" onClick={() => removeAddon(i)}>
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={addAddon}>
            <Plus className="mr-1 h-3 w-3" />
            Add-on
          </Button>
        </CardContent>
      </Card>

      {/* Mandatory subs */}
      <Card>
        <CardHeader>
          <CardTitle>Mandatory usage subscriptions</CardTitle>
          <p className="text-xs text-muted-foreground">
            PPDD / minimum-commit subs that MUST receive usage every run.
          </p>
        </CardHeader>
        <CardContent className="space-y-2">
          {cfg.mandatory_subs.length === 0 && (
            <p className="text-sm text-muted-foreground">No mandatory subs.</p>
          )}
          {cfg.mandatory_subs.map((s, i) => (
            <div key={i} className="space-y-1 rounded-md border p-2">
              <div className="grid grid-cols-[1fr_1fr_auto] items-end gap-2">
                <div>
                  <Label className="text-xs">Subscription number</Label>
                  <Input
                    value={s.subscription_number}
                    onChange={(e) => updateMandSub(i, { subscription_number: e.target.value })}
                    placeholder="A-S00000354"
                    className="font-mono"
                  />
                </div>
                <div>
                  <Label className="text-xs">Use case</Label>
                  <Input
                    value={s.use_case}
                    onChange={(e) => updateMandSub(i, { use_case: e.target.value })}
                    placeholder="Minimum Commit"
                  />
                </div>
                <Button variant="ghost" size="icon" onClick={() => removeMandSub(i)}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
              <div>
                <Label className="text-xs">Notes (optional)</Label>
                <Input
                  value={s.notes}
                  onChange={(e) => updateMandSub(i, { notes: e.target.value })}
                  placeholder="Post usage to draw down the committed amount."
                />
              </div>
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={addMandSub}>
            <Plus className="mr-1 h-3 w-3" />
            Mandatory sub
          </Button>
        </CardContent>
      </Card>

      {/* Volumes */}
      <Card>
        <CardHeader>
          <CardTitle>Volume ranges</CardTitle>
          <p className="text-xs text-muted-foreground">
            Randomly picked within each range on every run.
          </p>
        </CardHeader>
        <CardContent className="grid grid-cols-2 gap-3">
          <VolumeRow
            label="New subs"
            min={cfg.new_subs_min}
            max={cfg.new_subs_max}
            onMinChange={(v) => upd({ new_subs_min: v })}
            onMaxChange={(v) => upd({ new_subs_max: v })}
          />
          <VolumeRow
            label="Amendments"
            min={cfg.amendments_min}
            max={cfg.amendments_max}
            onMinChange={(v) => upd({ amendments_min: v })}
            onMaxChange={(v) => upd({ amendments_max: v })}
          />
          <VolumeRow
            label="Cancellations"
            min={cfg.cancellations_min}
            max={cfg.cancellations_max}
            onMinChange={(v) => upd({ cancellations_min: v })}
            onMaxChange={(v) => upd({ cancellations_max: v })}
          />
          <VolumeRow
            label="Usage posts"
            min={cfg.usage_posts_min}
            max={cfg.usage_posts_max}
            onMinChange={(v) => upd({ usage_posts_min: v })}
            onMaxChange={(v) => upd({ usage_posts_max: v })}
          />
        </CardContent>
      </Card>

      {/* Mix */}
      <Card>
        <CardHeader>
          <CardTitle>Mix percentages</CardTitle>
          <p className="text-xs text-muted-foreground">Each group must sum to 100.</p>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <p className="mb-2 text-sm font-semibold">Tier mix (for new subs)</p>
            {cfg.products.length === 0 && (
              <p className="text-xs text-muted-foreground">
                Add a product first and the tier inputs will appear.
              </p>
            )}
            <div className="grid grid-cols-3 gap-2">
              {[...cfg.products]
                .sort((a, b) => a.tier - b.tier)
                .map((p) => {
                  const key = String(p.tier);
                  return (
                    <div key={key}>
                      <Label className="text-xs">
                        Tier {p.tier} — {p.label || "(unnamed)"}
                      </Label>
                      <Input
                        type="number"
                        min={0}
                        max={100}
                        value={cfg.tier_mix[key] ?? 0}
                        onChange={(e) =>
                          upd({
                            tier_mix: {
                              ...cfg.tier_mix,
                              [key]: Number(e.target.value),
                            },
                          })
                        }
                      />
                    </div>
                  );
                })}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              Sum: {Object.values(cfg.tier_mix).reduce((a, b) => a + b, 0)}
            </p>
          </div>
          <Separator />
          <div>
            <p className="mb-2 text-sm font-semibold">Amendment mix</p>
            <div className="grid grid-cols-4 gap-2">
              {(["upgrade", "add_product", "downgrade", "remove_product"] as const).map((k) => (
                <div key={k}>
                  <Label className="text-xs">{k.replace("_", " ")}</Label>
                  <Input
                    type="number"
                    min={0}
                    max={100}
                    value={cfg.amendment_mix[k] ?? 0}
                    onChange={(e) =>
                      upd({
                        amendment_mix: {
                          ...cfg.amendment_mix,
                          [k]: Number(e.target.value),
                        },
                      })
                    }
                  />
                </div>
              ))}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              Sum: {Object.values(cfg.amendment_mix).reduce((a, b) => a + b, 0)}
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Growth bias */}
      <Card>
        <CardHeader>
          <CardTitle>Growth bias</CardTitle>
          <p className="text-xs text-muted-foreground">
            100 = neutral, 150 = 1.5× growth, 50 = half growth.
          </p>
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-3">
            <Input
              type="number"
              min={10}
              max={500}
              step={5}
              value={cfg.growth_bias_bp}
              onChange={(e) => upd({ growth_bias_bp: Number(e.target.value) })}
              className="max-w-[8rem]"
            />
            <Badge variant="default">{(cfg.growth_bias_bp / 100).toFixed(2)}×</Badge>
          </div>
        </CardContent>
      </Card>

      {/* Name pool */}
      <Card>
        <CardHeader>
          <CardTitle>Company name pool</CardTitle>
          <p className="text-xs text-muted-foreground">
            Used to generate new account names. Each name = one prefix + one suffix.
          </p>
        </CardHeader>
        <CardContent className="space-y-3">
          <div>
            <Label className="text-xs">Prefixes (comma-separated)</Label>
            <Input
              value={(cfg.name_pool.prefixes || []).join(", ")}
              onChange={(e) =>
                upd({
                  name_pool: {
                    ...cfg.name_pool,
                    prefixes: e.target.value.split(",").map((x) => x.trim()).filter(Boolean),
                  },
                })
              }
            />
          </div>
          <div>
            <Label className="text-xs">Suffixes (comma-separated)</Label>
            <Input
              value={(cfg.name_pool.suffixes || []).join(", ")}
              onChange={(e) =>
                upd({
                  name_pool: {
                    ...cfg.name_pool,
                    suffixes: e.target.value.split(",").map((x) => x.trim()).filter(Boolean),
                  },
                })
              }
            />
          </div>
        </CardContent>
      </Card>

      {/* Save bar */}
      <div className="sticky bottom-4 flex items-center justify-between rounded-md border bg-background/95 p-3 shadow-md backdrop-blur">
        <div className="text-sm">
          {saveOk && <span className="text-emerald-400">✓ Saved</span>}
          {saveError && <span className="text-destructive">{saveError.message}</span>}
        </div>
        <Button onClick={() => save.mutate()} disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save configuration"}
        </Button>
      </div>

      {/* Schedules */}
      <SchedulesSection tenantId={tenantId} />

      {/* Catalog import modal */}
      <CatalogImportModal
        open={importOpen}
        onOpenChange={setImportOpen}
        tenantId={tenantId}
        currentConfig={cfg}
        onImport={(merged) => {
          setCfg({ ...cfg, products: merged.products, addons: merged.addons });
        }}
      />
    </div>
  );
}

function VolumeRow({
  label,
  min,
  max,
  onMinChange,
  onMaxChange,
}: {
  label: string;
  min: number;
  max: number;
  onMinChange: (v: number) => void;
  onMaxChange: (v: number) => void;
}) {
  return (
    <div>
      <Label className="text-xs">{label}</Label>
      <div className="flex items-center gap-2">
        <Input
          type="number"
          min={0}
          value={min}
          onChange={(e) => onMinChange(Number(e.target.value))}
          className="max-w-[6rem]"
        />
        <span className="text-muted-foreground">–</span>
        <Input
          type="number"
          min={0}
          value={max}
          onChange={(e) => onMaxChange(Number(e.target.value))}
          className="max-w-[6rem]"
        />
      </div>
    </div>
  );
}
