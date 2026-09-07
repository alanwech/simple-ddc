# Changelog

## [Latest] - 2026-09-07

### Added
- **Contrast Control** — New slider for VCP 0x12 (contrast) alongside brightness
- **Thread Safety** — Per-monitor `_is_refreshing` guard prevents overlapping refresh threads
- **Wider UI** — Window expanded from 640×440 to 800×480 for better layout
- **Better Parsing** — Fixed "Unknown" monitor names by parsing brief `ddcutil detect` output
- **Visual Improvements** — Added connector info badge, cleaner control rows, darker theme

### Fixed
- **Lag Issues** — Eliminated thread pile-up by preventing concurrent refresh cycles
  - Increased refresh interval from 5s to 10s
  - Added `try/finally` to guarantee `_is_refreshing` resets
- **Monitor Name Detection** — Now parses both verbose and brief `ddcutil detect` formats
- **Contrast Handling** — Shows "n/a" for monitors without VCP 0x12 support

### Changed
- REFRESH_RATE: 5000ms → 10000ms (10 seconds)
- DEBOUNCING_DELAY: 500ms → 300ms (faster slider response)
- Window size: 640×440 → 800×480
- Auto-refresh checkbox label: "Auto-refresh (5s)" → "Auto-refresh (10s)"

### Technical Details
- Added `time` import for future timestamp tracking
- Improved VCP feature handling with separate per-feature debouncing
- Added `get_vcp_text()` for raw feature output parsing
- Enhanced error handling in refresh cycles

## [Initial] - First release

- DDC/CI monitor detection and listing
- Real-time brightness control with slider
- Auto-refresh with toggle
- Collapsible details panel per monitor
- Zero pip dependencies (tkinter only)
- Fedora-focused installation instructions
- Desktop app launcher integration
