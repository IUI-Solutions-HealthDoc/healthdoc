// FACILITY_ID re-exported MOCK_FACILITY_ID and had no consumers: consent is
// read per patient and scoped server-side through that patient, because
// consent_records has no facility_id of its own. Removed (P1.1).

export {
  ACCESS_CHANNELS,
  CONSENT_CHANNELS,
  CONSENT_STATUSES,
  accessChannelLabel,
  accessChannelLabels,
  consentChannelFormLabel,
  consentChannelLabel,
  consentPurposeLabel,
  consentStatusLabel,
} from "./i18nLabels";
