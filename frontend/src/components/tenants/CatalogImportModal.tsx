import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Search } from "lucide-react";
import { api } from "@/lib/api";
import type {
  Addon,
  CatalogImportPreview,
  ImportedCatalogItem,
  ImportRole,
  Product,
  TenantConfig,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/**
 * Catalog import modal.
 *
 * Flow:
 *   1. Opens → kicks off POST /api/tenants/{id}/config/import-preview
 *   2. Receives a CatalogImportPreview of unified catalog items, each with a
 *      Zuora `category` and a `suggested_role` (base/add-on).
 *   3. Renders one row per product with:
 *        - a Base / Add-on toggle (defaulted from the suggestion)
 *        - a tier number input when the row is Base
 *        - the `category` badge + sku / product number / description, to help
 *          the user decide
 *        - rate-plan checkboxes (which plans to actually pull in)
 *   4. "Import selected" splits the rows by their chosen role — Base rows
 *      become tier Products, Add-on rows turn each selected rate plan into an
 *      Addon — then MERGES into the current config (matched by
 *      product_rate_plan_id; unselected items are left alone).
 *   5. Parent receives the merged config via onImport and decides when to PUT.
 */

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tenantId: number;
  currentConfig: TenantConfig;
  onImport: (merged: { products: Product[]; addons: Addon[] }) => void;
}

interface ItemState {
  role: ImportRole;
  tier: number;
}

