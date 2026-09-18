"use client";

import { useEffect, useState } from "react";

import { getPatientPhoto } from "@/features/receptionist/api";

export interface PatientAvatarProps {
  patientId?: string;
  photoFileId?: string | null;
  photoUrl?: string | null;
  name: string;
  size?: "xs" | "sm" | "md" | "lg" | "xl";
  className?: string;
}

const SIZE_CLASSES = {
  xs: "w-6 h-6 text-[10px]",
  sm: "w-8 h-8 text-xs",
  md: "w-10 h-10 text-sm",
  lg: "w-14 h-14 text-base",
  xl: "w-20 h-20 text-xl font-bold",
};

function getInitials(name: string): string {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function PatientAvatar({
  patientId,
  photoFileId,
  photoUrl,
  name,
  size = "md",
  className = "",
}: PatientAvatarProps) {
  const [imgSrc, setImgSrc] = useState<string | null>(photoUrl ?? null);
  const [loadFailed, setLoadFailed] = useState(false);

  useEffect(() => {
    if (photoUrl) {
      setImgSrc(photoUrl);
      setLoadFailed(false);
      return;
    }
    if (!photoFileId || !patientId) {
      setImgSrc(null);
      return;
    }

    let isMounted = true;
    getPatientPhoto(patientId)
      .then((res) => {
        if (isMounted && res.download_url) {
          setImgSrc(res.download_url);
          setLoadFailed(false);
        }
      })
      .catch(() => {
        if (isMounted) setLoadFailed(true);
      });

    return () => {
      isMounted = false;
    };
  }, [patientId, photoFileId, photoUrl]);

  const sizeClass = SIZE_CLASSES[size] ?? SIZE_CLASSES.md;
  const initials = getInitials(name);

  if (imgSrc && !loadFailed) {
    return (
      <div
        className={`relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full border border-border/60 bg-muted ${sizeClass} ${className}`}
      >
        <img
          src={imgSrc}
          alt={`Photo of ${name}`}
          className="h-full w-full object-cover"
          onError={() => setLoadFailed(true)}
        />
      </div>
    );
  }

  return (
    <div
      aria-label={name}
      className={`inline-flex shrink-0 select-none items-center justify-center rounded-full bg-primary/10 font-semibold text-primary border border-primary/20 ${sizeClass} ${className}`}
    >
      {initials}
    </div>
  );
}

export default PatientAvatar;
