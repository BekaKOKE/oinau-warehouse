import { EnumBadge } from '@/components/ui/Badge';
import { Icon } from '@/components/ui/Icon';
import type { RequestStatusHistoryEntry } from '@/lib/api/types';
import { formatDateTime } from '@/lib/format';
import { REQUEST_STATUS } from '@/lib/labels';

import styles from './RequestDetail.module.css';

/** История статусов: хронологически, первая запись — создание заявки. */
export function RequestHistory({ entries }: { entries: readonly RequestStatusHistoryEntry[] }) {
  if (entries.length === 0) return <p className={styles.muted}>Истории пока нет.</p>;

  return (
    <ol className={styles.timeline}>
      {entries.map((entry) => (
        <li key={entry.id} className={styles.timelineItem}>
          <span className={styles.timelineDot} aria-hidden="true" />
          <div className={styles.timelineBody}>
            <div className={styles.timelineStatuses}>
              {entry.from_status ? (
                <>
                  <EnumBadge value={entry.from_status} meta={REQUEST_STATUS} />
                  <Icon name="arrowRight" size={14} aria-label="→" />
                  <EnumBadge value={entry.to_status} meta={REQUEST_STATUS} />
                </>
              ) : (
                <>
                  <span className={styles.strong}>Заявка создана</span>
                  <EnumBadge value={entry.to_status} meta={REQUEST_STATUS} />
                </>
              )}
            </div>
            <p className={styles.muted}>
              <time dateTime={entry.created_at}>{formatDateTime(entry.created_at)}</time>
              {' · '}
              {entry.changed_by?.full_name ?? (entry.from_status ? 'Система' : 'Сайт')}
            </p>
            {entry.comment ? <p className={styles.historyComment}>{entry.comment}</p> : null}
          </div>
        </li>
      ))}
    </ol>
  );
}
