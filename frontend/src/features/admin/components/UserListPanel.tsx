"use client";

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

  return (
    <Box
      sx={{
        ...adminPanelSx,
        p: 0,
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        minHeight: 420,
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
          Directory
        </Typography>
        <Typography sx={{ m: 0, mt: 0.4, fontSize: "0.8125rem", color: meridian.textSecondary }}>
          Search and manage staff accounts for this facility.
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

      <Box sx={{ flex: 1, overflowY: "auto", borderTop: `1px solid ${meridian.border}`, maxHeight: 520 }}>
        {loading ? (
          <Typography sx={{ p: 2.5, fontSize: "0.875rem", color: meridian.textSecondary }}>
            Loading…
          </Typography>
        ) : users.length === 0 ? (
          <Typography sx={{ p: 2.5, fontSize: "0.875rem", color: meridian.textSecondary }}>
            No users found.
          </Typography>
        ) : (
          users.map((u) => {
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
    </Box>
  );
}
