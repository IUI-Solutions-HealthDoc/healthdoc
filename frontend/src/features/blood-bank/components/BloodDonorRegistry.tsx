"use client";

import { useState } from "react";
import { AlertCircle, CheckCircle2, Heart, Plus, Search, UserCheck, UserX, X } from "lucide-react";
import { registerBloodDonor } from "../api";
import { useClinicalWrite } from "@/lib/useClinicalWrite";
import { useLocale } from "@/lib/i18n";
import { formatBloodGroup, type BloodDonor } from "../types";

interface BloodDonorRegistryProps {
  donors: BloodDonor[];
  onRefresh: () => void;
}

export function BloodDonorRegistry({ donors, onRefresh }: BloodDonorRegistryProps) {
  const { t } = useLocale();
  const [filterGroup, setFilterGroup] = useState<string>("all");
  const [filterEligible, setFilterEligible] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [isRegisterModalOpen, setIsRegisterModalOpen] = useState<boolean>(false);

  // Form state
  const [fullName, setFullName] = useState("");
  const [age, setAge] = useState<number>(28);
  const [gender, setGender] = useState("male");
  const [bloodGroup, setBloodGroup] = useState("O");
  const [rhFactor, setRhFactor] = useState("+");
  const [contactPhone, setContactPhone] = useState("");
  const [weight, setWeight] = useState("");
  const [hemoglobin, setHemoglobin] = useState("");
  const [lastDonation, setLastDonation] = useState("");
  const [ineligibilityReason, setIneligibilityReason] = useState("");

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const write = useClinicalWrite();

  const filteredDonors = donors.filter((d) => {
    const formatted = formatBloodGroup(d.blood_group, d.rh_factor);
    if (filterGroup !== "all" && formatted !== filterGroup) return false;
    if (filterEligible === "eligible" && !d.is_eligible) return false;
    if (filterEligible === "ineligible" && d.is_eligible) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const phone = d.contact_phone || d.mobile || "";
      const donorNum = d.donor_number || d.id.slice(0, 8);
      return (
        d.full_name.toLowerCase().includes(q) ||
        donorNum.toLowerCase().includes(q) ||
        phone.includes(q)
      );
    }
    return true;
  });

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isSubmitting || !write.isCurrent()) return;
    setError(null);
    if (!fullName.trim()) {
      setError(t("bloodBank.donor.errNameRequired"));
      return;
    }
    if (age < 18 || age > 65) {
      setError(t("bloodBank.donor.errAgeRange"));
      return;
    }

    try {
      setIsSubmitting(true);
      await write.run({
        full_name: fullName.trim(),
        age_years: age,
        sex: gender,
        blood_group: bloodGroup + rhFactor,
        mobile: contactPhone.trim() || null,
        weight_kg: Number(weight),
        hemoglobin_g_dl: Number(hemoglobin),
        last_donation_date: lastDonation || null,
        remarks: ineligibilityReason.trim() || null,
      }, registerBloodDonor);
      if (!write.isCurrent()) return;
      setIsRegisterModalOpen(false);
      // Reset
      setFullName("");
      setContactPhone("");
      setIneligibilityReason("");
      setWeight(""); setHemoglobin(""); setLastDonation("");
      onRefresh();
    } catch (err: unknown) {
      if (write.isCurrent()) {
        setError(err instanceof Error ? err.message : t("bloodBank.donor.errRegisterFailed"));
      }
    } finally {
      if (write.isCurrent()) setIsSubmitting(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Search and action bar */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 bg-card border border-border p-4 rounded-2xl shadow-sm">
        <div className="flex flex-1 items-center gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
            <input
              type="text"
              placeholder={t("bloodBank.donor.searchPlaceholder")}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full rounded-xl border border-input bg-background pl-9 pr-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-primary"
            />
          </div>

          <div className="flex items-center gap-2">
            <select
              value={filterGroup}
              onChange={(e) => setFilterGroup(e.target.value)}
              className="rounded-xl border border-input bg-background px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-primary font-medium"
            >
              <option value="all">{t("bloodBank.donor.allBloodGroups")}</option>
              <option value="A+">A+</option>
              <option value="A-">A-</option>
              <option value="B+">B+</option>
              <option value="B-">B-</option>
              <option value="AB+">AB+</option>
              <option value="AB-">AB-</option>
              <option value="O+">O+</option>
              <option value="O-">O-</option>
            </select>

            <select
              value={filterEligible}
              onChange={(e) => setFilterEligible(e.target.value)}
              className="rounded-xl border border-input bg-background px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-primary font-medium"
            >
              <option value="all">{t("bloodBank.donor.allEligibility")}</option>
              <option value="eligible">{t("bloodBank.donor.eligibleDonors")}</option>
              <option value="ineligible">{t("bloodBank.donor.deferredIneligible")}</option>
            </select>
          </div>
        </div>

        <button
          onClick={() => setIsRegisterModalOpen(true)}
          className="flex items-center justify-center gap-1.5 rounded-xl bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground hover:bg-primary/90 transition-colors shadow-sm shrink-0"
        >
          <Plus className="h-4 w-4" />
          {t("bloodBank.donor.registerNew")}
        </button>
      </div>

      {/* Donors Table */}
      <div className="rounded-2xl border border-border bg-card overflow-hidden shadow-sm">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-muted/50 text-muted-foreground font-semibold">
              <tr>
                <th className="p-3">{t("bloodBank.donor.col.donorNum")}</th>
                <th className="p-3">{t("bloodBank.donor.col.fullName")}</th>
                <th className="p-3">{t("bloodBank.col.bloodGroup")}</th>
                <th className="p-3">{t("bloodBank.donor.col.demographics")}</th>
                <th className="p-3">{t("bloodBank.donor.col.contact")}</th>
                <th className="p-3">{t("bloodBank.donor.col.eligibility")}</th>
                <th className="p-3">{t("bloodBank.donor.col.lastDonated")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {filteredDonors.length === 0 ? (
                <tr>
                  <td colSpan={7} className="p-8 text-center text-muted-foreground">
                    <Heart className="h-8 w-8 mx-auto mb-2 opacity-30 text-rose-500" />
                    {t("bloodBank.donor.empty")}
                  </td>
                </tr>
              ) : (
                filteredDonors.map((d) => (
                  <tr key={d.id} className="hover:bg-muted/30">
                    <td className="p-3 font-mono font-semibold text-foreground">
                      {d.donor_number || `DON-${d.id.slice(0, 8).toUpperCase()}`}
                    </td>
                    <td className="p-3 font-medium text-foreground">{d.full_name}</td>
                    <td className="p-3">
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-black bg-rose-500/10 text-rose-600 dark:text-rose-400">
                        {formatBloodGroup(d.blood_group, d.rh_factor)}
                      </span>
                    </td>
                    <td className="p-3 text-muted-foreground capitalize">
                      {d.age_years ?? t("bloodBank.notRecorded")} {t("bloodBank.donor.yearsSuffix")} • {d.sex || t("bloodBank.notRecorded")}
                    </td>
                    <td className="p-3 font-mono text-muted-foreground">{d.contact_phone || d.mobile || "—"}</td>
                    <td className="p-3">
                      {d.is_eligible ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] font-semibold text-emerald-600 dark:text-emerald-400">
                          <UserCheck className="h-3 w-3" /> {t("bloodBank.donor.eligible")}
                        </span>
                      ) : (
                        <span
                          title={d.ineligibility_reason || t("bloodBank.donor.deferred")}
                          className="inline-flex items-center gap-1 rounded-full bg-destructive/10 px-2 py-0.5 text-[11px] font-semibold text-destructive cursor-help"
                        >
                          <UserX className="h-3 w-3" /> {t("bloodBank.donor.deferred")}
                        </span>
                      )}
                    </td>
                    <td className="p-3 text-muted-foreground font-mono">
                      {d.last_donation_date || t("bloodBank.donor.firstTime")}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Registration Modal */}
      {isRegisterModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg rounded-2xl border border-border bg-card p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-200">
            <div className="flex items-center justify-between pb-4 border-b border-border">
              <div className="flex items-center gap-2">
                <Heart className="h-5 w-5 text-rose-500" />
                <h3 className="text-lg font-bold text-card-foreground">{t("bloodBank.donor.modalTitle")}</h3>
              </div>
              <button
                onClick={() => setIsRegisterModalOpen(false)}
                disabled={isSubmitting || write.retryPending}
                className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            {error && (
              <div className="mt-4 flex items-center gap-2 rounded-lg bg-destructive/10 p-3 text-sm text-destructive border border-destructive/20">
                <AlertCircle className="h-4 w-4 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <form onSubmit={handleRegister} className="mt-4 space-y-4">
              <fieldset disabled={isSubmitting || write.retryPending} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                  {t("field.fullName")} *
                </label>
                <input
                  type="text"
                  placeholder={t("bloodBank.donor.namePlaceholder")}
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                  required
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                    {t("bloodBank.donor.ageLabel")}
                  </label>
                  <input
                    type="number"
                    min="18"
                    max="65"
                    value={age}
                    onChange={(e) => setAge(parseInt(e.target.value) || 18)}
                    className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                    required
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                    {t("bloodBank.donor.genderLabel")}
                  </label>
                  <select
                    value={gender}
                    onChange={(e) => setGender(e.target.value)}
                    className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                  >
                    <option value="male">{t("bloodBank.donor.genderMale")}</option>
                    <option value="female">{t("bloodBank.donor.genderFemale")}</option>
                    <option value="other">{t("bloodBank.donor.genderOther")}</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                    {t("bloodBank.collect.aboGroup")}
                  </label>
                  <select
                    value={bloodGroup}
                    onChange={(e) => setBloodGroup(e.target.value)}
                    className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                  >
                    <option value="A">A</option>
                    <option value="B">B</option>
                    <option value="AB">AB</option>
                    <option value="O">O</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                    {t("bloodBank.collect.rhFactor")}
                  </label>
                  <select
                    value={rhFactor}
                    onChange={(e) => setRhFactor(e.target.value)}
                    className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                  >
                    <option value="+">{t("bloodBank.collect.rhPositive")}</option>
                    <option value="-">{t("bloodBank.collect.rhNegative")}</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                  {t("bloodBank.donor.contactPhone")}
                </label>
                <input
                  type="tel"
                  placeholder="+91 98765 43210"
                  value={contactPhone}
                  onChange={(e) => setContactPhone(e.target.value)}
                  className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </div>

              <div className="rounded-xl border border-border p-3 space-y-2 bg-muted/20">
                <p className="text-xs">{t("bloodBank.donor.eligibilityHint")}</p>
                <label className="block text-xs">{t("bloodBank.donor.weightKg")}
                  <input aria-label={t("bloodBank.donor.weightKg")} type="number" min="30" max="200" step="0.1" required value={weight} onChange={(e) => setWeight(e.target.value)} />
                </label>
                <label className="block text-xs">{t("bloodBank.donor.hemoglobin")}
                  <input aria-label={t("bloodBank.donor.hemoglobin")} type="number" min="5" max="25" step="0.1" required value={hemoglobin} onChange={(e) => setHemoglobin(e.target.value)} />
                </label>
                <label className="block text-xs">{t("bloodBank.donor.lastDonationHint")}
                  <input type="date" value={lastDonation} onChange={(e) => setLastDonation(e.target.value)} />
                </label>
                <label className="block text-xs">{t("bloodBank.donor.screeningNotes")}
                  <input value={ineligibilityReason} onChange={(e) => setIneligibilityReason(e.target.value)} />
                </label>
              </div>

              </fieldset>
              <div className="flex items-center justify-end gap-3 pt-4 border-t border-border">
                <button
                  type="button"
                  onClick={() => setIsRegisterModalOpen(false)}
                  disabled={isSubmitting || write.retryPending}
                  className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-muted-foreground hover:bg-muted transition-colors"
                >
                  {t("common.cancel")}
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  <CheckCircle2 className="h-4 w-4" />
                  {isSubmitting
                    ? t("bloodBank.donor.registering")
                    : write.retryPending
                      ? t("forms.renderer.retrySave")
                      : t("bloodBank.donor.saveDonor")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
