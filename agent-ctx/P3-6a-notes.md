# P3 Task 6-a — Account sphere frontend (Team/Organization, Onboarding, Notifications, Preferences)

Date: 2025-11-11 · Agent: P3 frontend 6-a · Repo: /home/z/my-project

## Files created (exact ownership scope)

| File | Contents |
|---|---|
| `src/lib/api-p3-account.ts` | Typed fetch layer for all account-sphere endpoints. Mirrors `src/lib/api.ts` plumbing (relative URLs + `XTransformPort=3030`, HttpOnly-cookie auth, single 401→`refreshSession()` retry reusing the shared single-flight, `ApiError` from `./api`, `ApiErrorBody` from `./types`). 204 responses resolve `void`. Query-string builder skips null/undefined/empty. |
| `src/components/croptwist/p3/team-tab.tsx` | `export default function TeamTab()` + exported `CreateOrgDialog`, `roleLabelKey`, `formatRelativeTime` (shared with the bell/wizard). |
| `src/components/croptwist/p3/onboarding-wizard.tsx` | `export default function OnboardingWizard({ open, onOpenChange })` |
| `src/components/croptwist/p3/notifications-bell.tsx` | `export default function NotificationsBell()` (self-contained; also holds the preferences dialog). |
| `messages/en/p3.json`, `messages/ar/p3.json` | Namespace `p3`, prefixes `account.* team.* onboarding.* notifications.* preferences.*`. 198 keys, en/ar key sets identical, zero hardcoded strings in components (`common.cancel`/`common.noData` reused for shared labels). Arabic is professional agricultural-business Arabic; RTL-safe via logical utilities (`ms-/me-`, `text-start`, `-end-*`, `rtl:rotate-180`). |
| `agent-ctx/P3-6a-notes.md` | This file. |

## Endpoints used (verified against backend sources, not just the task text)

- `GET/POST /api/v1/orgs`, `GET/PATCH /api/v1/orgs/{id}` (org payloads carry `my_role`)
- `GET /api/v1/orgs/{id}/members`, `PATCH /api/v1/orgs/{id}/members/{user_id}` **body `{role_code}`** (task text said `{role}` — `MemberRolePatch` in `app/api/v1/orgs.py` is authoritative), `DELETE …/members/{user_id}` (204)
- `POST /api/v1/orgs/{id}/ownership-transfer` **body `{target_user_id}`**
- `POST/GET /api/v1/orgs/{id}/invitations` (create returns the plaintext `token` **once** — surfaced in an emerald alert with copy-to-clipboard; "deliver out-of-band" is stated in UI copy), `DELETE /api/v1/orgs/{id}/invitations/{invitation_id}` (204), `POST /api/v1/invitations/accept` `{token}`
- `GET /api/v1/orgs/{id}/activity?limit&offset` (TanStack `useInfiniteQuery`, page 10, Load more while `offset+len < total`)
- `GET /api/v1/onboarding/progress`, `POST /steps/{step}/complete` `{data?}`, `POST /skip/{step}`, `POST /account-type` `{account_type}`, `POST /dismiss` — step order/names from `app/onboarding/service.py` (`account, account_type, organization, org_profile, first_farm, first_field, crops_priorities, review, tour`; required flags drive what can be skipped)
- `GET /api/v1/notifications?unread_only&severity&category&limit&offset`, `POST /{id}/read` `{read}`, `POST /read-all`, `GET /unread-count`, `GET/PUT /api/v1/notifications/preferences` (`{category, in_app_enabled?, email_enabled?}`)
- `GET/PUT /api/v1/preferences` (locale, timezone, currency_code, unit_system, week_start, agricultural_calendar; `null` clears calendar)

## Types

All local to `api-p3-account.ts`: `Organization{Type}`, `OrgRoleCode` (7 roles) + `ORG_ROLE_RANK` + `roleAtLeast()` (mirrors backend `ROLE_ORDER`), `OrganizationMember`, `OrganizationInvitation{Status}`, `OwnershipTransferResponse`, `OrganizationActivityEvent`, `OnboardingProgress`/`StepState`, `NotificationItem`, `NotificationSeverity` = `info|advisory|warning|critical`, `NotificationCategory` (8), `NotificationPreferenceItem`, `UserPreferences`, `PreferencesUpdateInput`, list/response envelopes. Backend error envelope is `{error:{code,message,details,request_id}}` → mapped through the shared `ApiError`/`describeError` into friendly toasts; per-section queries render inline `Alert` + Retry.

## Component behavior highlights

