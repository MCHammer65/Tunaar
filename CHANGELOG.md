# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/).
Each version section drives the GitHub Release notes + announcement drafts.

## [Unreleased]

### Added
- (your changes here)

## [0.11.0] - 2026-06-27
### Added
- Autopilot feature-request queue: in-app Feedback widget files GitHub issues; approve-before-build gate.
- Self-healing scaffolding: nightly self-test and Dependabot raise auto-fix issues; agent opens fix PRs on review.
- Channel logo embedding and EPG timezone hygiene in the served guide.
- Security headers and management-API rate limiting.
- Installable PWA dashboard with an offline shell.
- Multi-source stream failover (alternate providers of the same channel).
- Targeted SSRF guard on outbound fetches (allows LAN, blocks cloud metadata).
- VPN-egress deployment docs.

## [0.10.0] - 2026-06-27
### Added
- Portable Autopilot feedback module and in-app capture.

## [0.9.0] - 2026-06-27
### Added
- Full Lemon Squeezy licensing lifecycle: 30-day trial, nag, basic-tier lockdown, 14-day renewal grace.
- NAS deployment guides (Synology, QNAP, Unraid, TrueNAS, Portainer) and a /readyz endpoint.
- Native Jellyfin and Emby support, guaranteed guide match, duplicate-description fix, stream auto-reconnect.
