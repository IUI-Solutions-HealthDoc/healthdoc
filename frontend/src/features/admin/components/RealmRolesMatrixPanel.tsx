"use client";

import { useMemo, useState } from "react";
import CheckIcon from "@mui/icons-material/Check";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";

import { meridian } from "@/styles/theme";
import {
  MATRIX_CAPABILITIES,
  MATRIX_CAPABILITY_LABELS,
  REALM_ROLES,
  REALM_ROLE_LABELS,
  ROLE_CAPABILITY_MAP,
} from "../constants";
import { adminPanelSx } from "../panelSx";
import type { RealmRole } from "../types";

const STICKY_BG = "#fbfcfe";

export function RealmRolesMatrixPanel() {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<RealmRole | null>("doctor");

  const filteredRoles = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return REALM_ROLES;
    return REALM_ROLES.filter((role) => {
      const label = REALM_ROLE_LABELS[role].toLowerCase();
      return label.includes(q) || role.includes(q);
    });
  }, [query]);

  const selectedCaps = selected ? ROLE_CAPABILITY_MAP[selected] : [];

  return (
    <Box sx={adminPanelSx}>
      <Typography
        sx={{ m: 0, fontSize: "1.0625rem", fontWeight: 700, color: meridian.textPrimary }}
      >
        Role permissions
      </Typography>
      <Typography sx={{ m: 0, mt: 0.5, mb: 2, fontSize: "0.8125rem", color: meridian.textSecondary }}>
        Review what each application role is allowed to access. Assignments are managed from staff accounts.
      </Typography>

      <Stack
        direction={{ xs: "column", sm: "row" }}
        spacing={1.5}
        sx={{ mb: 2, alignItems: { sm: "center" }, justifyContent: "space-between" }}
      >
        <TextField
          size="small"
          placeholder="Filter roles…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          sx={{ width: { xs: "100%", sm: 260 } }}
        />
        <Box
          sx={{
            px: 1.5,
            py: 1,
            borderRadius: "10px",
            border: `1px solid ${meridian.warning}44`,
            bgcolor: "rgba(180, 83, 9, 0.08)",
            maxWidth: 420,
          }}
        >
          <Typography sx={{ m: 0, fontSize: "0.75rem", color: meridian.warning, fontWeight: 600 }}>
            Platform administrators manage facilities only and cannot access clinical records.
          </Typography>
        </Box>
      </Stack>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", lg: "1fr 280px" },
          gap: 2,
          alignItems: "start",
        }}
      >
        <TableContainer
          sx={{
            maxHeight: 480,
            borderRadius: "12px",
            border: `1px solid ${meridian.border}`,
          }}
        >
          <Table stickyHeader size="small" sx={{ minWidth: 960 }}>
            <TableHead>
              <TableRow>
                <TableCell
                  sx={{
                    position: "sticky",
                    left: 0,
                    zIndex: 3,
                    bgcolor: STICKY_BG,
                    fontWeight: 700,
                    fontSize: "0.6875rem",
                    letterSpacing: "0.04em",
                    textTransform: "uppercase",
                    color: meridian.textSecondary,
                    borderBottom: `1px solid ${meridian.border}`,
                  }}
                >
                  Role
                </TableCell>
                {MATRIX_CAPABILITIES.map((cap) => (
                  <TableCell
                    key={cap}
                    align="center"
                    sx={{
                      bgcolor: STICKY_BG,
                      fontWeight: 700,
                      fontSize: "0.6875rem",
                      color: meridian.textSecondary,
                      whiteSpace: "nowrap",
                      px: 0.75,
                      borderBottom: `1px solid ${meridian.border}`,
                    }}
                  >
                    <Tooltip title={MATRIX_CAPABILITY_LABELS[cap]} arrow>
                      <span>{MATRIX_CAPABILITY_LABELS[cap]}</span>
                    </Tooltip>
                  </TableCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {filteredRoles.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={MATRIX_CAPABILITIES.length + 1}>
                    <Typography sx={{ py: 2, color: meridian.textSecondary, fontSize: "0.875rem" }}>
                      No roles match this filter.
                    </Typography>
                  </TableCell>
                </TableRow>
              ) : (
                filteredRoles.map((role) => {
                  const caps = new Set(ROLE_CAPABILITY_MAP[role]);
                  const isSelected = role === selected;
                  return (
                    <TableRow
                      key={role}
                      hover
                      selected={isSelected}
                      onClick={() => setSelected(role)}
                      sx={{
                        cursor: "pointer",
                        bgcolor: isSelected ? "#e8eef5" : undefined,
                        "& td": {
                          borderColor: "rgb(0 31 84 / 0.08)",
                        },
                      }}
                    >
                      <TableCell
                        sx={{
                          position: "sticky",
                          left: 0,
                          zIndex: 1,
                          bgcolor: isSelected ? "#e8eef5" : STICKY_BG,
                          fontWeight: 600,
                          color: meridian.textPrimary,
                          whiteSpace: "nowrap",
                          borderLeft: isSelected
                            ? `3px solid ${meridian.brandPrimary}`
                            : "3px solid transparent",
                        }}
                      >
                        <Typography sx={{ m: 0, fontWeight: 700, fontSize: "0.8125rem" }}>
                          {REALM_ROLE_LABELS[role]}
                        </Typography>
                        <Typography
                          sx={{
                            m: 0,
                            fontSize: "0.6875rem",
                            fontFamily: "var(--font-ibm-plex-mono), monospace",
                            color: meridian.textSecondary,
                          }}
                        >
                          {role}
                        </Typography>
                      </TableCell>
                      {MATRIX_CAPABILITIES.map((cap) => {
                        const on = caps.has(cap);
                        return (
                          <TableCell key={cap} align="center" sx={{ px: 0.5 }}>
                            {on ? (
                              <Box
                                sx={{
                                  display: "inline-flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  width: 22,
                                  height: 22,
                                  borderRadius: "6px",
                                  bgcolor: "rgba(0, 31, 84, 0.1)",
                                  color: meridian.brandPrimary,
                                }}
                              >
                                <CheckIcon sx={{ fontSize: 14 }} />
                              </Box>
                            ) : (
                              <Typography
                                component="span"
                                sx={{ color: meridian.border, fontSize: "0.875rem" }}
                              >
                                —
                              </Typography>
                            )}
                          </TableCell>
                        );
                      })}
                    </TableRow>
                  );
                })
              )}
            </TableBody>
          </Table>
        </TableContainer>

        <Box
          sx={{
            borderRadius: "14px",
            border: `1px solid ${meridian.border}`,
            background: `linear-gradient(180deg, ${meridian.surface} 0%, #fbfcfe 100%)`,
            p: 2,
            minHeight: 200,
            position: { lg: "sticky" },
            top: { lg: 16 },
          }}
        >
          {selected ? (
            <>
              <Typography
                sx={{
                  m: 0,
                  fontSize: "0.6875rem",
                  fontWeight: 700,
                  letterSpacing: "0.06em",
                  textTransform: "uppercase",
                  color: meridian.textSecondary,
                }}
              >
                Role detail
              </Typography>
              <Typography
                sx={{
                  m: 0,
                  mt: 0.75,
                  fontSize: "1.0625rem",
                  fontWeight: 700,
                  color: meridian.textPrimary,
                }}
              >
                {REALM_ROLE_LABELS[selected]}
              </Typography>
              <Typography
                sx={{
                  m: 0,
                  mt: 0.35,
                  mb: 1.5,
                  fontSize: "0.75rem",
                  fontFamily: "var(--font-ibm-plex-mono), monospace",
                  color: meridian.brandPrimary,
                  fontWeight: 600,
                }}
              >
                {selected}
              </Typography>

              {selected === "superadmin" ? (
                <Typography
                  sx={{
                    m: 0,
                    mb: 1.5,
                    fontSize: "0.75rem",
                    color: meridian.warning,
                    fontWeight: 600,
                  }}
                >
                  Governance role — not for clinical workflows.
                </Typography>
              ) : null}

              <Typography
                sx={{
                  m: 0,
                  mb: 1,
                  fontSize: "0.6875rem",
                  fontWeight: 700,
                  letterSpacing: "0.04em",
                  textTransform: "uppercase",
                  color: meridian.textSecondary,
                }}
              >
                Capabilities ({selectedCaps.length})
              </Typography>
              <Stack direction="row" useFlexGap sx={{ flexWrap: "wrap", gap: 0.75, mb: 2 }}>
                {selectedCaps.map((cap) => (
                  <Chip
                    key={cap}
                    size="small"
                    label={MATRIX_CAPABILITY_LABELS[cap]}
                    sx={{
                      fontWeight: 600,
                      height: 26,
                      bgcolor: "#e8eef5",
                      color: meridian.brandPrimary,
                      border: `1px solid rgb(0 31 84 / 0.14)`,
                    }}
                  />
                ))}
              </Stack>
              <Typography sx={{ m: 0, fontSize: "0.75rem", color: meridian.textSecondary, lineHeight: 1.45 }}>
                This is a read-only permission reference. Assign roles from the staff account workflow.
              </Typography>
            </>
          ) : (
            <Typography sx={{ color: meridian.textSecondary, fontSize: "0.875rem" }}>
              Select a role row to see its capability list.
            </Typography>
          )}
        </Box>
      </Box>
    </Box>
  );
}
