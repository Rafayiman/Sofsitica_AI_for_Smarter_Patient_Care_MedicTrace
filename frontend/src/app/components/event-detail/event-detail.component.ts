import { Component, Input, OnChanges, Output, EventEmitter, SimpleChanges, HostListener } from '@angular/core';
import { NgIf, NgFor } from '@angular/common';
import { ApiService } from '../../services/api.service';
import { EventGroup, RawEvent, GroupExpandResponse } from '../../models';
import { QualityBadgeComponent } from '../quality-badge/quality-badge.component';

@Component({
  selector: 'app-event-detail',
  standalone: true,
  imports: [NgIf, NgFor, QualityBadgeComponent],
  template: `
    <div class="backdrop" (click)="close()">
      <div class="modal" role="dialog" aria-modal="true" (click)="$event.stopPropagation()">
        <div class="head">
          <div>
            <div class="title">{{ group.event_subtype || group.event_type }}</div>
            <div class="sub">
              {{ group.date }} · {{ group.event_type }} ·
              <span class="mono">{{ group.source_table }}</span>
              <span *ngIf="group.encounter_id" class="mono"> · {{ group.encounter_id }}</span>
              <span class="mono"> · {{ expanded?.event_count }} row(s)</span>
              <span *ngIf="groupSummary" class="sum"> · {{ groupSummary }}</span>
              <span *ngIf="flaggedRows" class="warn-txt"> · {{ flaggedRows }} flagged</span>
            </div>
          </div>
          <button class="x" (click)="close()" aria-label="Close">
            <i class="ph ph-x" aria-hidden="true"></i>
          </button>
        </div>

        <div *ngIf="loading" class="center loading" aria-label="Loading source rows">
          <span class="bar"></span><span class="bar"></span><span class="bar short"></span>
        </div>

        <table *ngIf="!loading && expanded" class="rows">
          <thead>
            <tr>
              <th>Time</th>
              <th>Value</th>
              <th>Unit</th>
              <th>Source</th>
              <th>Quality</th>
            </tr>
          </thead>
          <tbody>
            <tr *ngFor="let ev of expanded.events" class="row">
              <td class="mono nowrap">{{ ev.event_timestamp.replace('T', ' ') }}</td>
              <td>
                <span *ngIf="!isMissing(ev.value)">{{ ev.value }}</span>
                <ng-container *ngIf="isMissing(ev.value)">
                  <span class="missing">missing</span>
                  <span *ngIf="ev.value_numeric !== null" class="hint"> · numeric {{ ev.value_numeric }}</span>
                </ng-container>
              </td>
              <td class="muted">{{ ev.unit || '—' }}</td>
              <td class="mono muted">
                {{ ev.source_table }}.<span class="rowid">{{ ev.source_row_id }}</span>
              </td>
              <td>
                <app-quality-badge *ngIf="ev.flags.length" [count]="ev.flags.length" [flags]="ev.flags"></app-quality-badge>
                <span *ngIf="!ev.flags.length" class="muted">—</span>
              </td>
            </tr>
          </tbody>
        </table>

        <div *ngIf="!loading && expanded && !expanded.events.length" class="center muted">
          No raw rows found.
        </div>
      </div>
    </div>
  `,
  styles: [`
    .backdrop {
      position: fixed;
      inset: 0;
      background: rgba(10, 12, 16, 0.5);
      backdrop-filter: blur(3px);
      z-index: 40;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
      animation: fade var(--d-fast) ease;
    }
    @media (prefers-reduced-transparency: reduce) {
      .backdrop { backdrop-filter: none; }
    }
    @keyframes fade { from { opacity: 0 } to { opacity: 1 } }

    .modal {
      width: min(860px, 94vw);
      max-height: 82vh;
      overflow: auto;
      background: var(--surface);
      border-radius: var(--r-14);
      border: 1px solid var(--border-strong);
      box-shadow: var(--shadow-modal);
      animation: rise var(--d-med) var(--ease);
    }
    @keyframes rise {
      from { transform: translateY(16px) scale(0.985); opacity: 0; }
      to { transform: none; opacity: 1; }
    }

    .head {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      padding: 16px 20px;
      border-bottom: 1px solid var(--border-subtle);
      position: sticky;
      top: 0;
      background: var(--surface);
      z-index: 1;
    }
    .title { font-size: 16px; font-weight: 600; color: var(--ink); }
    .sub { font-size: 12px; color: var(--ink-3); margin-top: 3px; font-variant-numeric: tabular-nums; }

    .x {
      display: grid;
      place-items: center;
      width: 30px;
      height: 30px;
      border: none;
      background: var(--surface-elev);
      color: var(--ink-3);
      border-radius: var(--r-8);
      cursor: pointer;
      font-size: 15px;
      transition: color var(--d-fast) var(--ease), background var(--d-fast) var(--ease), transform var(--d-fast) var(--ease);
    }
    .x:hover { background: var(--surface-sunken); color: var(--ink); }
    .x:active { transform: scale(0.93); }

    .rows { width: 100%; border-collapse: collapse; font-size: 12.5px; }
    .rows th {
      text-align: left;
      padding: 8px 20px;
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--ink-4);
      font-weight: 600;
      border-bottom: 1px solid var(--border-subtle);
      position: sticky;
      top: 65px;
      background: var(--surface);
      z-index: 1;
    }
    .rows td { padding: 7px 20px; border-bottom: 1px solid var(--border-subtle); vertical-align: top; }
    .row { transition: background var(--d-fast) var(--ease); }
    .row:hover td { background: var(--surface-elev); }

    .mono { font-family: var(--font-mono); font-size: 11.5px; }
    .rowid { color: var(--accent); }
    .nowrap { white-space: nowrap; }
    .muted { color: var(--ink-4); }
    .sum { color: var(--accent); font-weight: 600; font-variant-numeric: tabular-nums; }
    .warn-txt { color: var(--warn); font-weight: 600; }
    .missing { color: var(--warn); font-weight: 600; }
    .hint { color: var(--ink-4); font-size: 11px; font-family: var(--font-mono); }
    .center { padding: 30px 20px; text-align: center; }

    .loading { display: flex; flex-direction: column; gap: 9px; align-items: center; }
    .loading .bar {
      width: 86%;
      height: 12px;
      border-radius: 5px;
      background: var(--surface-sunken);
      animation: pulse 1.4s var(--ease) infinite;
    }
    .loading .bar.short { width: 60%; animation-delay: 0.12s; }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
  `],
})
export class EventDetailComponent implements OnChanges {
  @Input() group!: EventGroup;
  @Input() patientId = '';
  @Output() closed = new EventEmitter<void>();

