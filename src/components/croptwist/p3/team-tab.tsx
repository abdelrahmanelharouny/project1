'use client'

import { useMemo, useState, type FormEvent } from 'react'
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryResult,
} from '@tanstack/react-query'
import { useLocale, useTranslations } from 'next-intl'
import { toast } from 'sonner'
import {
  AlertCircle,
  Building2,
  Check,
  Copy,
  CreditCard,
  Crown,
  FileText,
  History,
  KeyRound,
  LandPlot,
  Loader2,
  Pencil,
  RefreshCw,
  Settings,
  ShieldCheck,
  Sparkles,
  Tractor,
  UserMinus,
  UserPlus,
  Users,
  Wheat,
} from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { describeError, getMe } from '@/lib/api'
import {
  createInvitation,
  createOrganization,
  listOrganizationActivity,
  listOrganizationInvitations,
  listOrganizationMembers,
  listOrganizations,
  patchOrganization,
  patchOrganizationMemberRole,
  removeOrganizationMember,
  revokeInvitation,
  roleAtLeast,
  transferOrganizationOwnership,
  type Organization,
  type OrganizationActivityEvent,
  type OrganizationMember,
  type OrganizationMemberListResponse,
  type OrganizationType,
  type OrgRoleCode,
} from '@/lib/api-p3-account'
import { formatDay } from '@/lib/format'
import { RowSkeletons, SectionError } from './settings-shared'

// ---------------------------------------------------------------------------
// Constants + small helpers
// ---------------------------------------------------------------------------

const ORG_TYPES: OrganizationType[] = ['individual', 'business', 'farm_org']

const ALL_ROLES: OrgRoleCode[] = [
  'owner',
  'org_admin',
  'manager',
  'operator',
  'agronomist',
  'analyst',
  'viewer',
]



/** Message key for a role code (also used by the onboarding wizard). */
export function roleLabelKey(role: OrgRoleCode): string {
  switch (role) {
    case 'owner':
      return 'team.roleOwner'
    case 'org_admin':
      return 'team.roleOrgAdmin'
    case 'manager':
      return 'team.roleManager'
    case 'operator':
      return 'team.roleOperator'
    case 'agronomist':
      return 'team.roleAgronomist'
    case 'analyst':
      return 'team.roleAnalyst'
    default:
      return 'team.roleViewer'
  }
}

/** Relative time ("3 days ago") in the active UI locale. Shared with the
 * notifications bell. */
export function formatRelativeTime(iso: string | null | undefined, locale: string): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'
  const diffMs = date.getTime() - Date.now()
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' })
  const abs = Math.abs(diffMs)
  const MINUTE = 60_000
  const HOUR = 3_600_000
  const DAY = 86_400_000
  if (abs < MINUTE) return rtf.format(Math.round(diffMs / 1000), 'second')
  if (abs < HOUR) return rtf.format(Math.round(diffMs / MINUTE), 'minute')
  if (abs < DAY) return rtf.format(Math.round(diffMs / HOUR), 'hour')
  if (abs < 30 * DAY) return rtf.format(Math.round(diffMs / DAY), 'day')
  if (abs < 365 * DAY) return rtf.format(Math.round(diffMs / (30 * DAY)), 'month')
  return rtf.format(Math.round(diffMs / (365 * DAY)), 'year')
}

/** Roles the current actor may grant (frontend UX only — the server enforces
 * the actual policy: only an owner can grant owner/org_admin). */
function assignableRoles(myRole: OrgRoleCode | null): OrgRoleCode[] {
  if (roleAtLeast(myRole, 'owner')) return ALL_ROLES
  if (roleAtLeast(myRole, 'org_admin')) return ALL_ROLES.filter((r) => r !== 'owner' && r !== 'org_admin')
  return []
}

// SectionError / RowSkeletons moved to ./settings-shared (P03 W2.2) — shared
 // with the extracted Preferences sub-page.

// ---------------------------------------------------------------------------
// Create organization dialog (shared with the onboarding wizard)
// ---------------------------------------------------------------------------

