import * as React from "react";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TableSortLabel from "@mui/material/TableSortLabel";
import TablePagination from "@mui/material/TablePagination";
import Paper from "@mui/material/Paper";
import Box from "@mui/material/Box";
import Skeleton from "@mui/material/Skeleton";
import Typography from "@mui/material/Typography";
import { meridian } from "@/styles/theme";
import { useLocale } from "@/lib/i18n";

export interface DataTableColumn<T> {
  /** Unique key. If it matches a key on T, sorting works automatically. */
  key: string;
  label: string;
  /** Custom cell renderer. If omitted, falls back to row[key]. */
  render?: (row: T) => React.ReactNode;
  sortable?: boolean;
  align?: "left" | "center" | "right";
  width?: number | string;
}

export interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  rows: T[];
  /** Unique id per row, used for React keys — required so partial re-renders don't misplace rows */
  getRowId: (row: T) => string | number;
  loading?: boolean;
  emptyMessage?: string;
  onRowClick?: (row: T) => void;
  /** Highlights the active row when set (e.g. doctor queue selection). */
  selectedRowId?: string | number | null;

  /** Pagination — omit all three to render an unpaginated table */
  page?: number;
  rowsPerPage?: number;
  totalCount?: number;
  onPageChange?: (page: number) => void;
  onRowsPerPageChange?: (rowsPerPage: number) => void;
  rowsPerPageOptions?: number[];
}

/**
 * Shared table for every list screen (doctor queue, order lists, prescription
 * queue, patient search, etc). Supports two modes:
 *
 *  1. Simple: pass `rows` only -> renders everything, no pagination.
 *  2. Paginated: pass `page`, `rowsPerPage`, `totalCount`, `onPageChange` ->
 *     you fetch the correct page from the API yourself; this component
 *     stays presentation-only and never mutates your data.
 *
 * Sorting is client-side over the `rows` you pass in. If you're using
 * server-side pagination, sort on the server and just pass rows in order.
 */