  expanded: GroupExpandResponse | null = null;
  loading = false;

  get groupSummary(): string {
    const g = this.group;
    if (!g) return '';
    if (g.value !== null && g.value !== undefined) return `${g.value}${g.unit ? ' ' + g.unit : ''}`;
    if (g.summary) {
      if (g.summary.kind === 'numeric') {
        const min = g.summary.min;
        const max = g.summary.max;
        const v = min === max ? String(min) : `${min}–${max}`;
        return `${v}${g.unit ? ' ' + g.unit : ''}`;
      }
      return `mode “${g.summary.mode}” ×${g.summary.mode_count}`;
    }
    return '';
  }

  get flaggedRows(): number {
    return this.expanded?.events.filter((e) => e.flags.length).length ?? 0;
  }

  isMissing(v: string | null | undefined): boolean {
    if (v === null || v === undefined) return true;
    const t = v.trim().toLowerCase();
    return ['___', '', 'unknown', 'n/a', 'na', 'none', '-', 'null', 'nan'].includes(t);
  }

  constructor(private api: ApiService) {}

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['group'] && this.group) {
      this.open();
    }
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    this.close();
  }

  close(): void {
    this.closed.emit();
  }

  open(): void {
    this.loading = true;
    this.api.expandGroup(this.patientId, this.group).subscribe({
      next: (res) => {
        this.expanded = res;
        this.loading = false;
      },
      error: () => {
        this.loading = false;
        this.expanded = { patient_id: this.patientId, event_count: 0, events: [] };
      },
    });
  }
}
