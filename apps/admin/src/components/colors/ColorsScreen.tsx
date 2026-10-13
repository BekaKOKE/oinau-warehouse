'use client';

/**
 * Справочник цветов: один на весь каталог, чтобы «чёрный» у каната
 * и у сиденья был одним цветом. Код цвета после создания не меняется —
 * он записан в отправленных заявках. Используемый цвет не удаляется,
 * а отключается: на сайте он пропадает, в заявках остаётся.
 */

import { useState, type FormEvent } from 'react';

import { RequirePermission } from '@/components/session/AuthGate';
import { useSession } from '@/components/session/SessionProvider';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { DataTable, type Column } from '@/components/ui/DataTable';
import { Dialog, useConfirm } from '@/components/ui/Dialog';
import { Field, Input, Switch } from '@/components/ui/Field';
import { Card, PageHeader } from '@/components/ui/Layout';
import { EmptyState } from '@/components/ui/States';
import { useToast } from '@/components/ui/Toast';
import { colorsApi } from '@/lib/api/endpoints';
import type { Color } from '@/lib/api/types';
import { Permission } from '@/lib/auth/permissions';
import { colorCodeFromName } from '@/lib/colors';
import { extractFieldErrors, isForbidden } from '@/lib/errors';
import { formatCount, plural } from '@/lib/format';
import { useQuery } from '@/lib/hooks/useQuery';

import styles from './Colors.module.css';

const HEX = /^#[0-9a-fA-F]{6}$/;

export function ColorsScreen() {
  return (
    <RequirePermission all={[Permission.CATALOG_READ]}>
      <ColorsPanel />
    </RequirePermission>
  );
}

function ColorsPanel() {
  const { can } = useSession();
  const canWrite = can(Permission.CATALOG_WRITE);
  const toast = useToast();
  const confirm = useConfirm();
  const list = useQuery((signal) => colorsApi.list({ signal }), []);
  const [open, setOpen] = useState<Color | 'new' | null>(null);

  const remove = async (color: Color) => {
    const approved = await confirm({
      title: `Удалить цвет «${color.name}»?`,
      description:
        'Цвет исчезнет из справочника. Удалить можно только цвет, который не используется в товарах.',
      confirmLabel: 'Удалить',
    });
    if (!approved) return;
    try {
      await colorsApi.remove(color.id);
      toast.success('Цвет удалён', color.name);
      list.reload();
    } catch (error) {
      toast.error(isForbidden(error) ? 'Нет права изменять цвета' : 'Цвет не удалён', error);
    }
  };

  const columns: Column<Color>[] = [
    {
      key: 'name',
      header: 'Цвет',
      cell: (row) => (
        <div className={styles.nameCell}>
          <span className={styles.swatch} style={{ background: row.hex }} aria-hidden="true" />
          {canWrite ? (
            <button type="button" className={styles.nameButton} onClick={() => setOpen(row)}>
              {row.name}
            </button>
          ) : (
            <span>{row.name}</span>
          )}
        </div>
      ),
    },
    { key: 'code', header: 'Код', cell: (row) => <span className="mono">{row.code}</span> },
    {
      key: 'hex',
      header: 'Образец',
      hideOnMobile: true,
      cell: (row) => <span className="mono">{row.hex}</span>,
    },
    {
      key: 'usage',
      header: 'У товаров',
      align: 'right',
      cell: (row) => <span className="num">{formatCount(row.products_count ?? 0)}</span>,
    },
    {
      key: 'status',
      header: 'Статус',
      cell: (row) =>
        row.is_active ? (
          <Badge tone="success">Активен</Badge>
        ) : (
          <Badge tone="neutral">Отключён</Badge>
        ),
    },
    ...(canWrite
      ? [
          {
            key: 'actions',
            header: <span className="visually-hidden">Действия</span>,
            align: 'right' as const,
            cell: (row: Color) =>
              row.products_count ? null : (
                <Button
                  size="sm"
                  variant="dangerGhost"
                  icon="trash"
                  aria-label={`Удалить цвет ${row.name}`}
                  onClick={() => void remove(row)}
                />
              ),
          },
        ]
      : []),
  ];

  const total = list.data?.length ?? 0;

  return (
    <>
      <PageHeader
        title="Цвета"
        description={
          list.data
            ? `${formatCount(total)} ${plural(total, ['цвет', 'цвета', 'цветов'])} в справочнике`
            : 'Справочник цветов товаров'
        }
        actions={
          canWrite ? (
            <Button variant="primary" icon="plus" onClick={() => setOpen('new')}>
              Новый цвет
            </Button>
          ) : null
        }
      />
      <Card flush>
        <DataTable
          caption="Справочник цветов"
          columns={columns}
          rows={list.data}
          rowKey={(row) => row.id}
          loading={!list.data && list.status !== 'error'}
          error={list.error}
          onRetry={list.reload}
          empty={
            <EmptyState
              icon="tag"
              title="Цветов нет"
              description="Добавьте цвета, чтобы назначать их товарам."
              compact
            />
          }
        />
      </Card>
      {open ? (
        <ColorDialog
          color={open === 'new' ? null : open}
          onClose={() => setOpen(null)}
          onSaved={() => {
            setOpen(null);
            list.reload();
          }}
        />
      ) : null}
    </>
  );
}