export function CatalogImportModal({
  open,
  onOpenChange,
  tenantId,
  currentConfig,
  onImport,
}: Props) {
  const [filter, setFilter] = useState("");
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  // Which rate plans are selected, encoded as `${itemIdx}:${rpIdx}`.
  const [selectedRP, setSelectedRP] = useState<Set<string>>(new Set());
  // Per-item role + tier overrides, keyed by item index.
  const [itemState, setItemState] = useState<Record<number, ItemState>>({});

  const importMut = useMutation({
    mutationFn: () => api.importCatalog(tenantId),
    onSuccess: (preview) => {
      // Pre-select every rate plan, and seed role/tier from the server guess.
      const rp = new Set<string>();
      const st: Record<number, ItemState> = {};
      preview.items.forEach((it, i) => {
        it.rate_plans.forEach((_rp, rpi) => rp.add(`${i}:${rpi}`));
        st[i] = { role: it.suggested_role, tier: it.tier || 1 };
      });
      setSelectedRP(rp);
      setItemState(st);
      setExpanded(new Set(preview.items.map((_, i) => i)));
    },
  });

  // Re-fire the import on every open so the preview is always fresh.
  useQuery({
    queryKey: ["catalog-import-autostart", tenantId, open],
    queryFn: async () => {
      if (open && !importMut.isPending && !importMut.data) {
        importMut.mutate();
      }
      return null;
    },
    enabled: open,
    staleTime: Infinity,
  });

  const preview = importMut.data as CatalogImportPreview | undefined;

  const filteredItems = useMemo(() => {
    if (!preview) return [];
    const list = preview.items.map((it, i) => ({ it, i }));
    if (!filter.trim()) return list;
    const needle = filter.toLowerCase();
    return list.filter(
      ({ it }) =>
        it.label.toLowerCase().includes(needle) ||
        (it.category ?? "").toLowerCase().includes(needle) ||
        (it.sku ?? "").toLowerCase().includes(needle) ||
        it.rate_plans.some((rp) => rp.name.toLowerCase().includes(needle))
    );
  }, [preview, filter]);

  const counts = useMemo(() => {
    if (!preview) return { base: 0, addon: 0, ratePlans: 0 };
    const baseProducts = new Set<number>();
    let addonPlans = 0;
    selectedRP.forEach((k) => {
      const i = Number(k.split(":")[0]);
      const role = itemState[i]?.role ?? preview.items[i]?.suggested_role;
      if (role === "base") baseProducts.add(i);
      else addonPlans += 1;
    });
    return {
      base: baseProducts.size,
      addon: addonPlans,
      ratePlans: selectedRP.size,
    };
  }, [preview, selectedRP, itemState]);

  const toggleExpand = (i: number) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(i) ? next.delete(i) : next.add(i);
      return next;
    });

  const toggleItem = (i: number, rpCount: number) =>
    setSelectedRP((prev) => {
      const next = new Set(prev);
      const allSelected = Array.from({ length: rpCount }).every((_, rpi) =>
        next.has(`${i}:${rpi}`)
      );
      for (let rpi = 0; rpi < rpCount; rpi++) {
        allSelected ? next.delete(`${i}:${rpi}`) : next.add(`${i}:${rpi}`);
      }
      return next;
    });

  const toggleRatePlan = (i: number, rpi: number) =>
    setSelectedRP((prev) => {
      const next = new Set(prev);
      const key = `${i}:${rpi}`;
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });

  const setRole = (i: number, role: ImportRole) =>
    setItemState((prev) => ({
      ...prev,
      [i]: { role, tier: prev[i]?.tier ?? 1 },
    }));

  const setTier = (i: number, tier: number) =>
    setItemState((prev) => ({
      ...prev,
      [i]: { role: prev[i]?.role ?? "base", tier },
    }));

  const selectAll = () => {
    if (!preview) return;
    const rp = new Set<string>();
    preview.items.forEach((it, i) =>
      it.rate_plans.forEach((_rp, rpi) => rp.add(`${i}:${rpi}`))
    );
    setSelectedRP(rp);
  };

  const selectNone = () => setSelectedRP(new Set());

  const doImport = () => {
    if (!preview) return;
    const importedProducts: Product[] = [];
    const importedAddons: Addon[] = [];

    preview.items.forEach((it, i) => {
      const role = itemState[i]?.role ?? it.suggested_role;
      const tier = itemState[i]?.tier ?? it.tier ?? 1;
      const selectedPlans = it.rate_plans.filter((_rp, rpi) =>
        selectedRP.has(`${i}:${rpi}`)
      );
      if (selectedPlans.length === 0) return;

      if (role === "base") {
        importedProducts.push({
          label: it.label,
          tier,
          rate_plans: selectedPlans.map((rp) => ({
            name: rp.name,
            period: rp.period,
            product_rate_plan_id: rp.product_rate_plan_id,
          })),
        });
      } else {
        for (const rp of selectedPlans) {
          const name = rp.name ? `${it.label} — ${rp.name}` : it.label;
          importedAddons.push({
            name,
            product_rate_plan_id: rp.product_rate_plan_id,
          });
        }
      }
    });

    // Renumber base tiers to 1..N with no gaps, preserving the user's order.
    importedProducts.sort((a, b) => a.tier - b.tier);
    importedProducts.forEach((p, idx) => (p.tier = idx + 1));

    const merged = mergeCatalog(currentConfig, importedProducts, importedAddons);
    onImport(merged);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Import catalog from Zuora</DialogTitle>
          <DialogDescription>
            Pick the rate plans to pull in and set each product as a Base tier
            or an Add-on. The default split comes from each product's Zuora
            category — override it with the toggle. Matching rate plan IDs are
            updated; new ones appended; unselected items left alone.
          </DialogDescription>
        </DialogHeader>

        {importMut.isPending && (
          <p className="py-8 text-center text-muted-foreground">
            Fetching catalog from Zuora…
          </p>
        )}
        {importMut.isError && (
          <div className="rounded-md border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
            <strong>Import failed.</strong>{" "}
            {(importMut.error as Error | null)?.message || "Unknown error"}
          </div>
        )}

        {preview && (
          <>
            <div className="flex items-center gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  className="pl-8"
                  placeholder="Search products, categories, SKUs, rate plans…"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                />
              </div>
              <Button variant="outline" size="sm" onClick={selectAll}>
                Select all
              </Button>
              <Button variant="outline" size="sm" onClick={selectNone}>
                Select none
              </Button>
            </div>

            <div className="max-h-[50vh] overflow-y-auto rounded-md border">
              {preview.warnings.length > 0 && (
                <div className="border-b bg-amber-500/10 p-2 text-xs text-amber-400">
                  {preview.warnings.map((w, i) => (
                    <div key={i}>⚠ {w}</div>
                  ))}
                </div>
              )}

              {filteredItems.length > 0 ? (
                <div className="divide-y">
                  {filteredItems.map(({ it, i }) => (
                    <ItemRow
                      key={i}
                      itemIdx={i}
                      item={it}
                      role={itemState[i]?.role ?? it.suggested_role}
                      tier={itemState[i]?.tier ?? it.tier ?? 1}
                      expanded={expanded.has(i)}
                      selection={selectedRP}
                      onToggleExpand={() => toggleExpand(i)}
                      onToggleItem={() => toggleItem(i, it.rate_plans.length)}
                      onToggleRatePlan={(rpi) => toggleRatePlan(i, rpi)}
                      onSetRole={(r) => setRole(i, r)}
                      onSetTier={(t) => setTier(i, t)}
                    />
                  ))}
                </div>
              ) : (
                <p className="p-4 text-center text-sm text-muted-foreground">
                  Nothing matches "{filter}".
                </p>
              )}
            </div>
          </>
        )}

        <DialogFooter>
          <div className="mr-auto text-xs text-muted-foreground">
            {preview && (
              <>
                {counts.base} base product{counts.base !== 1 ? "s" : ""} ·{" "}
                {counts.addon} add-on{counts.addon !== 1 ? "s" : ""} ·{" "}
                {counts.ratePlans} rate plan{counts.ratePlans !== 1 ? "s" : ""}{" "}
                selected
              </>
            )}
          </div>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={doImport} disabled={!preview || counts.ratePlans === 0}>
            Import selected
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RoleToggle({
  role,
  onSetRole,
}: {
  role: ImportRole;
  onSetRole: (r: ImportRole) => void;
}) {
  return (
    <div
      className="flex overflow-hidden rounded-md border text-xs"
      onClick={(e) => e.stopPropagation()}
    >
      {(["base", "addon"] as const).map((r) => (
        <button
          key={r}
          type="button"
          onClick={() => onSetRole(r)}
          className={cn(
            "px-2 py-1 font-medium transition-colors",
            role === r
              ? "bg-primary text-primary-foreground"
              : "bg-transparent text-muted-foreground hover:bg-accent/40"
          )}
        >
          {r === "base" ? "Base" : "Add-on"}
        </button>
      ))}
    </div>
  );
}

function ItemRow({
  itemIdx,
  item,
  role,
  tier,
  expanded,
  selection,
  onToggleExpand,
  onToggleItem,
  onToggleRatePlan,
  onSetRole,
  onSetTier,
}: {
  itemIdx: number;
  item: ImportedCatalogItem;
  role: ImportRole;
  tier: number;
  expanded: boolean;
  selection: Set<string>;
  onToggleExpand: () => void;
  onToggleItem: () => void;
  onToggleRatePlan: (rpi: number) => void;
  onSetRole: (r: ImportRole) => void;
  onSetTier: (t: number) => void;
}) {
  const selectedCount = item.rate_plans.filter((_, rpi) =>
    selection.has(`${itemIdx}:${rpi}`)
  ).length;
  const allSelected = selectedCount === item.rate_plans.length;
  const someSelected = selectedCount > 0 && !allSelected;

  // Secondary metadata line — only render the bits that exist.
  const meta = [
    item.sku ? `SKU ${item.sku}` : null,
    item.product_number || null,
    item.description || null,
  ].filter(Boolean) as string[];

  return (
    <div>
      <div
        className="flex cursor-pointer items-center gap-3 px-3 py-2 hover:bg-accent/40"
        onClick={onToggleExpand}
      >
        <button
          type="button"
          className="text-muted-foreground"
          onClick={(e) => {
            e.stopPropagation();
            onToggleExpand();
          }}
        >
          {expanded ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
        </button>
        <Checkbox
          checked={allSelected ? true : someSelected ? "indeterminate" : false}
          onCheckedChange={onToggleItem}
          onClick={(e) => e.stopPropagation()}
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate text-sm font-medium">{item.label}</p>
            <span
              className={cn(
                "shrink-0 rounded px-1.5 py-0.5 text-[0.6rem] font-semibold uppercase tracking-wide",
                item.category
                  ? "bg-muted text-muted-foreground"
                  : "bg-amber-500/15 text-amber-400"
              )}
            >
              {item.category ?? "no category"}
            </span>
          </div>
          <p className="truncate text-xs text-muted-foreground">
            {selectedCount}/{item.rate_plans.length} rate plan
            {item.rate_plans.length !== 1 ? "s" : ""} selected
            {meta.length > 0 && <> · {meta.join(" · ")}</>}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {role === "base" && (
            <div
              className="flex items-center gap-1"
              onClick={(e) => e.stopPropagation()}
            >
              <span className="text-[0.65rem] text-muted-foreground">tier</span>
              <Input
                type="number"
                min={1}
                value={tier}
                onChange={(e) =>
                  onSetTier(Math.max(1, Number(e.target.value) || 1))
                }
                className="h-7 w-14 px-1.5 text-center text-xs"
              />
            </div>
          )}
          <RoleToggle role={role} onSetRole={onSetRole} />
        </div>
      </div>
      {expanded && (
        <div className="ml-8 divide-y border-l">
          {item.rate_plans.map((rp, rpi) => {
            const key = `${itemIdx}:${rpi}`;
            return (
              <div
                key={rpi}
                className="flex cursor-pointer items-center gap-3 px-3 py-1.5 text-sm hover:bg-accent/40"
                onClick={() => onToggleRatePlan(rpi)}
              >
                <Checkbox
                  checked={selection.has(key)}
                  onCheckedChange={() => onToggleRatePlan(rpi)}
                />
                <div className="flex-1">
                  <span>{rp.name}</span>
                  <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-[0.65rem] font-semibold">
                    {rp.period}
                  </span>
                </div>
                <code className="text-[0.65rem] text-muted-foreground">
                  {rp.product_rate_plan_id}
                </code>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/**
 * Merge imported products + addons into the current config.
 * Existing entries (matched by product_rate_plan_id) are updated; new
 * entries are appended; everything else is left alone.
 */
function mergeCatalog(
  current: TenantConfig,
  importedProducts: Product[],
  importedAddons: Addon[]
): { products: Product[]; addons: Addon[] } {
  // Build a lookup from product rate plan ID → (productIdx, ratePlanIdx).
  const idIndex = new Map<string, { pi: number; rpi: number }>();
  current.products.forEach((p, pi) =>
    p.rate_plans.forEach((rp, rpi) => {
      if (rp.product_rate_plan_id) idIndex.set(rp.product_rate_plan_id, { pi, rpi });
    })
  );

  const products = current.products.map((p) => ({ ...p, rate_plans: [...p.rate_plans] }));

  for (const imp of importedProducts) {
    // Does ANY of this imported product's rate plans match an existing rate plan?
    const firstHit = imp.rate_plans.find((rp) => idIndex.has(rp.product_rate_plan_id));
    if (firstHit) {
      const { pi } = idIndex.get(firstHit.product_rate_plan_id)!;
      // Update existing product in place.
      products[pi] = { ...products[pi], label: imp.label, tier: imp.tier };
      // Update/append each rate plan.
      for (const rp of imp.rate_plans) {
        const existingIdx = products[pi].rate_plans.findIndex(
          (x) => x.product_rate_plan_id === rp.product_rate_plan_id
        );
        if (existingIdx >= 0) {
          products[pi].rate_plans[existingIdx] = { ...rp };
        } else {
          products[pi].rate_plans.push({ ...rp });
        }
      }
    } else {
      // Append whole new product.
      products.push({ ...imp, rate_plans: [...imp.rate_plans] });
    }
  }

  // Add-ons: merge by product_rate_plan_id.
  const addons = [...current.addons];
  const addonIds = new Set(addons.map((a) => a.product_rate_plan_id));
  for (const a of importedAddons) {
    if (addonIds.has(a.product_rate_plan_id)) {
      const idx = addons.findIndex((x) => x.product_rate_plan_id === a.product_rate_plan_id);
      addons[idx] = { ...a };
    } else {
      addons.push({ ...a });
      addonIds.add(a.product_rate_plan_id);
    }
  }

  return { products, addons };
}