- **TeamTab**: skeletons per section; empty state (why orgs matter: multi-farm collaboration, server-enforced roles, shared history) → Create dialog (name + RadioGroup individual/business/farm_org with one-line explanations); org selector when >1; org card with member count + inline rename (org_admin+, event-driven edit state — no state-sync effects, per `react-hooks/set-state-in-effect`); Members table on sm+, stacked cards below; role Select options respect backend grant policy (owner grants all 7; org_admin only manager↓) — UX gating only, server enforces; self rows show static badge, no self-removal; ownership transfer owner-only with typed-email AlertDialog confirm (case-insensitive match); activity icons by `event_type` prefix (farm./field./member.* incl. Crown for ownership_transferred/recommendation./report./billing./developer./crop_cycle./setting.); Preferences card bottom (user-scoped): locale en/ar, 28 common timezones (+current if foreign), 21 currencies (+current), metric/imperial, week start, agricultural calendar (none/gregorian/coptic/hijri +current) — PUT on save + success toast; honest hint that the header language control switches UI language (preference `locale` is the stored profile value).
- **OnboardingWizard**: Dialog `sm:max-w-lg`, compact pill Stepper (done=emerald Check, skipped=Minus, current=ring dot, pending=outline dot), driven by `GET /onboarding/progress` whenever opened (resumable). Per step: account → continue; account_type → RadioGroup + `POST /account-type`; organization → if orgs exist "You already belong to {name}" + complete, else shared `CreateOrgDialog` **or** invitation-token join (`POST /invitations/accept`) — farm/field creation is never duplicated; org_profile → link to Team tab + complete/skip; first_farm → deep-link `setActiveTab('farms')` (does NOT touch the unconsumed `createFarmDialogOpen` store flag) + "I added it — continue" + "Do this later" (never blocks); first_field / crops_priorities → same + `POST /skip/{step}` (optional steps only — server rejects skipping required ones); review → required-step checklist + complete; tour → 7 tab links (overview/farms/team/billing/insights/reports/developer) using `setActiveTab`, Finish/Skip tour + AlertDialog-confirmed `POST /onboarding/dismiss`. All mutations invalidate `['p3-onboarding']`; org step shares the `['p3-orgs']` cache with TeamTab.
- **NotificationsBell**: ghost `h-9 w-9` bell + emerald count badge (99+ cap); unread-count polled via `refetchInterval: 60_000` (`retry:false` — Forbidden when the user has no org yet ⇒ badge stays hidden, no fabricated state); Popover `w-80 sm:w-96`, All/Unread Tabs, list `max-h-96 overflow-y-auto scrollbar-thin`; severity dots info=stone / advisory=emerald / warning=amber / critical=red; category + severity Badges; relative timestamps via shared `formatRelativeTime` (`Intl.RelativeTimeFormat`, locale-aware incl. Arabic); row click marks read (if unread) and navigates only for recognized `link_kind`s (farm/field/observation→farms, report→reports, recommendation→insights, billing/subscription/invoice→billing, invitation/membership/organization→team, api_key/webhook→developer) — otherwise no navigation; Mark-all-read (disabled at 0 unread); footer opens the per-category preferences Dialog (8 categories × in-app/email Switches, immediate `PUT` per flip, error-only toast, honesty note that email delivery depends on a configured provider).

## Query keys (new)

`p3-orgs`, `p3-org-members:{orgId}`, `p3-org-invitations:{orgId}`, `p3-org-activity:{orgId}` (infinite), `p3-me`, `p3-onboarding`, `p3-notif-unread`, `p3-notifs:{all|unread}`, `p3-notif-prefs`, `p3-preferences`.

## Deviations / decisions (worth knowing)

1. **Task text vs backend**: member role PATCH body is `{role_code}` and ownership transfer is `{target_user_id}` (Pydantic models are authoritative). Severity `success` from the task does not exist server-side; `advisory` (the emerald dot) is its counterpart.
2. **Role select shows a static badge** for owner rows and for the current user (server refuses self-removal; owner changes flow through ownership transfer).
3. **Invitation token UX**: plaintext token shown once with copy button — mirrors the backend contract (hashed at rest, out-of-band delivery).
4. **Preferences `locale`** is stored on the profile but does not switch UI language (that is the NEXT_LOCALE cookie via the header LocaleSwitcher); the hint text says so — no silent mismatch.
5. **Onboarding "Do this later"** on required steps closes the wizard without a skip call (server rejects skipping required steps); resumability makes this lossless.
6. No edits to `api.ts`, `store.ts`, `i18n/*`, `nav.json`, `workspace.tsx`, sibling p3b files, or `mini-services/`. `p3` namespace was already registered in `src/i18n/config.ts`.

## Validation

- `bunx tsc --noEmit` — clean (whole repo, including sibling agents' files present at check time).
- `bun run lint` — clean; two `react-hooks/set-state-in-effect` errors found during development were fixed by switching to event-driven edit state (org rename) and a keyed form remount (preferences).
- Dev server not started; nothing committed.