function ColorDialog({
  color,
  onClose,
  onSaved,
}: {
  color: Color | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const creating = color === null;
  const [name, setName] = useState(color?.name ?? '');
  const [code, setCode] = useState(color?.code ?? '');
  const [hex, setHex] = useState(color?.hex ?? '#000000');
  const [sortOrder, setSortOrder] = useState(String(color?.sort_order ?? 0));
  const [active, setActive] = useState(color?.is_active ?? true);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const local: Record<string, string> = {};
    if (!name.trim()) local.name = 'Укажите название';
    if (creating && !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(code)) {
      local.code = 'Латиница в нижнем регистре, цифры и дефис';
    }
    if (!HEX.test(hex)) local.hex = 'Формат #RRGGBB';
    if (!/^\d+$/.test(sortOrder)) local.sort_order = 'Целое неотрицательное число';
    setErrors(local);
    if (Object.keys(local).length > 0) return;
    setSaving(true);
    try {
      const base = { name: name.trim(), hex, sort_order: Number(sortOrder), is_active: active };
      if (creating) {
        await colorsApi.create({ ...base, code });
        toast.success('Цвет создан', base.name);
      } else {
        await colorsApi.update(color.id, base);
        toast.success('Цвет сохранён', base.name);
      }
      onSaved();
    } catch (error) {
      const fields = extractFieldErrors(error);
      if ((error as { code?: string }).code === 'color_code_exists') {
        fields.code = 'Цвет с таким кодом уже есть';
      }
      setErrors(fields);
      toast.error(
        isForbidden(error)
          ? 'Нет права изменять цвета'
          : creating
            ? 'Цвет не создан'
            : 'Не сохранено',
        error,
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open
      onClose={onClose}
      busy={saving}
      title={creating ? 'Новый цвет' : `Цвет «${color.name}»`}
      description="Название и образец видит покупатель при выборе цвета на сайте."
    >
      <form className={styles.form} onSubmit={onSubmit} noValidate>
        <Field label="Название" required error={errors.name}>
          <Input
            maxLength={255}
            value={name}
            disabled={saving}
            onChange={(event) => {
              const next = event.target.value;
              // Код нового цвета идёт за названием, пока его не правили руками.
              if (creating && code === colorCodeFromName(name)) setCode(colorCodeFromName(next));
              setName(next);
            }}
          />
        </Field>
        <Field
          label="Код"
          required
          error={errors.code}
          hint={creating ? 'Уходит в заявки и не меняется после создания.' : 'Не меняется.'}
        >
          <Input
            className="mono"
            maxLength={200}
            value={code}
            disabled={!creating || saving}
            onChange={(event) => setCode(event.target.value)}
          />
        </Field>
        <Field label="Образец" required error={errors.hex}>
          <div className={styles.hexRow}>
            <input
              type="color"
              aria-label="Выбрать образец"
              className={styles.picker}
              value={HEX.test(hex) ? hex.toLowerCase() : '#000000'}
              disabled={saving}
              onChange={(event) => setHex(event.target.value)}
            />
            <Input
              className="mono"
              aria-label="Образец, #RRGGBB"
              maxLength={7}
              value={hex}
              disabled={saving}
              onChange={(event) => setHex(event.target.value)}
            />
          </div>
        </Field>
        <Field label="Порядок" error={errors.sort_order} hint="Меньше — выше в списке.">
          <Input
            inputMode="numeric"
            value={sortOrder}
            disabled={saving}
            onChange={(event) => setSortOrder(event.target.value)}
          />
        </Field>
        <Switch
          label="Активен"
          description="Отключённый цвет пропадает с сайта, но остаётся в заявках."
          checked={active}
          disabled={saving}
          onChange={(event) => setActive(event.target.checked)}
        />
        <div className={styles.actions}>
          <Button variant="ghost" disabled={saving} onClick={onClose}>
            Отмена
          </Button>
          <Button type="submit" variant="primary" loading={saving}>
            {creating ? 'Создать' : 'Сохранить'}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
