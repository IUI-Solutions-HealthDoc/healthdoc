import { ReportData } from "../types/report";

export const report: ReportData = {
  status: "VERIFIED",

  laboratory: {
    id: "LAB-001",
    name: "ABC Diagnostics Laboratory",
    logo: "/healthdoc-logo.png",
    nablNumber: "NABL-M-123456",
    address:
      "105 - 108, Smart Square, Near D-Mart, Bhumkar Chowk, Pune - 411057",
    phone: "095125 23250",
    phoneSecondary: "+91 89806 97395",
    email: "support@abcdiagnostics.com",
    website: "www.abcdiagnostics.com",
    tagline: "Accurate | Caring | Instant",
  },

  patient: {
    patientId: "P120",
    uhid: "UHID-202600123",
    name: "Rahul Sharma",
    age: 28,
    gender: "Male",
    dob: "1998-03-14",
    mobile: "9876543210",
  },

  visit: {
    visitId: "VIS-100001",
    visitType: "OPD",
    encounterNumber: "ENC-100001",
  },

  doctor: {
    doctorId: "DOC-1005",
    name: "Dr. Amit Verma",
    qualification: "MBBS, MD",
    department: "Internal Medicine",
    registrationNumber: "DMC123456",
    hospital: "City Care Hospital",
  },

  order: {
    orderId: "ORD-10001",
    priority: "Routine",
    orderedAt: "2026-07-13T08:55:00Z",
  },

  sample: {
    accessionNumber: "ACC-20260713-001",
    sampleId: "LAB-20260713-001",
    barcode: "LAB-20260713-001",
    sampleType: "Whole Blood",
    container: "EDTA Tube",
    collectedAt: "2026-07-13T09:15:00Z",
    collectedAtLocation:
      "105 - 108, Smart Square, Near D-Mart, Bhumkar Chowk, Pune - 411057",
    receivedAt: "2026-07-13T09:35:00Z",
    processedAt: "2026-07-13T10:20:00Z",
  },

  reportInfo: {
    reportId: "REP-20260713-0001",
    reportNumber: "RPT-100254",
    title: "Complete Blood Count (CBC)",
    category: "Hematology",
    method: "Automated Cell Counter",
    instruments: "Fully Automated Cell Counter - Mindray 300",
    reportedAt: "2026-07-13T12:30:00Z",
    verifiedAt: "2026-07-13T12:40:00Z",
  },

  testGroups: [
    {
      groupId: "HB",
      groupName: "HEMOGLOBIN",
      results: [
        {
          code: "HB",
          name: "Hemoglobin (Hb)",
          result: "13.8",
          unit: "g/dL",
          referenceRange: "13.0 - 17.0",
          flag: "NORMAL",
          displayOrder: 1,
        },
      ],
    },
    {
      groupId: "RBC",
      groupName: "RBC COUNT",
      results: [
        {
          code: "RBC",
          name: "Total RBC count",
          result: "4.92",
          unit: "mill/cumm",
          referenceRange: "4.5 - 5.5",
          flag: "NORMAL",
          displayOrder: 1,
        },
      ],
    },
    {
      groupId: "INDICES",
      groupName: "BLOOD INDICES",
      results: [
        {
          code: "PCV",
          name: "Packed Cell Volume (PCV)",
          note: "Calculated",
          result: "41.2",
          unit: "%",
          referenceRange: "40 - 50",
          flag: "NORMAL",
          displayOrder: 1,
        },
        {
          code: "MCV",
          name: "Mean Corpuscular Volume (MCV)",
          note: "Calculated",
          result: "83.7",
          unit: "fL",
          referenceRange: "83 - 101",
          flag: "NORMAL",
          displayOrder: 2,
        },
        {
          code: "MCH",
          name: "MCH",
          note: "Calculated",
          result: "28.0",
          unit: "pg",
          referenceRange: "27 - 32",
          flag: "NORMAL",
          displayOrder: 3,
        },
        {
          code: "MCHC",
          name: "MCHC",
          note: "Calculated",
          result: "33.5",
          unit: "%",
          referenceRange: "32.5 - 34.5",
          flag: "NORMAL",
          displayOrder: 4,
        },
        {
          code: "RDW",
          name: "RDW",
          result: "14.8",
          unit: "%",
          referenceRange: "11.6 - 14.0",
          flag: "HIGH",
          displayOrder: 5,
        },
      ],
    },
    {
      groupId: "WBC",
      groupName: "WBC COUNT",
      results: [
        {
          code: "WBC",
          name: "Total WBC count",
          result: "7200",
          unit: "cumm",
          referenceRange: "4000 - 11000",
          flag: "NORMAL",
          displayOrder: 1,
        },
      ],
    },
    {
      groupId: "DIFF",
      groupName: "DIFFERENTIAL COUNT",
      results: [
        {
          code: "NEUT",
          name: "Neutrophils",
          result: "60",
          unit: "%",
          referenceRange: "40 - 75",
          flag: "NORMAL",
          displayOrder: 1,
        },
        {
          code: "LYMP",
          name: "Lymphocytes",
          result: "30",
          unit: "%",
          referenceRange: "20 - 45",
          flag: "NORMAL",
          displayOrder: 2,
        },
        {
          code: "EOS",
          name: "Eosinophils",
          result: "8",
          unit: "%",
          referenceRange: "1 - 6",
          flag: "HIGH",
          displayOrder: 3,
        },
        {
          code: "MONO",
          name: "Monocytes",
          result: "2",
          unit: "%",
          referenceRange: "2 - 10",
          flag: "NORMAL",
          displayOrder: 4,
        },
        {
          code: "BASO",
          name: "Basophils",
          result: "0",
          unit: "%",
          referenceRange: "< 2",
          flag: "NORMAL",
          displayOrder: 5,
        },
      ],
    },
    {
      groupId: "PLT",
      groupName: "PLATELET COUNT",
      results: [
        {
          code: "PLT",
          name: "Platelet Count",
          result: "255000",
          unit: "cumm",
          referenceRange: "150000 - 410000",
          flag: "NORMAL",
          displayOrder: 1,
        },
        {
          code: "ESR",
          name: "ESR (Westergren)",
          result: "30",
          unit: "mm/hr",
          referenceRange: "0 - 20",
          flag: "HIGH",
          displayOrder: 2,
        },
      ],
    },
  ],

  remarks: {
    interpretation: "Further confirm with clinical correlation. ESR is mildly elevated.",
    comments: "CBC parameters are largely within normal limits.",
    advice: "Clinical correlation is advised.",
  },

  verification: {
    verifiedBy: "Dr. Neha Sharma",
    qualification: "MD, Pathologist",
    designation: "Consultant Pathologist",
    registrationNumber: "PMC45896",
    verifiedAt: "2026-07-13T12:40:00Z",
    digitalSignature: "/images/signatures/neha-sharma.png",
    digitallySigned: true,
  },

  signatories: [
    {
      name: "Mr. Rohit Mehta",
      qualification: "DMLT",
      designation: "Medical Lab Technician",
      signature: "/images/signatures/neha-sharma.png",
    },
    {
      name: "Dr. Neha Sharma",
      qualification: "MD, Pathologist",
      designation: "Pathologist",
      signature: "/images/signatures/neha-sharma.png",
    },
    {
      name: "Dr. Amit Desai",
      qualification: "MD, Pathologist",
      designation: "Pathologist",
      signature: "/images/signatures/neha-sharma.png",
    },
  ],

  footer: {
    disclaimer:
      "This is a digitally verified report. No physical signature is required.",
    generatedAt: "2026-07-13T12:41:00Z",
    generatedBy: "Laboratory Information System (LIS)",
    version: 1,
    printedAt: "2026-07-13T12:45:00Z",
    whatsapp: "+91 89806 97395",
  },

  qrCode: {
    value: "https://abcdiagnostics.com/report/REP-20260713-0001",
  },
};
