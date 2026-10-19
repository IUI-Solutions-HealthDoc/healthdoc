import { translate } from "@/lib/i18n";
interface ResultFlagProps {
  flag: string;
}

const styles: Record<string, string> = {
  HIGH: "text-[#d61f26]",
  LOW: "text-[#1d4ed8]",
  BORDERLINE: "text-[#ea580c]",
  CRITICAL: "text-[#d61f26]",
  PANIC: "text-[#7e22ce]",
};

const labels: Record<string, string> = {
  get HIGH() { return translate("common.msg.high"); },
  LOW: "Low",
  get BORDERLINE() { return translate("common.msg.borderline"); },
  get CRITICAL() { return translate("equipment.critical"); },
  get PANIC() { return translate("common.msg.panic"); },
};

export default function ResultFlagLabel({ flag }: ResultFlagProps) {
  if (flag === "NORMAL" || !labels[flag]) return null;

  return (
    <span className={`ml-1.5 text-[11px] font-semibold ${styles[flag]}`}>
      {labels[flag]}
    </span>
  );
}
