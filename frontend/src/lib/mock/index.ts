/**
 * Mock data placeholders until backend APIs are connected.
 */

export type MockPatient = {
  id: string;
  name: string;
  uhid: string;
};

export type MockUser = {
  id: string;
  name: string;
  role: string;
};

export const mockPatients: MockPatient[] = [];

export const mockUsers: MockUser[] = [];