export function DataTable<T>({
  columns,
  rows,
  getRowId,
  loading = false,
  emptyMessage = "No records found.",
  onRowClick,
  selectedRowId = null,
  page,
  rowsPerPage,
  totalCount,
  onPageChange,
  onRowsPerPageChange,
  rowsPerPageOptions = [10, 25, 50],
}: DataTableProps<T>) {
  const { t } = useLocale();
  const [sortKey, setSortKey] = React.useState<string | null>(null);
  const [sortDir, setSortDir] = React.useState<"asc" | "desc">("asc");

  const isPaginated =
    page !== undefined && rowsPerPage !== undefined && totalCount !== undefined;

  const sortedRows = React.useMemo(() => {
    if (!sortKey) return rows;
    const copy = [...rows];
    copy.sort((a, b) => {
      const av = (a as Record<string, unknown>)[sortKey];
      const bv = (b as Record<string, unknown>)[sortKey];
      if (av == null && bv == null) return 0;
      if (av == null) return -1;
      if (bv == null) return 1;

      if (typeof av === "number" && typeof bv === "number") {
        return sortDir === "asc" ? av - bv : bv - av;
      }
      const aStr = String(av);
      const bStr = String(bv);
      const cmp = aStr.localeCompare(bStr);
      return sortDir === "asc" ? cmp : -cmp;
    });
    return copy;
  }, [rows, sortKey, sortDir]);

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  };

  return (
    <Paper
      elevation={0}
      sx={{
        width: "100%",
        overflow: "hidden",
        borderRadius: "16px",
        border: `1px solid ${meridian.border}`,
        background: `linear-gradient(180deg, ${meridian.surface} 0%, #fbfcfe 100%)`,
        boxShadow:
          "0 1px 2px rgb(0 31 84 / 0.04), 0 12px 32px rgb(0 31 84 / 0.06)",
      }}
    >
      <TableContainer sx={{ maxHeight: 640 }}>
        <Table stickyHeader size="small" aria-label={t("common.ui.dataTable")}>
          <TableHead>
            <TableRow>
              {columns.map((col) => (
                <TableCell
                  key={col.key}
                  align={col.align ?? "left"}
                  sx={{
                    width: col.width,
                    backgroundColor: meridian.muted,
                    borderBottom: `1px solid ${meridian.border}`,
                    color: meridian.textSecondary,
                    fontWeight: 700,
                    fontSize: "0.6875rem",
                    letterSpacing: "0.06em",
                    textTransform: "uppercase",
                    fontFamily:
                      'var(--font-ibm-plex-sans), "IBM Plex Sans", system-ui, sans-serif',
                    py: 1.5,
                    px: 2,
                  }}
                >
                  {col.sortable ? (
                    <TableSortLabel
                      active={sortKey === col.key}
                      direction={sortKey === col.key ? sortDir : "asc"}
                      onClick={() => handleSort(col.key)}
                      sx={{
                        color: "inherit !important",
                        "& .MuiTableSortLabel-icon": {
                          color: `${meridian.brandPrimary} !important`,
                        },
                      }}
                    >
                      {col.label}
                    </TableSortLabel>
                  ) : (
                    col.label
                  )}
                </TableCell>
              ))}
            </TableRow>
          </TableHead>

          <TableBody>
            {loading &&
              Array.from({ length: rowsPerPage ?? 5 }).map((_, i) => (
                <TableRow key={`skeleton-${i}`}>
                  {columns.map((col) => (
                    <TableCell key={col.key} sx={{ px: 2, py: 1.5 }}>
                      <Skeleton variant="text" />
                    </TableCell>
                  ))}
                </TableRow>
              ))}

            {!loading && sortedRows.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={columns.length}
                  align="center"
                  sx={{ py: 6, px: 2 }}
                >
                  <Typography
                    variant="body2"
                    sx={{ color: meridian.textSecondary, fontWeight: 500 }}
                  >
                    {emptyMessage}
                  </Typography>
                </TableCell>
              </TableRow>
            )}

            {!loading &&
              sortedRows.map((row) => {
                const rowId = getRowId(row);
                const isSelected = selectedRowId != null && rowId === selectedRowId;
                return (
                  <TableRow
                    key={rowId}
                    hover={!!onRowClick}
                    selected={isSelected}
                    onClick={() => onRowClick?.(row)}
                    sx={{
                      cursor: onRowClick ? "pointer" : "default",
                      "&:last-child td": { borderBottom: 0 },
                      backgroundColor: isSelected ? "rgb(0 31 84 / 0.06)" : undefined,
                      "&:hover td": onRowClick
                        ? {
                            backgroundColor: isSelected
                              ? "rgb(0 31 84 / 0.08)"
                              : "rgb(0 31 84 / 0.03)",
                          }
                        : undefined,
                    }}
                  >
                    {columns.map((col) => (
                      <TableCell
                        key={col.key}
                        align={col.align ?? "left"}
                        sx={{
                          px: 2,
                          py: 1.6,
                          borderBottom: `1px solid rgb(0 31 84 / 0.06)`,
                          color: meridian.textPrimary,
                          fontSize: "0.875rem",
                          fontWeight: 500,
                          whiteSpace: "nowrap",
                          verticalAlign: "middle",
                        }}
                      >
                        {col.render
                          ? col.render(row)
                          : String((row as Record<string, unknown>)[col.key] ?? "—")}
                      </TableCell>
                    ))}
                  </TableRow>
                );
              })}
          </TableBody>
        </Table>
      </TableContainer>

      {isPaginated && (
        <Box
          sx={{
            borderTop: `1px solid ${meridian.border}`,
            backgroundColor: "rgb(244 246 249 / 0.65)",
          }}
        >
          <TablePagination
            component="div"
            count={totalCount!}
            page={page!}
            rowsPerPage={rowsPerPage!}
            rowsPerPageOptions={rowsPerPageOptions}
            onPageChange={(_, newPage) => onPageChange?.(newPage)}
            onRowsPerPageChange={(e) =>
              onRowsPerPageChange?.(parseInt(e.target.value, 10))
            }
            sx={{
              color: meridian.textSecondary,
              overflow: "hidden",
              "& .MuiToolbar-root": {
                flexWrap: "wrap",
                gap: 1,
                minHeight: 56,
                px: 2,
              },
              "& .MuiTablePagination-selectLabel, & .MuiTablePagination-displayedRows":
                {
                  fontSize: "0.8125rem",
                  fontWeight: 500,
                  margin: 0,
                },
              "& .MuiTablePagination-input": {
                marginRight: 2,
                marginLeft: 1,
              },
              "& .MuiTablePagination-select": {
                borderRadius: "8px",
                border: `1px solid ${meridian.border}`,
                backgroundColor: meridian.surface,
                paddingRight: "24px !important",
              },
              "& .MuiTablePagination-actions": {
                marginLeft: 1.5,
              },
              "& .MuiIconButton-root": {
                color: meridian.brandPrimary,
                borderRadius: "8px",
              },
            }}
          />
        </Box>
      )}
    </Paper>
  );
}
