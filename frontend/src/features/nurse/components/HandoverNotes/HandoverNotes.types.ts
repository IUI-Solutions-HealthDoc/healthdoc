export type Shift = "morning" | "evening" | "night";

export interface HandoverNote {
  id: string;
  admission_id: string;
  shift: Shift;
  situation: string | null;
  background: string | null;
  assessment: string | null;
  recommendation: string | null;
  handed_over_to: string;
  /** Resolved server-side so the ward board is not an N+1 of user fetches. */
  handed_over_to_name?: string | null;
  created_by?: string;
  created_by_name?: string | null;
  created_at?: string;
}

export interface HandoverNotesProps {
  admissionId: string | null;
  notes: HandoverNote[];
}
