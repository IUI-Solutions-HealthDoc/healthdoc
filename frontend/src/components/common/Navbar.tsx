"use client";

import { Menu, LogOut, User } from "lucide-react";
import { meridian } from "@/styles/theme";
import { REALM_ROLE_LABELS } from "@/features/admin/constants";
import { useAuth } from "@/providers/auth-provider";
import { HealthDocBrand } from "./HealthDocBrand";

interface NavbarProps {
  open: boolean;
  setOpen: React.Dispatch<React.SetStateAction<boolean>>;
}

export default function Navbar({ open, setOpen }: NavbarProps) {
  const { user, logout } = useAuth();
  const roleLabel = user?.role
    ? (REALM_ROLE_LABELS[user.role] ?? user.role)
    : "Unassigned";

  return (
    <header
      className="fixed top-0 left-0 right-0 z-50 flex h-16 items-center justify-between border-b px-6"
      style={{
        backgroundColor: meridian.surface,
        borderColor: meridian.border,
        boxShadow: "0 1px 2px rgb(0 31 84 / 0.04)",
      }}
    >
      <div className="flex items-center gap-4">
        <button
          type="button"
          onClick={() => setOpen((prev) => !prev)}
          className="rounded-lg p-2 transition-colors"
          style={{ color: meridian.textPrimary }}
          aria-label="Toggle menu"
          aria-controls="workspace-sidebar"
          aria-expanded={open}
        >
          <Menu size={22} />
        </button>

        <HealthDocBrand
          size={40}
          preload
          subtitle="HMIS"
          nameClassName="text-lg"
          className="text-[#001F54]"
        />
      </div>

      <div className="flex items-center gap-4" style={{ color: meridian.textSecondary }}>
        <div className="flex items-center gap-2">
          <div
            className="flex h-9 w-9 items-center justify-center rounded-full text-white"
            style={{ backgroundColor: meridian.brandPrimary }}
          >
            <User size={18} />
          </div>
          <div>
            <p className="font-medium" style={{ color: meridian.textPrimary }}>
              {user?.name || roleLabel}
            </p>
            <p className="text-xs" style={{ color: meridian.textSecondary }}>
              {roleLabel}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => void logout()}
          className="rounded-lg p-2 transition-colors hover:bg-slate-100"
          aria-label="Sign out"
          title="Sign out"
        >
          <LogOut size={18} />
        </button>
      </div>
    </header>
  );
}
