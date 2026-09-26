export interface Ward {
  id: string;
  name: string;
  name_hi?: string | null;
  department_id: string | null;
  facility_id: string;
  is_active: boolean;
}

export interface WardSelectorProps {
  wards: Ward[];
  selectedWard: string;
  onChange: (wardId: string) => void;
}