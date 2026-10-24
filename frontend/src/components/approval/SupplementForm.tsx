"use client";

type Props = { fields: string[]; warehouseId: string; setWarehouseId: (value: string) => void };

export function SupplementForm({ fields, warehouseId, setWarehouseId }: Props) {
  if (!fields.length) return null;
  return (
    <fieldset className="card" aria-label="补充草稿信息">
      <legend>需要补充的信息</legend>
      {fields.includes("warehouse_id") ? (
        <label>
          仓库编号
          <input aria-label="仓库编号" value={warehouseId} onChange={(event) => setWarehouseId(event.target.value)} placeholder="例如 W01" />
        </label>
      ) : <p>{fields.join("、")}</p>}
    </fieldset>
  );
}
