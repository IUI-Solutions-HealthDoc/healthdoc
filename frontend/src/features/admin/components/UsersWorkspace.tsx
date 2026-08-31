"use client";

import { useCallback, useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";
import Link from "next/link";

import { meridian } from "@/styles/theme";
import { useUserDetail } from "../hooks/useUserDetail";
import { useUserEditor } from "../hooks/useUserEditor";
import { useUsers } from "../hooks/useUsers";
import type { User } from "../types";
import { listDepartments, type Department } from "../api/departments";
import { AdminPageHeader } from "./AdminPageHeader";
import { CreateUserModal } from "./CreateUserModal";
import { UserListPanel } from "./UserListPanel";
import { UserProfileForm } from "./UserProfileForm";

export function UsersWorkspace() {
  const {
    users,
    loading: listLoading,
    error: listError,
    filters,
    setQuery,
    setActiveFilter,
    refresh: refreshList,
  } = useUsers();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [departments, setDepartments] = useState<Department[]>([]);

  useEffect(() => {
    let cancelled = false;
    void listDepartments()
      .then((response) => {
        if (!cancelled) setDepartments(response.items);
      })
      .catch(() => {
        if (!cancelled) setDepartments([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const { user, setUser, loading: detailLoading, error: detailError } = useUserDetail(selectedId);

  const onSaved = useCallback(
    (next: User) => {
      setUser(next);
      void refreshList();
    },
    [refreshList, setUser],
  );

  const editor = useUserEditor(user, onSaved);

  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 2.5 }}>
      <AdminPageHeader
        backHref="/admin"
        eyebrow="Admin"
        title="Users"
        subtitle="Create staff accounts and manage profiles and active access."
        actions={
          <>
            <Button
              component={Link}
              href="/admin/account-requests"
              variant="outlined"
              sx={{ textTransform: "none", fontWeight: 600, borderRadius: "10px" }}
            >
              Request account
            </Button>
            <Button
              variant="contained"
              color="primary"
              onClick={() => setCreateOpen(true)}
              sx={{
                textTransform: "none",
                fontWeight: 700,
                borderRadius: "10px",
                bgcolor: meridian.brandPrimary,
                color: "#ffffff",
                "&:hover": { bgcolor: meridian.brandDeep },
              }}
            >
              Add staff member
            </Button>
          </>
        }
      />

      {listError ? (
        <Typography role="alert" sx={{ color: meridian.danger, fontSize: "0.875rem" }}>
          {listError}
        </Typography>
      ) : null}

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", lg: "320px 1fr" },
          gap: 2.5,
          alignItems: "stretch",
        }}
      >
        <UserListPanel
          users={users}
          loading={listLoading}
          query={filters.query ?? ""}
          activeFilter={filters.is_active ?? null}
          selectedId={selectedId}
          onQueryChange={setQuery}
          onActiveFilterChange={setActiveFilter}
          onSelect={setSelectedId}
        />

        {!selectedId ? (
          <Box
            sx={{
              borderRadius: "16px",
              border: `1px dashed ${meridian.border}`,
              background: `linear-gradient(180deg, ${meridian.muted} 0%, #eef3f8 100%)`,
              p: 4,
              minHeight: 420,
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              textAlign: "center",
              gap: 1,
            }}
          >
            <Typography
              sx={{ m: 0, fontWeight: 700, fontSize: "1rem", color: meridian.textPrimary }}
            >
              No user selected
            </Typography>
            <Typography sx={{ m: 0, fontSize: "0.875rem", color: meridian.textSecondary, maxWidth: 320 }}>
              Pick someone from the list to view and edit their profile, or add a staff member.
            </Typography>
          </Box>
        ) : detailError ? (
          <Box
            role="alert"
            sx={{
              borderRadius: "16px",
              border: `1px solid ${meridian.border}`,
              p: 4,
              minHeight: 420,
              color: meridian.danger,
            }}
          >
            {detailError}
          </Box>
        ) : detailLoading || !editor.draft ? (
          <Box
            sx={{
              borderRadius: "16px",
              border: `1px solid ${meridian.border}`,
              p: 4,
              minHeight: 420,
              color: meridian.textSecondary,
            }}
          >
            Loading user…
          </Box>
        ) : (
          <UserProfileForm
            draft={editor.draft}
            busy={editor.busy}
            isDirty={editor.isDirty}
            errors={editor.errors}
            departments={departments}
            onChange={(key, value) => {
              if (
                key === "full_name" ||
                key === "email" ||
                key === "mobile" ||
                key === "designation" ||
                key === "employee_id" ||
                key === "registration_number" ||
                key === "qualification" ||
                key === "department_id"
              ) {
                editor.patchField(key, value === "" ? null : value);
              }
            }}
            onSave={() => void editor.save()}
            onToggleActive={() => void editor.toggleActive()}
          />
        )}
      </Box>

      <CreateUserModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(u) => {
          void refreshList();
          setSelectedId(u.id);
        }}
      />
    </Box>
  );
}
