interface ExpiryChipProps {
  daysLeft: number;
}

export default function ExpiryChip({
  daysLeft,
}: ExpiryChipProps) {
  let bg = "";
  let text = "";

  if (daysLeft <= 0) {
    bg = "bg-red-100 text-red-700";
    text = "Expired";
  } else if (daysLeft <= 30) {
    bg = "bg-orange-100 text-orange-700";
    text = `${daysLeft} Days Left`;
  } else if (daysLeft <= 90) {
    bg = "bg-yellow-100 text-yellow-700";
    text = `${daysLeft} Days Left`;
  } else {
    bg = "bg-green-100 text-green-700";
    text = `${daysLeft} Days Left`;
  }

  return (
    <span
      className={`px-3 py-1 rounded-full text-xs font-semibold ${bg}`}
    >
      {text}
    </span>
  );
}