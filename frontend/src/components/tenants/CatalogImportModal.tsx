import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Search } from "lucide-react";
import { api } from "@/lib/api";
import type {
  Addon,
  CatalogImportPreview,
  ImportedProduct,
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
 *   2. Receives a CatalogImportPreview
 *   3. Renders a two-level checkbox tree of products → rate plans,
 *      pre-selecting the classifier's guesses. Add-ons are a flat list
 *      with checkboxes.
 *   4. "Import selected" MERGES the selection into the current config:
 *      - Existing products with the same product_rate_plan_id are updated
 *      - New products are appended
 *      - Unselected items are left alone (not clobbered)
 *   5. Parent receives the merged config via onImport and decides when
 *      to PUT it back to the server.
 */

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tenantId: number;
  currentConfig: TenantConfig;
  onImport: (merged: { products: Product[]; addons: Addon[] }) => void;
}

interface SelectionState {
  // product label + rate plan index, encoded as `${prodIdx}:${rpIdx}`
  rate_plans: Set<string>;
  // addon index
  addons: Set<number>;
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
  const [selection, setSelection] = useState<SelectionState>({
    rate_plans: new Set(),
    addons: new Set(),
  });

  const importMut = useMutation({
    mutationFn: () => api.importCatalog(tenantId),
    onSuccess: (preview) => {
      // Pre-select everything by default.
      const rp = new Set<string>();
      preview.products.forEach((p, pi) => {
        p.rate_plans.forEach((_rp, rpi) => rp.add(`${pi}:${rpi}`));
      });
      const add = new Set<number>(preview.addons.map((_, i) => i));
      setSelection({ rate_plans: rp, addons: add });
      setExpanded(new Set(preview.products.map((_, i) => i)));
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

  const filteredProducts = useMemo(() => {
    if (!preview) return [];
    if (!filter.trim()) return preview.products.map((p, i) => ({ p, i }));
    const needle = filter.toLowerCase();
    return preview.products
      .map((p, i) => ({ p, i }))
      .filter(
        ({ p }) =>
          p.label.toLowerCase().includes(needle) ||
          p.rate_plans.some((rp) => rp.name.toLowerCase().includes(needle))
      );
  }, [preview, filter]);

  const filteredAddons = useMemo(() => {
    if (!preview) return [];
    if (!filter.trim()) return preview.addons.map((a, i) => ({ a, i }));
    const needle = filter.toLowerCase();
    return preview.addons
      .map((a, i) => ({ a, i }))
      .filter(({ a }) => a.name.toLowerCase().includes(needle));
  }, [preview, filter]);

  const counts = useMemo(() => {
    if (!preview) return { products: 0, ratePlans: 0, addons: 0 };
    const pset = new Set<number>();
    selection.rate_plans.forEach((k) => pset.add(Number(k.split(":")[0])));
    return {
      products: pset.size,
      ratePlans: selection.rate_plans.size,
      addons: selection.addons.size,
    };
  }, [preview, selection]);

  const toggleExpand = (i: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(i) ? next.delete(i) : next.add(i);
      return next;
    });
  };

  const toggleProduct = (pi: number, rpCount: number) => {
    setSelection((prev) => {
      const next = { ...prev, rate_plans: new Set(prev.rate_plans) };
      const allSelected = Array.from({ length: rpCount }).every((_, rpi) =>
        next.rate_plans.has(`${pi}:${rpi}`)
      );
      if (allSelected) {
        for (let rpi = 0; rpi < rpCount; rpi++) next.rate_plans.delete(`${pi}:${rpi}`);
      } else {
        for (let rpi = 0; rpi < rpCount; rpi++) next.rate_plans.add(`${pi}:${rpi}`);
      }
      return next;
    });
  };

  const toggleRatePlan = (pi: number, rpi: number) => {
    setSelection((prev) => {
      const next = { ...prev, rate_plans: new Set(prev.rate_plans) };
      const key = `${pi}:${rpi}`;
      next.rate_plans.has(key) ? next.rate_plans.delete(key) : next.rate_plans.add(key);
      return next;
    });
  };

  const toggleAddon = (i: number) => {
    setSelection((prev) => {
      const next = { ...prev, addons: new Set(prev.addons) };
      next.addons.has(i) ? next.addons.delete(i) : next.addons.add(i);
      return next;
    });
  };

  const selectAll = () => {
    if (!preview) return;
    const rp = new Set<string>();
    preview.products.forEach((p, pi) => {
      p.rate_plans.forEach((_rp, rpi) => rp.add(`${pi}:${rpi}`));
    });
    setSelection({ rate_plans: rp, addons: new Set(preview.addons.map((_, i) => i)) });
  };

  const selectNone = () => {
    setSelection({ rate_plans: new Set(), addons: new Set() });
  };

  const doImport = () => {
    if (!preview) return;
    // Build the partial import product list from the selection.
    const importedProducts: Product[] = preview.products
      .map((p, pi) => ({
        label: p.label,
        tier: p.tier,
        rate_plans: p.rate_plans
          .map((rp, rpi) =>
            selection.rate_plans.has(`${pi}:${rpi}`)
              ? { name: rp.name, period: rp.period, product_rate_plan_id: rp.product_rate_plan_id }
              : null
          )
          .filter((x): x is NonNullable<typeof x> => x !== null),
      }))
      .filter((p) => p.rate_plans.length > 0);

    const importedAddons: Addon[] = preview.addons
      .filter((_, i) => selection.addons.has(i))
      .map((a) => ({ name: a.name, product_rate_plan_id: a.product_rate_plan_id }));

    // Merge into current config (don't clobber unselected).
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
            Select the products and add-ons to pull in. Existing entries with
            matching rate plan IDs will be updated; new ones will be appended;
            unselected items will be left alone.
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
                  placeholder="Search products or rate plans…"
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

              {filteredProducts.length > 0 && (
                <div className="divide-y">
                  <div className="bg-muted/40 px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Products
                  </div>
                  {filteredProducts.map(({ p, i }) => (
                    <ProductRow
                      key={i}
                      prodIdx={i}
                      product={p}
                      expanded={expanded.has(i)}
                      onToggleExpand={() => toggleExpand(i)}
                      selection={selection.rate_plans}
                      onToggleProduct={() => toggleProduct(i, p.rate_plans.length)}
                      onToggleRatePlan={(rpi) => toggleRatePlan(i, rpi)}
                    />
                  ))}
                </div>
              )}

              {filteredAddons.length > 0 && (
                <div className="divide-y">
                  <div className="bg-muted/40 px-3 py-1.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Add-ons
                  </div>
                  {filteredAddons.map(({ a, i }) => (
                    <div
                      key={i}
                      className="flex cursor-pointer items-center gap-3 px-3 py-2 hover:bg-accent/40"
                      onClick={() => toggleAddon(i)}
                    >
                      <Checkbox
                        checked={selection.addons.has(i)}
                        onCheckedChange={() => toggleAddon(i)}
                      />
                      <div className="flex-1">
                        <p className="text-sm">{a.name}</p>
                        <p className="font-mono text-[0.65rem] text-muted-foreground">
                          {a.product_rate_plan_id}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {filteredProducts.length === 0 && filteredAddons.length === 0 && (
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
                {counts.products} product{counts.products !== 1 ? "s" : ""} ·{" "}
                {counts.ratePlans} rate plan{counts.ratePlans !== 1 ? "s" : ""} ·{" "}
                {counts.addons} add-on{counts.addons !== 1 ? "s" : ""} selected
              </>
            )}
          </div>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={doImport}
            disabled={!preview || (counts.ratePlans === 0 && counts.addons === 0)}
          >
            Import selected
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ProductRow({
  prodIdx,
  product,
  expanded,
  onToggleExpand,
  selection,
  onToggleProduct,
  onToggleRatePlan,
}: {
  prodIdx: number;
  product: ImportedProduct;
  expanded: boolean;
  onToggleExpand: () => void;
  selection: Set<string>;
  onToggleProduct: () => void;
  onToggleRatePlan: (rpi: number) => void;
}) {
  const selectedCount = product.rate_plans.filter((_, rpi) =>
    selection.has(`${prodIdx}:${rpi}`)
  ).length;
  const allSelected = selectedCount === product.rate_plans.length;
  const someSelected = selectedCount > 0 && !allSelected;

  return (
    <div className="">
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
          {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </button>
        <Checkbox
          checked={allSelected ? true : someSelected ? "indeterminate" : false}
          onCheckedChange={onToggleProduct}
          onClick={(e) => e.stopPropagation()}
        />
        <div className="flex-1">
          <p className="text-sm font-medium">{product.label}</p>
          <p className="text-xs text-muted-foreground">
            tier {product.tier} · {selectedCount}/{product.rate_plans.length} rate plans selected
          </p>
        </div>
      </div>
      {expanded && (
        <div className="ml-8 divide-y border-l">
          {product.rate_plans.map((rp, rpi) => {
            const key = `${prodIdx}:${rpi}`;
            return (
              <div
                key={rpi}
                className={cn(
                  "flex cursor-pointer items-center gap-3 px-3 py-1.5 text-sm hover:bg-accent/40"
                )}
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
                <code className="text-[0.65rem] text-muted-foreground">{rp.product_rate_plan_id}</code>
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
