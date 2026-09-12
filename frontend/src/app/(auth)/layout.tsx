import { ShieldCheck, Activity, Award, Lock } from "lucide-react";
import { HealthDocBrand } from "@/components/common/HealthDocBrand";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col lg:flex-row bg-background">
      {/* Brand & Security Showcase Banner (Visible on lg screens) */}
      <div className="relative hidden lg:flex lg:w-1/2 xl:w-7/12 flex-col justify-between overflow-hidden bg-gradient-to-br from-[#001F54] via-[#0A2540] to-[#001536] p-12 text-white">
        {/* Ambient subtle glow circles */}
        <div className="pointer-events-none absolute -left-20 -top-20 h-96 w-96 rounded-full bg-blue-500/10 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-20 -right-20 h-96 w-96 rounded-full bg-cyan-500/10 blur-3xl" />

        <div className="relative z-10">
          <HealthDocBrand
            size={52}
            preload
            subtitle="Hospital Information Management System"
            nameClassName="text-2xl font-bold tracking-wide text-white"
            className="text-white"
          />
        </div>

        <div className="relative z-10 my-auto max-w-xl space-y-6">
          <div className="inline-flex items-center gap-2 rounded-full border border-blue-400/30 bg-blue-500/10 px-3.5 py-1 text-xs font-medium tracking-wide text-blue-200 backdrop-blur-sm">
            <span className="flex h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
            Enterprise Clinical Operations Platform
          </div>

          <h2 className="text-3xl xl:text-4xl font-bold tracking-tight text-white leading-tight">
            Integrated Clinical, Diagnostic & Administrative Excellence
          </h2>

          <p className="text-sm xl:text-base leading-relaxed text-blue-100/80">
            Streamlining outpatient consultations, inpatient bed telemetry, verified diagnostic reporting, and digital health records under unified ABDM standards.
          </p>

          <div className="grid grid-cols-2 gap-4 pt-4">
            <div className="rounded-xl border border-white/10 bg-white/5 p-4 backdrop-blur-sm transition hover:bg-white/10">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-500/20 text-blue-300">
                  <ShieldCheck className="h-5 w-5" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-white">ABDM M1, M2 & M3</h3>
                  <p className="text-xs text-blue-200/70">Ayushman Bharat Digital Mission</p>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-white/10 bg-white/5 p-4 backdrop-blur-sm transition hover:bg-white/10">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/20 text-emerald-300">
                  <Lock className="h-5 w-5" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-white">DPDP Act 2023</h3>
                  <p className="text-xs text-blue-200/70">Immutable audit & consent compliance</p>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-white/10 bg-white/5 p-4 backdrop-blur-sm transition hover:bg-white/10">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-purple-500/20 text-purple-300">
                  <Activity className="h-5 w-5" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-white">Real-Time eMAR</h3>
                  <p className="text-xs text-blue-200/70">Telemetry, wards & closed-loop dispensing</p>
                </div>
              </div>
            </div>

            <div className="rounded-xl border border-white/10 bg-white/5 p-4 backdrop-blur-sm transition hover:bg-white/10">
              <div className="flex items-center gap-3">
                <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-cyan-500/20 text-cyan-300">
                  <Award className="h-5 w-5" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-white">DICOM PACS</h3>
                  <p className="text-xs text-blue-200/70">Full Orthanc imaging & diagnostics</p>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="relative z-10 flex items-center justify-between border-t border-white/10 pt-6 text-xs text-blue-200/60">
          <span>HealthDoc Clinical Suite v2.4</span>
          <span>End-to-End FIPS 140-3 Encryption</span>
        </div>
      </div>

      {/* Right Column: Interactive Login Container */}
      <div className="flex flex-1 items-center justify-center p-6 sm:p-12">
        <div className="w-full max-w-md">{children}</div>
      </div>
    </div>
  );
}

