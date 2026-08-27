"use client";

interface StockLevelBadgeProps {
  quantity: number;
  minimumQuantity: number;
}

export default function StockLevelBadge({
  quantity,
  minimumQuantity,
}: StockLevelBadgeProps) {
  let label = "";
  let badgeClass = "";

  if (quantity === 0) {
    label = "Out of Stock";
    badgeClass = "bg-red-100 text-red-700";
  } else if (quantity <= minimumQuantity) {
    label = "Low Stock";
    badgeClass = "bg-yellow-100 text-yellow-700";
  } else {
    label = "In Stock";
    badgeClass = "bg-green-100 text-green-700";
  }

  return (
    <span
      className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${badgeClass}`}
      style={{ fontFamily: "IBM Plex Mono" }}
    >
      {label}
    </span>
  );
}