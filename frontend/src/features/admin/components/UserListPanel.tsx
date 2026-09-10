"use client";

import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { meridian } from "@/styles/theme";
import { adminPanelSx } from "../panelSx";
import type { User } from "../types";
import { ActiveStatusChip } from "./ActiveStatusChip";

type Props = {
  users: User[];
  loading: boolean;
  query: string;
  activeFilter: boolean | null;
  selectedId: string | null;
  onQueryChange: (q: string) => void;
  onActiveFilterChange: (v: boolean | null) => void;
  onSelect: (id: string) => void;
};

export function UserListPanel({
  users,
  loading,
  query,
  activeFilter,
  selectedId,
  onQueryChange,
  onActiveFilterChange,
  onSelect,
}: Props) {
  const filterValue =
    activeFilter === null ? "all" : activeFilter ? "active" : "inactive";

  const [page, setPage] = useState(1);
  const PAGE_SIZE = 8;

  // Reset to page 1 on search or filter change
  useEffect(() => {
    setPage(1);
  }, [query, activeFilter]);

  const totalPages = Math.max(1, Math.ceil(users.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const paginatedUsers = users.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  return (
    <Box
      sx={{
        ...adminPanelSx,
        p: 0,
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        minHeight: 480,
        height: "100%",
      }}
    >
      <Box sx={{ px: 2.5, pt: 2.25, pb: 1.75 }}>
        <Typography
          sx={{
            m: 0,
            fontSize: "1.0625rem",
            fontWeight: 700,
            color: meridian.textPrimary,
            letterSpacing: "-0.02em",
          }}
        >
          Staff Directory
        </Typography>
        <Typography sx={{ m: 0, mt: 0.4, fontSize: "0.8125rem", color: meridian.textSecondary }}>
          Search and manage staff profiles for this facility ({users.length} total).
        </Typography>
      </Box>

      <Stack spacing={1.25} sx={{ px: 2.5, pb: 2 }}>
        <TextField
          size="small"
          placeholder="Search username, name, employee ID…"
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
        />
        <TextField
          select
          size="small"
          label="Status"
          value={filterValue}
          onChange={(e) => {
            const v = e.target.value;
            onActiveFilterChange(v === "all" ? null : v === "active");
          }}
        >
          <MenuItem value="all">All</MenuItem>
          <MenuItem value="active">Active</MenuItem>
          <MenuItem value="inactive">Inactive</MenuItem>
        </TextField>
      </Stack>

      <Box sx={{ flex: 1, overflowY: "auto", borderTop: `1px solid ${meridian.border}`, maxHeight: 460 }}>
        {loading ? (
          <Typography sx={{ p: 2.5, fontSize: "0.875rem", color: meridian.textSecondary }}>
            Loading staff profiles…
          </Typography>
        ) : paginatedUsers.length === 0 ? (
          <Typography sx={{ p: 2.5, fontSize: "0.875rem", color: meridian.textSecondary }}>
            No users found.
          </Typography>
        ) : (
          paginatedUsers.map((u) => {
            const selected = u.id === selectedId;
            return (
              <Box
                key={u.id}
                component="button"
                type="button"
                onClick={() => onSelect(u.id)}
                sx={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  border: 0,
                  borderBottom: `1px solid ${meridian.border}`,
                  borderLeft: selected
                    ? `3px solid ${meridian.brandPrimary}`
                    : "3px solid transparent",
                  cursor: "pointer",
                  px: 2.5,
                  py: 1.5,
                  backgroundColor: selected ? "#e8eef5" : "transparent",
                  transition: "background-color 120ms ease, border-color 120ms ease",
                  "&:hover": { backgroundColor: selected ? "#e8eef5" : meridian.muted },
                }}
              >
                <Stack direction="row" sx={{ justifyContent: "space-between", gap: 1 }}>
                  <Box sx={{ minWidth: 0 }}>
                    <Typography
                      sx={{
                        m: 0,
                        fontSize: "0.9375rem",
                        fontWeight: 600,
                        color: meridian.textPrimary,
                      }}
                    >
                      {u.full_name}
                    </Typography>
                    <Typography
                      sx={{
                        m: 0,
                        mt: 0.35,
                        fontSize: "0.75rem",
                        fontFamily: "var(--font-ibm-plex-mono), monospace",
                        color: meridian.brandPrimary,
                      }}
                    >
                      {u.username}
                    </Typography>
                  </Box>
                  <ActiveStatusChip active={u.is_active} />
                </Stack>
              </Box>
            );
          })
        )}
      </Box>

      {/* Pagination Footer */}
      {users.length > PAGE_SIZE && (
        <Box
          sx={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            px: 2,
            py: 1.5,
            borderTop: `1px solid ${meridian.border}`,
            bgcolor: "#fafbfc",
          }}
        >
          <Typography sx={{ fontSize: "0.75rem", color: meridian.textSecondary }}>
            Page {currentPage} of {totalPages}
          </Typography>
          <Stack direction="row" spacing={1}>
            <button
              type="button"
              disabled={currentPage <= 1}
              onClick={() => setPage((p: number) => Math.max(1, p - 1))}
              style={{
                padding: "4px 10px",
                fontSize: "0.75rem",
                borderRadius: "6px",
                border: `1px solid ${meridian.border}`,
                backgroundColor: "#fff",
                cursor: currentPage <= 1 ? "not-allowed" : "pointer",
                opacity: currentPage <= 1 ? 0.5 : 1,
              }}
            >
              Prev
            </button>
            <button
              type="button"
              disabled={currentPage >= totalPages}
              onClick={() => setPage((p: number) => Math.min(totalPages, p + 1))}
              style={{
                padding: "4px 10px",
                fontSize: "0.75rem",
                borderRadius: "6px",
                border: `1px solid ${meridian.border}`,
                backgroundColor: "#fff",
                cursor: currentPage >= totalPages ? "not-allowed" : "pointer",
                opacity: currentPage >= totalPages ? 0.5 : 1,
              }}
            >
              Next
            </button>
          </Stack>
        </Box>
      )}
    </Box>
  );
}