export function CreateOrgDialog({
  open,
  onOpenChange,
  onCreated,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated?: (org: Organization) => void
}) {
  const t = useTranslations('p3')
  const tCommon = useTranslations('common')
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [type, setType] = useState<OrganizationType>('individual')

  const handleOpenChange = (next: boolean) => {
    if (!next) {
      setName('')
      setType('individual')
    }
    onOpenChange(next)
  }

  const mutation = useMutation({
    mutationFn: () => createOrganization({ name: name.trim(), organization_type: type }),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['p3-orgs'] })
      queryClient.invalidateQueries({ queryKey: ['p3-onboarding'] })
      toast.success(t('team.created'), { description: created.name })
      handleOpenChange(false)
      onCreated?.(created)
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!name.trim() || mutation.isPending) return
    mutation.mutate()
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-h-[85vh] overflow-y-auto scrollbar-thin sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('team.createTitle')}</DialogTitle>
          <DialogDescription>{t('team.createDesc')}</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="space-y-4" aria-label={t('team.createTitle')}>
          <div className="space-y-1.5">
            <Label htmlFor="p3-org-name">{t('team.nameLabel')}</Label>
            <Input
              id="p3-org-name"
              placeholder={t('team.namePlaceholder')}
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={200}
              required
            />
          </div>
          <fieldset className="space-y-1.5">
            <legend className="text-sm font-medium text-stone-700">{t('team.typeLabel')}</legend>
            <RadioGroup
              value={type}
              onValueChange={(value) => setType(value as OrganizationType)}
              className="gap-2 pt-1"
            >
              {ORG_TYPES.map((value) => (
                <Label
                  key={value}
                  htmlFor={`p3-org-type-${value}`}
                  className="flex cursor-pointer items-start gap-2.5 rounded-md border border-stone-200 bg-white p-3 text-start font-normal hover:bg-stone-50 has-[[data-state=checked]]:border-emerald-600"
                >
                  <RadioGroupItem id={`p3-org-type-${value}`} value={value} className="mt-0.5" />
                  <span className="space-y-0.5">
                    <span className="block text-sm font-medium text-stone-900">
                      {value === 'individual'
                        ? t('account.typeIndividual')
                        : value === 'business'
                          ? t('account.typeBusiness')
                          : t('account.typeFarmOrg')}
                    </span>
                    <span className="block text-xs text-stone-500">
                      {value === 'individual'
                        ? t('account.explainIndividual')
                        : value === 'business'
                          ? t('account.explainBusiness')
                          : t('account.explainFarmOrg')}
                    </span>
                  </span>
                </Label>
              ))}
            </RadioGroup>
          </fieldset>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => handleOpenChange(false)}>
              {tCommon('cancel')}
            </Button>
            <Button type="submit" disabled={mutation.isPending || !name.trim()} className="gap-1.5">
              {mutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
              {t('team.createOrg')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

// ---------------------------------------------------------------------------
// Organization card (identity + inline rename for org_admin+)
// ---------------------------------------------------------------------------

function OrgCard({ org, memberCount }: { org: Organization; memberCount: number | undefined }) {
  const t = useTranslations('p3')
  const tCommon = useTranslations('common')
  const queryClient = useQueryClient()
  const canEdit = roleAtLeast(org.my_role, 'org_admin')
  // Inline edit state is keyed by org id (event-driven, no sync effect).
  const [editState, setEditState] = useState<{ orgId: string; name: string } | null>(null)
  const editing = editState !== null && editState.orgId === org.id
  const name = editState?.name ?? org.name

  const mutation = useMutation({
    mutationFn: () => patchOrganization(org.id, { name: name.trim() }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['p3-orgs'] })
      toast.success(t('team.nameUpdated'))
      setEditState(null)
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  return (
    <Card className="border-stone-200 bg-white shadow-sm">
      <CardContent>
        {editing ? (
          <form
            className="flex items-center gap-2"
            onSubmit={(event) => {
              event.preventDefault()
              if (name.trim() && name.trim() !== org.name) mutation.mutate()
              else setEditState(null)
            }}
          >
            <Input
              aria-label={t('team.nameLabel')}
              value={name}
              onChange={(event) => setEditState({ orgId: org.id, name: event.target.value })}
              maxLength={200}
              className="h-8 max-w-xs"
              autoFocus
            />
            <Button type="submit" size="sm" className="h-8" disabled={mutation.isPending}>
              {mutation.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              ) : (
                <Check className="h-3.5 w-3.5" aria-hidden />
              )}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="h-8"
              onClick={() => setEditState(null)}
            >
              {tCommon('cancel')}
            </Button>
          </form>
        ) : (
          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <h3 className="truncate text-base font-semibold text-stone-900">{org.name}</h3>
              {canEdit ? (
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-9 w-9"
                  aria-label={t('team.editName')}
                  onClick={() => setEditState({ orgId: org.id, name: org.name })}
                >
                  <Pencil className="h-3.5 w-3.5" aria-hidden />
                </Button>
              ) : null}
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-stone-500">
              <Badge variant="outline" className="border-stone-300 bg-stone-50 font-normal text-stone-600">
                {org.organization_type === 'individual'
                  ? t('account.typeIndividual')
                  : org.organization_type === 'business'
                    ? t('account.typeBusiness')
                    : t('account.typeFarmOrg')}
              </Badge>
              <span>{t('team.memberCount', { count: memberCount ?? 0 })}</span>
              <span>{t('team.createdOn', { date: formatDay(org.created_at) })}</span>
              <span className="flex items-center gap-1">
                <ShieldCheck className="h-3.5 w-3.5 text-emerald-700" aria-hidden />
                {t('team.yourRole')}: {t(roleLabelKey(org.my_role ?? 'viewer'))}
              </span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Members (role select + remove for org_admin/owner; UX gating only)
// ---------------------------------------------------------------------------

function MemberRoleBadge({ role }: { role: OrgRoleCode }) {
  const t = useTranslations('p3')
  return (
    <Badge
      variant="outline"
      className={
        role === 'owner'
          ? 'border-emerald-300 bg-emerald-50 font-normal text-emerald-800'
          : 'border-stone-300 bg-white font-normal text-stone-600'
      }
    >
      {t(roleLabelKey(role))}
    </Badge>
  )
}

function MemberActions({
  org,
  member,
  myRole,
  meId,
}: {
  org: Organization
  member: OrganizationMember
  myRole: OrgRoleCode | null
  meId: string | null
}) {
  const t = useTranslations('p3')
  const tCommon = useTranslations('common')
  const queryClient = useQueryClient()
  const [confirmOpen, setConfirmOpen] = useState(false)
  const canManage = roleAtLeast(myRole, 'org_admin')
  const isSelf = member.user_id === meId
  const options = assignableRoles(myRole)
  const displayName = member.display_name || member.email || member.user_id

  const roleMutation = useMutation({
    mutationFn: (role: OrgRoleCode) => patchOrganizationMemberRole(org.id, member.user_id, role),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['p3-org-members', org.id] })
      queryClient.invalidateQueries({ queryKey: ['p3-orgs'] })
      toast.success(t('team.roleChanged'))
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  const removeMutation = useMutation({
    mutationFn: () => removeOrganizationMember(org.id, member.user_id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['p3-org-members', org.id] })
      queryClient.invalidateQueries({ queryKey: ['p3-orgs'] })
      toast.success(t('team.memberRemoved'))
      setConfirmOpen(false)
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  if (!canManage) {
    return <MemberRoleBadge role={member.role_code} />
  }

  return (
    <div className="flex items-center justify-end gap-2">
      {isSelf || member.role_code === 'owner' ? (
        <MemberRoleBadge role={member.role_code} />
      ) : (
        <Select
          value={member.role_code}
          onValueChange={(value) => roleMutation.mutate(value as OrgRoleCode)}
          disabled={roleMutation.isPending}
        >
          <SelectTrigger
            aria-label={`${t('team.colRole')} — ${displayName}`}
            className="h-8 w-[130px] border-stone-300 bg-white text-xs"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {options.map((role) => (
              <SelectItem key={role} value={role} className="text-xs">
                {t(roleLabelKey(role))}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
      {isSelf ? null : (
        <Button
          size="icon"
          variant="ghost"
          className="h-8 w-8 text-red-600 hover:bg-red-50 hover:text-red-700"
          aria-label={`${t('team.removeMember')} — ${displayName}`}
          onClick={() => setConfirmOpen(true)}
        >
          <UserMinus className="h-4 w-4" aria-hidden />
        </Button>
      )}
      <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('team.removeTitle', { name: displayName })}</AlertDialogTitle>
            <AlertDialogDescription>{t('team.removeDesc')}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{tCommon('cancel')}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-red-600 text-white hover:bg-red-700"
              onClick={(event) => {
                event.preventDefault()
                removeMutation.mutate()
              }}
            >
              {removeMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
              {t('team.removeAction')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

function MembersSection({
  org,
  myRole,
  meId,
  membersQuery,
}: {
  org: Organization
  myRole: OrgRoleCode | null
  meId: string | null
  membersQuery: UseQueryResult<OrganizationMemberListResponse>
}) {
  const t = useTranslations('p3')
  const tCommon = useTranslations('common')
  const locale = useLocale()
  const members = membersQuery.data?.items ?? []

  return (
    <Card className="border-stone-200 bg-white shadow-sm">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-semibold text-stone-900">{t('team.membersTitle')}</CardTitle>
        <CardDescription>{t('team.membersDesc')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {membersQuery.isLoading ? (
          <RowSkeletons />
        ) : membersQuery.isError ? (
          <SectionError onRetry={() => membersQuery.refetch()} />
        ) : members.length === 0 ? (
          <p className="text-sm text-stone-500">{tCommon('noData')}</p>
        ) : (
          <>
            {/* Table on wide screens */}
            <div className="hidden sm:block">
              <Table>
                <TableHeader>
                  <TableRow className="border-stone-200">
                    <TableHead className="text-stone-600">{t('team.colMember')}</TableHead>
                    <TableHead className="text-stone-600">{t('team.colJoined')}</TableHead>
                    <TableHead className="text-end text-stone-600">{t('team.colRole')}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {members.map((member) => (
                    <TableRow key={member.id} className="border-stone-100">
                      <TableCell>
                        <div className="flex flex-col">
                          <span className="text-sm font-medium text-stone-900">
                            {member.display_name || member.email || member.user_id}
                            {member.user_id === meId ? (
                              <span className="ms-2 rounded bg-stone-100 px-1.5 py-0.5 text-[10px] font-normal text-stone-500">
                                {t('team.you')}
                              </span>
                            ) : null}
                          </span>
                          {member.email ? (
                            <span className="text-xs text-stone-500" dir="ltr">
                              {member.email}
                            </span>
                          ) : null}
                        </div>
                      </TableCell>
                      <TableCell className="text-xs text-stone-500">
                        {formatRelativeTime(member.joined_at, locale)}
                      </TableCell>
                      <TableCell className="text-end">
                        <MemberActions org={org} member={member} myRole={myRole} meId={meId} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
            {/* Cards on small screens */}
            <div className="space-y-2 sm:hidden">
              {members.map((member) => (
                <div key={member.id} className="rounded-md border border-stone-200 p-2.5">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium text-stone-900">
                        {member.display_name || member.email || member.user_id}
                        {member.user_id === meId ? ` · ${t('team.you')}` : ''}
                      </p>
                      {member.email ? (
                        <p className="truncate text-xs text-stone-500" dir="ltr">
                          {member.email}
                        </p>
                      ) : null}
                      <p className="mt-0.5 text-xs text-stone-500">
                        {t('team.colJoined')}: {formatRelativeTime(member.joined_at, locale)}
                      </p>
                    </div>
                    <MemberActions org={org} member={member} myRole={myRole} meId={meId} />
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
        {roleAtLeast(myRole, 'org_admin') ? (
          <p className="text-xs text-stone-500">{t('team.rolesNote')}</p>
        ) : null}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Invitations (org_admin+)
// ---------------------------------------------------------------------------

function InvitationsSection({ org, myRole }: { org: Organization; myRole: OrgRoleCode | null }) {
  const t = useTranslations('p3')
  const queryClient = useQueryClient()
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<OrgRoleCode>('viewer')
  const [tokenNotice, setTokenNotice] = useState<string | null>(null)
  const options = assignableRoles(myRole)

  const invitationsQuery = useQuery({
    queryKey: ['p3-org-invitations', org.id],
    queryFn: () => listOrganizationInvitations(org.id, 'pending'),
  })

  const createMutation = useMutation({
    mutationFn: () =>
      createInvitation(org.id, { email: email.trim().toLowerCase(), role_code: role }),
    onSuccess: (invitation) => {
      queryClient.invalidateQueries({ queryKey: ['p3-org-invitations', org.id] })
      queryClient.invalidateQueries({ queryKey: ['p3-orgs'] })
      toast.success(t('team.inviteCreated'))
      setTokenNotice(invitation.token ?? null)
      setEmail('')
      setRole('viewer')
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  const revokeMutation = useMutation({
    mutationFn: (invitationId: string) => revokeInvitation(org.id, invitationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['p3-org-invitations', org.id] })
      toast.success(t('team.revoked'))
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!email.trim() || createMutation.isPending) return
    createMutation.mutate()
  }

  const copyToken = async () => {
    if (!tokenNotice) return
    try {
      await navigator.clipboard.writeText(tokenNotice)
      toast.success(t('team.tokenCopied'))
    } catch {
      // Clipboard unavailable — the token stays visible in the alert.
    }
  }

  const pending = invitationsQuery.data?.items ?? []

  return (
    <Card className="border-stone-200 bg-white shadow-sm">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-semibold text-stone-900">{t('team.invitationsTitle')}</CardTitle>
        <CardDescription>{t('team.invitationsDesc')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {tokenNotice ? (
          <Alert className="border-emerald-200 bg-emerald-50 [&>svg]:text-emerald-700">
            <KeyRound className="h-4 w-4" />
            <AlertTitle className="text-emerald-900">{t('team.tokenTitle')}</AlertTitle>
            <AlertDescription className="text-emerald-900">
              <code
                className="block max-w-full truncate rounded bg-white px-2 py-1 font-mono text-xs"
                dir="ltr"
              >
                {tokenNotice}
              </code>
              <Button size="sm" variant="outline" className="mt-2 gap-1.5" onClick={copyToken}>
                <Copy className="h-3.5 w-3.5" aria-hidden /> {t('team.copyToken')}
              </Button>
            </AlertDescription>
          </Alert>
        ) : null}

        <form
          onSubmit={submit}
          className="grid gap-2 sm:grid-cols-[1fr_150px_auto]"
          aria-label={t('team.sendInvite')}
        >
          <div className="space-y-1">
            <Label htmlFor="p3-invite-email" className="sr-only">
              {t('team.emailLabel')}
            </Label>
            <Input
              id="p3-invite-email"
              type="email"
              placeholder={t('team.emailPlaceholder')}
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              dir="ltr"
            />
          </div>
          <Select value={role} onValueChange={(value) => setRole(value as OrgRoleCode)}>
            <SelectTrigger aria-label={t('team.roleLabel')} className="border-stone-300 bg-white text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {options.map((option) => (
                <SelectItem key={option} value={option} className="text-xs">
                  {t(roleLabelKey(option))}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button type="submit" className="gap-1.5" disabled={createMutation.isPending || !email.trim()}>
            {createMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <UserPlus className="h-4 w-4" aria-hidden />
            )}
            <span className="hidden sm:inline">{t('team.sendInvite')}</span>
          </Button>
        </form>

        <Separator className="bg-stone-100" />

        <div className="space-y-1.5">
          <p className="text-xs font-medium uppercase tracking-wide text-stone-500">
            {t('team.pendingTitle')}
          </p>
          {invitationsQuery.isLoading ? (
            <RowSkeletons rows={2} />
          ) : invitationsQuery.isError ? (
            <SectionError onRetry={() => invitationsQuery.refetch()} />
          ) : pending.length === 0 ? (
            <p className="text-sm text-stone-500">{t('team.noPending')}</p>
          ) : (
            <ul className="divide-y divide-stone-100">
              {pending.map((invitation) => (
                <li key={invitation.id} className="flex items-center justify-between gap-2 py-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm text-stone-900" dir="ltr">
                      {invitation.email}
                    </p>
                    <p className="text-xs text-stone-500">
                      {t(roleLabelKey(invitation.role_code))}
                      {invitation.expires_at
                        ? ` · ${t('team.expires', { date: formatDay(invitation.expires_at) })}`
                        : ''}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-8 shrink-0 text-red-600 hover:bg-red-50 hover:text-red-700"
                    onClick={() => revokeMutation.mutate(invitation.id)}
                    disabled={revokeMutation.isPending}
                  >
                    {revokeMutation.isPending && revokeMutation.variables === invitation.id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                    ) : null}
                    {t('team.revoke')}
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Ownership transfer (owner only, typed-email confirmation)
// ---------------------------------------------------------------------------

function OwnershipSection({ org, members }: { org: Organization; members: OrganizationMember[] }) {
  const t = useTranslations('p3')
  const tCommon = useTranslations('common')
  const queryClient = useQueryClient()
  const [targetId, setTargetId] = useState('')
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [typedEmail, setTypedEmail] = useState('')

  const targets = members.filter((member) => member.role_code !== 'owner')
  const target = useMemo(
    () => targets.find((member) => member.user_id === targetId) ?? null,
    [targets, targetId],
  )

  const mutation = useMutation({
    mutationFn: () => transferOrganizationOwnership(org.id, targetId),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['p3-orgs'] })
      queryClient.invalidateQueries({ queryKey: ['p3-org-members', org.id] })
      queryClient.invalidateQueries({ queryKey: ['p3-org-activity', org.id] })
      toast.success(t('team.ownershipTransferred'), {
        description: result.new_owner_email ?? undefined,
      })
      setConfirmOpen(false)
      setTargetId('')
      setTypedEmail('')
    },
    onError: (err) => {
      const { title, description } = describeError(err)
      toast.error(title, { description })
    },
  })

  return (
    <Card className="border-stone-200 bg-white shadow-sm">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-1.5 text-sm font-semibold text-stone-900">
          <Crown className="h-4 w-4 text-amber-600" aria-hidden /> {t('team.ownershipTitle')}
        </CardTitle>
        <CardDescription>{t('team.ownershipDesc')}</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Select
            value={targetId}
            onValueChange={(value) => {
              setTargetId(value)
              setTypedEmail('')
            }}
          >
            <SelectTrigger
              aria-label={t('team.selectNewOwner')}
              className="border-stone-300 bg-white text-xs"
            >
              <SelectValue placeholder={t('team.selectNewOwner')} />
            </SelectTrigger>
            <SelectContent>
              {targets.map((member) => (
                <SelectItem key={member.id} value={member.user_id} className="text-xs">
                  {member.display_name || member.email || member.user_id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            className="gap-1.5 border-amber-300 text-amber-800 hover:bg-amber-50 hover:text-amber-900"
            disabled={!targetId}
            onClick={() => setConfirmOpen(true)}
          >
            <Crown className="h-4 w-4" aria-hidden /> {t('team.transfer')}
          </Button>
        </div>

        <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>
                {target
                  ? t('team.transferTitle', {
                      name: target.display_name || target.email || target.user_id,
                    })
                  : null}
              </AlertDialogTitle>
              <AlertDialogDescription>{t('team.transferDesc')}</AlertDialogDescription>
            </AlertDialogHeader>
            <div className="space-y-1.5">
              <Label htmlFor="p3-transfer-email">{t('team.typedEmailLabel')}</Label>
              <Input
                id="p3-transfer-email"
                value={typedEmail}
                onChange={(event) => setTypedEmail(event.target.value)}
                autoComplete="off"
                dir="ltr"
              />
            </div>
            <AlertDialogFooter>
              <AlertDialogCancel>{tCommon('cancel')}</AlertDialogCancel>
              <AlertDialogAction
                className="bg-amber-700 text-white hover:bg-amber-800"
                disabled={
                  !target ||
                  typedEmail.trim().toLowerCase() !== (target.email ?? '').toLowerCase() ||
                  mutation.isPending
                }
                onClick={(event) => {
                  event.preventDefault()
                  mutation.mutate()
                }}
              >
                {mutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
                {t('team.transferAction')}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Activity timeline (paginated, icon per event type)
// ---------------------------------------------------------------------------

function ActivityIcon({ eventType }: { eventType: string }) {
  if (eventType.startsWith('farm.')) return <Tractor className="h-4 w-4" aria-hidden />
  if (eventType.startsWith('field.')) return <LandPlot className="h-4 w-4" aria-hidden />
  if (eventType === 'member.ownership_transferred') return <Crown className="h-4 w-4" aria-hidden />
  if (eventType === 'member.invited' || eventType === 'member.joined')
    return <UserPlus className="h-4 w-4" aria-hidden />
  if (eventType === 'member.removed') return <UserMinus className="h-4 w-4" aria-hidden />
  if (eventType.startsWith('member.')) return <ShieldCheck className="h-4 w-4" aria-hidden />
  if (eventType.startsWith('recommendation.')) return <Sparkles className="h-4 w-4" aria-hidden />
  if (eventType.startsWith('report.')) return <FileText className="h-4 w-4" aria-hidden />
  if (eventType.startsWith('billing.')) return <CreditCard className="h-4 w-4" aria-hidden />
  if (eventType.startsWith('developer.')) return <KeyRound className="h-4 w-4" aria-hidden />
  if (eventType.startsWith('crop_cycle.')) return <Wheat className="h-4 w-4" aria-hidden />
  if (eventType.startsWith('setting.')) return <Settings className="h-4 w-4" aria-hidden />
  return <History className="h-4 w-4" aria-hidden />
}

function ActivitySection({ orgId }: { orgId: string }) {
  const t = useTranslations('p3')
  const locale = useLocale()
  const PAGE_SIZE = 10

  const activityQuery = useInfiniteQuery({
    queryKey: ['p3-org-activity', orgId],
    queryFn: ({ pageParam }) =>
      listOrganizationActivity(orgId, { limit: PAGE_SIZE, offset: pageParam as number }),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => {
      const next = lastPage.offset + lastPage.items.length
      return next < lastPage.total ? next : undefined
    },
  })

  const events: OrganizationActivityEvent[] =
    activityQuery.data?.pages.flatMap((page) => page.items) ?? []

  return (
    <Card className="border-stone-200 bg-white shadow-sm">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-semibold text-stone-900">{t('team.activityTitle')}</CardTitle>
        <CardDescription>{t('team.activityDesc')}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {activityQuery.isLoading ? (
          <RowSkeletons />
        ) : activityQuery.isError ? (
          <SectionError onRetry={() => activityQuery.refetch()} />
        ) : events.length === 0 ? (
          <p className="text-sm text-stone-500">{t('team.noActivity')}</p>
        ) : (
          <>
            <ol>
              {events.map((event, index) => (
                <li key={event.id} className="relative flex gap-3 pb-4 last:pb-0">
                  {index < events.length - 1 ? (
                    <span
                      className="absolute start-[15px] top-9 h-[calc(100%-2.25rem)] w-px bg-stone-200"
                      aria-hidden
                    />
                  ) : null}
                  <span className="relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-stone-200 bg-stone-50 text-stone-600">
                    <ActivityIcon eventType={event.event_type} />
                  </span>
                  <div className="min-w-0 pt-1">
                    <p className="text-sm text-stone-900">{event.summary}</p>
                    <p className="text-xs text-stone-500">
                      {formatRelativeTime(event.created_at, locale)}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
            {activityQuery.hasNextPage ? (
              <Button
                size="sm"
                variant="outline"
                className="gap-1.5"
                onClick={() => activityQuery.fetchNextPage()}
                disabled={activityQuery.isFetchingNextPage}
              >
                {activityQuery.isFetchingNextPage ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                ) : null}
                {t('team.loadMore')}
              </Button>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  )
}

// Preferences (global product configuration, user-scoped) moved to the
// dedicated `preferences-tab.tsx` Settings sub-page (P03 W2.2).

// ---------------------------------------------------------------------------
// TeamTab (default export)
// ---------------------------------------------------------------------------

export default function TeamTab() {
  const t = useTranslations('p3')
  const [createOpen, setCreateOpen] = useState(false)
  const [selectedOrgId, setSelectedOrgId] = useState<string | null>(null)

  const orgsQuery = useQuery({
    queryKey: ['p3-orgs'],
    queryFn: listOrganizations,
    staleTime: 15_000,
  })

  const meQuery = useQuery({
    queryKey: ['p3-me'],
    queryFn: getMe,
    staleTime: 5 * 60_000,
  })

  const orgs = orgsQuery.data?.items ?? []
  const org = useMemo(
    () => orgs.find((candidate) => candidate.id === selectedOrgId) ?? orgs[0] ?? null,
    [orgs, selectedOrgId],
  )

  const membersQuery = useQuery({
    queryKey: ['p3-org-members', org?.id],
    queryFn: () => listOrganizationMembers((org as Organization).id),
    enabled: Boolean(org),
  })
  const memberCount = membersQuery.data?.total
  const members = membersQuery.data?.items ?? []
  const myRole = org?.my_role ?? null
  const meId = meQuery.data?.user.id ?? null

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold tracking-tight text-stone-900">{t('team.title')}</h2>
        <p className="text-sm text-stone-500">{t('team.subtitle')}</p>
      </div>

      {orgsQuery.isLoading ? (
        <div className="space-y-3" aria-hidden>
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : orgsQuery.isError ? (
        <Alert variant="destructive" className="border-red-200 bg-red-50 [&>svg]:text-red-600">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle className="text-red-900">{t('team.errorTitle')}</AlertTitle>
          <AlertDescription className="mt-2">
            <Button size="sm" variant="outline" onClick={() => orgsQuery.refetch()} className="gap-1.5">
              <RefreshCw className="h-3.5 w-3.5" aria-hidden /> {t('team.retry')}
            </Button>
          </AlertDescription>
        </Alert>
      ) : orgs.length === 0 ? (
        <Card className="border-stone-200 bg-white shadow-sm">
          <CardContent className="flex flex-col items-center gap-4 py-10 text-center">
            <span className="flex h-12 w-12 items-center justify-center rounded-2xl border border-emerald-200 bg-emerald-50 text-emerald-700">
              <Users className="h-6 w-6" aria-hidden />
            </span>
            <div className="space-y-1">
              <h3 className="text-base font-semibold text-stone-900">{t('team.emptyTitle')}</h3>
              <p className="mx-auto max-w-md text-sm text-stone-500">{t('team.emptyDesc')}</p>
            </div>
            <ul className="mx-auto max-w-md space-y-1.5 text-start text-sm text-stone-600">
              <li className="flex items-center gap-2">
                <Building2 className="h-4 w-4 shrink-0 text-emerald-700" aria-hidden /> {t('team.reason1')}
              </li>
              <li className="flex items-center gap-2">
                <ShieldCheck className="h-4 w-4 shrink-0 text-emerald-700" aria-hidden /> {t('team.reason2')}
              </li>
              <li className="flex items-center gap-2">
                <History className="h-4 w-4 shrink-0 text-emerald-700" aria-hidden /> {t('team.reason3')}
              </li>
            </ul>
            <Button onClick={() => setCreateOpen(true)} className="gap-1.5">
              <UserPlus className="h-4 w-4" aria-hidden /> {t('team.createOrg')}
            </Button>
          </CardContent>
        </Card>
      ) : (
        <>
          {orgs.length > 1 ? (
            <div className="flex flex-wrap items-center gap-2">
              <Label htmlFor="p3-org-select" className="text-xs text-stone-500">
                {t('team.selectOrg')}
              </Label>
              <Select value={org?.id ?? ''} onValueChange={(value) => setSelectedOrgId(value)}>
                <SelectTrigger
                  id="p3-org-select"
                  className="h-8 w-full max-w-xs border-stone-300 bg-white text-xs"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {orgs.map((candidate) => (
                    <SelectItem key={candidate.id} value={candidate.id} className="text-xs">
                      {candidate.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ) : null}

          {org ? (
            <>
              <OrgCard org={org} memberCount={memberCount} />
              <div className="grid gap-4 lg:grid-cols-2">
                <MembersSection org={org} myRole={myRole} meId={meId} membersQuery={membersQuery} />
                <div className="space-y-4">
                  {roleAtLeast(myRole, 'org_admin') ? (
                    <InvitationsSection org={org} myRole={myRole} />
                  ) : null}
                  {myRole === 'owner' ? <OwnershipSection org={org} members={members} /> : null}
                </div>
              </div>
              <ActivitySection orgId={org.id} />
            </>
          ) : null}
        </>
      )}

      <CreateOrgDialog open={createOpen} onOpenChange={setCreateOpen} />
    </div>
  )
}
