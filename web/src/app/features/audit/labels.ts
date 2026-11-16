import { AuditAction } from '../../api/models/audit-action';
import { AuditEntity } from '../../api/models/audit-entity';
import { roleLabel } from '../../core/session/roles';

export const ACTION_LABELS: Record<AuditAction, string> = {
  'organization.created': 'Creó la organización',
  'organization.settings_changed': 'Cambió la configuración',
  'invitation.created': 'Invitó a una persona',
  'invitation.revoked': 'Revocó una invitación',
  'invitation.accepted': 'Aceptó una invitación',
  'member.roles_changed': 'Cambió roles',
  'member.removed': 'Dio de baja a un miembro',
  'bank_account.created': 'Registró una cuenta bancaria',
  'bank_account.updated': 'Editó una cuenta bancaria',
  'bank_account.archived': 'Archivó una cuenta bancaria',
  'import_profile.created': 'Creó un perfil de importación',
  'import_profile.updated': 'Editó un perfil de importación',
  'import_profile.archived': 'Archivó un perfil de importación',
  'import.uploaded': 'Subió un archivo',
  'import.discarded': 'Descartó una vista previa',
  'import.confirmed': 'Confirmó una importación',
  'import.voided': 'Anuló una importación',
  'receivable.cancelled': 'Anuló un cobro',
  'engine_run.requested': 'Corrió el motor',
  'demo.role_switched': 'Cambió de rol en la demo',
  'match.created': 'Creó una coincidencia',
  'match.confirmed': 'Confirmó una coincidencia',
  'match.discarded': 'Descartó una coincidencia',
  'match.approved': 'Aprobó una coincidencia',
  'match.rejected': 'Rechazó una coincidencia',
  'match.reverted': 'Revirtió una coincidencia',
  'period.closed': 'Cerró un mes',
  'period.reopened': 'Reabrió un mes',
};

export const ENTITY_LABELS: Record<AuditEntity, string> = {
  organization: 'Organización',
  user: 'Usuario',
  invitation: 'Invitación',
  member: 'Miembro',
  bank_account: 'Cuenta bancaria',
  import_profile: 'Perfil de importación',
  import_file: 'Archivo importado',
  receivable: 'Cobro',
  engine_run: 'Corrida del motor',
  match: 'Coincidencia',
  period_event: 'Cierre de mes',
};

const SOURCE_LABELS: Record<string, string> = {
  demo: 'demo',
  registration: 'registro',
  cli: 'consola',
  manual: 'a mano',
  ai: 'sugerencia de IA',
  engine: 'motor',
};

const KIND_LABELS: Record<string, string> = {
  bank_statement: 'extracto',
  receivables: 'cobros',
};

function list(value: string | string[]): string[] {
  return Array.isArray(value) ? value : [value];
}

/** The metadata keys are a closed list (audit.domain); each one reads as a short phrase. */
export function metadataSummary(metadata: Record<string, string | string[]>): string {
  const parts: string[] = [];
  if (metadata['source']) {
    const source = list(metadata['source'])[0];
    parts.push(`Origen: ${SOURCE_LABELS[source] ?? source}`);
  }
  if (metadata['kind']) {
    const kind = list(metadata['kind'])[0];
    parts.push(`Tipo: ${KIND_LABELS[kind] ?? kind}`);
  }
  if (metadata['roles']) {
    parts.push(`Roles: ${list(metadata['roles']).map(roleLabel).join(', ')}`);
  }
  if (metadata['fields']) {
    parts.push(`Campos: ${list(metadata['fields']).join(', ')}`);
  }
  return parts.join(' · ') || '—';
}
