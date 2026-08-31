// Ported from hermes-agent `thread/changed-files-card.tsx` @ a9c783f2.
//
// Cursor-style "N files changed" summary closing out the newest assistant turn:
// one row per file it edited with that file's +/-, and a Review action opening
// the diff pane. A row click hands the path to the host — upstream calls
// `openReviewForPath` on its own store; this tier is embedded (iframe), so it
// emits a `pulse:open-file` CustomEvent the host can pick up, and does nothing
// invisible when no host is listening.

import { useMemo } from 'react';

import { deriveChangedFiles } from '../model/changed-files';
import { DiffCount } from './diff-lines';
import { cn } from '../lib/cn';

/** ~5 rows. A turn that rewrites twenty files should still read as one card in
 *  the transcript, not a wall the user has to scroll past to reach the composer. */
export const MAX_CHANGED_FILE_ROWS = 5;

export function emitOpenFile(path: string) {
  if (typeof window === 'undefined') {
    return;
  }

  window.dispatchEvent(new CustomEvent('pulse:open-file', { detail: { path } }));
}

export function ChangedFilesCard({
  parts,
  reviewAction,
}: {
  parts: readonly unknown[];
  /** Renders the "Review" affordance only if the host can act on it. */
  reviewAction?: (path: string) => void;
}) {
  const files = useMemo(() => deriveChangedFiles(parts), [parts]);

  if (files.length === 0) {
    return null;
  }

  const shown = files.slice(0, MAX_CHANGED_FILE_ROWS);
  const hidden = files.length - shown.length;

  return (
    <div className="pulse-changed-files" data-slot="aui_changed-files">
      <div className="pulse-changed-files__head">
        <span className="pulse-changed-files__count">
          {files.length === 1 ? '1 file changed' : `${files.length} files changed`}
        </span>
        {reviewAction && (
          <button className="pulse-changed-files__review" onClick={() => reviewAction(files[0]!.path)} type="button">
            Review changes
          </button>
        )}
      </div>
      <ul className="pulse-changed-files__list">
        {shown.map(file => (
          <li key={file.path}>
            <button
              className="pulse-changed-files__row"
              onClick={() => {
                emitOpenFile(file.path);
                reviewAction?.(file.path);
              }}
              title={file.path}
              type="button"
            >
              <span className="pulse-changed-files__name">{file.name}</span>
              <DiffCount added={file.added} className="pulse-changed-files__stats" removed={file.removed} />
            </button>
          </li>
        ))}
      </ul>
      {hidden > 0 && <p className={cn('pulse-changed-files__more')}>{`and ${hidden} more`}</p>}
    </div>
  );
}
