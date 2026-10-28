import type { InventoryView as SeedView, InventorySummary as SeedSummary } from "./domain-types";

type UnknownStock = "reserved" | "inbound" | "available" | "projected" | "target_stock" | "shortage" | "version";
export type InventoryView = Omit<SeedView, UnknownStock> & Record<UnknownStock, number | null> & {
  part_name?: string;
  safety_shortage?: number;
  missing_fields?: string[];
};
type UnknownTotal = "total_reserved" | "total_inbound" | "total_available" | "total_projected" | "total_target_stock" | "total_shortage";
export type InventorySummary = Omit<SeedSummary, UnknownTotal> & Record<UnknownTotal, number | null>;
