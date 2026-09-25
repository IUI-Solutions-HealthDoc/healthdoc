import { QuickAction } from "./QuickActions.types";

export const QUICK_ACTIONS: QuickAction[] = [
  {
    id: "vitals",
    labelKey: "nurse.actionAddVitals",
    icon: "🩺",
    color: "bg-blue-100 text-blue-700",
  },
  {
    id: "note",
    labelKey: "nurse.actionNursingNote",
    icon: "📝",
    color: "bg-green-100 text-green-700",
  },
  {
    id: "incident",
    labelKey: "nurse.actionIncidentReport",
    icon: "⚠️",
    color: "bg-orange-100 text-orange-700",
  },
  {
    id: "medication",
    labelKey: "nurse.actionMedication",
    icon: "💊",
    color: "bg-purple-100 text-purple-700",
  },
  {
    id: "transfer",
    labelKey: "nurse.actionWardTransfer",
    icon: "🚑",
    color: "bg-yellow-100 text-yellow-700",
  },
  {
    id: "doctor",
    labelKey: "nurse.actionCallDoctor",
    icon: "👨‍⚕️",
    color: "bg-red-100 text-red-700",
  },
  {
    id: "history",
    labelKey: "nurse.actionViewHistory",
    icon: "📋",
    color: "bg-slate-100 text-slate-700",
  },
];
