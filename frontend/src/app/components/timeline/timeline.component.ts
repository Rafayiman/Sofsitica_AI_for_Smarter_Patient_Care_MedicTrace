import { Component, Input, OnChanges, AfterViewInit, OnDestroy, SimpleChanges, ViewChildren, QueryList, ElementRef } from '@angular/core';
import { NgIf, NgFor } from '@angular/common';
import { Subscription } from 'rxjs';
import { TimelineDay, EventGroup, GroupSummary } from '../../models';
import { EventDetailComponent } from '../event-detail/event-detail.component';
import { QualityBadgeComponent } from '../quality-badge/quality-badge.component';

const TYPE_LABELS: Record<string, string> = {
  lab: 'Lab',
  medication: 'Medication',
  diagnosis: 'Diagnosis',
  procedure: 'Procedure',
  icu_procedure: 'ICU procedure',
  transfer: 'Transfer',
  icu_observation: 'ICU observation',
  icu_stay: 'ICU stay',
  admission: 'Admission',
  measurement: 'Measurement',
};

const TYPE_VARS: Record<string, string> = {
  lab: 'var(--c-lab)',
  medication: 'var(--c-med)',
  diagnosis: 'var(--c-dx)',
  procedure: 'var(--c-proc)',
  icu_procedure: 'var(--c-proc)',
  transfer: 'var(--c-transfer)',
  icu_observation: 'var(--c-icu-obs)',
  icu_stay: 'var(--c-icu-stay)',
  admission: 'var(--c-adm)',
  measurement: 'var(--c-meas)',
};

@Component({
  selector: 'app-timeline',
  standalone: true,
  imports: [NgIf, NgFor, EventDetailComponent, QualityBadgeComponent],
  template: `
    <div class="timeline">
      <aside class="rail" *ngIf="days.length > 1" aria-label="Jump to timeline day">
        <div class="rail-track">
          <input
            id="day-jump"
            class="jump-slider"
            type="range"
            [min]="1"
            [max]="days.length"
            [value]="jumpDay"
            (input)="onJump($event)"
            (change)="onJumpCommit()"
            (pointerup)="endDrag()"
            (keyup)="endDrag()"
            aria-label="Jump to timeline day"
          />
          <div class="rail-ticks" *ngIf="tickMarks.length">
            <span
              class="tick"
              *ngFor="let t of tickMarks"
              [class.cur]="t.major && t.d === jumpDay"
              [class.minor]="!t.major"
              [style.bottom]="t.bottomPct + '%'"
              (click)="jumpToDay(t.d)"
              role="button"
              tabindex="0"
              (keydown.enter)="jumpToDay(t.d)"
              [title]="'Day ' + t.d + ' — ' + t.full"
              [attr.aria-label]="'Jump to day ' + t.d + ' — ' + t.full"
            >
              <i class="tick-line" aria-hidden="true"></i>
              <span class="tick-label" *ngIf="t.major">{{ t.label }}</span>
            </span>
          </div>
          <i class="rail-pos" *ngIf="tickMarks.length" [style.bottom]="posPct() + '%'" aria-hidden="true"></i>
        </div>
        <span class="rail-info" aria-live="polite">
          Day {{ jumpDay }}/{{ days.length }}<span *ngIf="jumpDay <= days.length" class="rail-date"><br />{{ days[jumpDay - 1].date }}</span>
        </span>
      </aside>

      <div class="days">
      <section *ngFor="let day of days; let di = index" class="day" #dayEl [class.flash]="flashIdx === di" [style.scroll-margin-top]="'74px'">
        <div class="day-head">
          <span class="day-num">Day {{ di + 1 }}</span>
          <span class="day-date">{{ day.date }}</span>
          <span class="day-count" [title]="'Event groups on this day'">{{ day.groups.length }} groups</span>
        </div>

        <div class="day-body">
          <div
            *ngFor="let g of day.groups; let gi = index"
            class="group"
            [style.--i]="gi % 6"
            (click)="onGroupClick(g)"
            role="button"
            tabindex="0"
            (keydown.enter)="onGroupClick(g)"
          >
            <span class="gutter" [style.background]="color(g.event_type)"></span>
            <span class="type" [style.color]="color(g.event_type)">{{ typeLabel(g.event_type) }}</span>
            <span class="name">
              {{ g.event_subtype || typeLabel(g.event_type) }}
              <span *ngIf="!g.event_subtype" class="no-label">no label</span>
            </span>
            <span class="value">
              <ng-container *ngIf="displayValue(g) !== null">
                {{ displayValue(g) }}<span *ngIf="g.unit" class="unit">{{ g.unit }}</span>
              </ng-container>
              <ng-container *ngIf="displayValue(g) === null" class="muted">—</ng-container>
            </span>
            <span *ngIf="g.summary" class="summary">{{ summaryText(g.summary) }}</span>
            <span *ngIf="g.count > 1" class="count">{{ g.count }}×</span>
            <app-quality-badge *ngIf="g.flags.length" [count]="flagTotal(g)" [flags]="g.flags"></app-quality-badge>
            <i class="ph ph-caret-right caret" aria-hidden="true"></i>
          </div>
        </div>
      </section>
      <div *ngIf="!days.length" class="empty">
        <i class="ph ph-rows" aria-hidden="true"></i>
        <p>No events for this patient.</p>
      </div>
      </div>
    </div>

    <app-event-detail
      *ngIf="detail"
      [group]="detail"
      [patientId]="patientId"
      (closed)="detail = null"
    ></app-event-detail>
  `,
  styles: [`
        .timeline { display: flex; gap: 18px; align-items: flex-start; }
    .days { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 30px; }

    /* vertical day-jump rail — sticky on the left, always visible while scrolling */
    .rail {
      position: sticky;
      top: 74px;
      flex: 0 0 74px;
      height: calc(100vh - 104px);
      min-height: 180px;
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
      padding: 10px 0 8px;
      background: var(--surface);
      border: 1px solid var(--border-subtle);
      border-radius: var(--r-12);
    }
    .rail-track {
      position: relative;
      flex: 1;
      width: 22px;
      min-height: 100px;
    }
    .jump-slider {
      writing-mode: vertical-lr;
      direction: ltr;
      width: 22px;
      height: 100%;
      margin: 0;
      accent-color: var(--accent);
      cursor: pointer;
    }
    .rail-ticks {
      position: absolute;
      inset: 9px 0;
      pointer-events: none;
    }
    .tick {
      position: absolute;
      left: 0;
      transform: translateY(50%);
      display: flex;
      align-items: center;
      gap: 5px;
      cursor: pointer;
      padding: 1px 3px;
      border-radius: 4px;
      transition: background var(--d-fast) var(--ease), color var(--d-fast) var(--ease);
    }
    .tick.major { pointer-events: auto; }
    .tick.major:hover { background: var(--accent-soft); }
    .tick-line {
      width: 6px;
      height: 2px;
      border-radius: 2px;
      background: var(--ink-4);
      flex-shrink: 0;
    }
    .tick.minor .tick-line { width: 5px; height: 2px; background: var(--ink-5); }
    .tick.major .tick-line { width: 7px; height: 3px; background: var(--ink-2); }
    .tick.cur .tick-line { background: var(--accent); height: 3px; width: 8px; }
    .tick-label {
      font-family: var(--font-mono);
      font-size: 9.5px;
      color: var(--ink-2);
      white-space: nowrap;
    }
    .tick.cur .tick-label { color: var(--accent); font-weight: 700; }

    /* hairline showing the current day; always visible even between labels */
    .rail-pos {
      position: absolute;
      left: 0;
      right: 0;
      height: 2px;
      border-radius: 2px;
      background: var(--accent);
      transform: translateY(50%);
      pointer-events: none;
      transition: bottom 120ms linear;
      z-index: 2;
    }

    .rail-info {
      font-family: var(--font-mono);
      font-size: 10px;
      color: var(--ink-2);
      text-align: center;
      line-height: 1.4;
      font-variant-numeric: tabular-nums;
    }
    .rail-date {
      color: var(--ink-3);
      font-size: 8.5px;
    }

/* flash highlight when a day is jumped to */
    .day.flash {
      animation: flash-hl 1.6s var(--ease) both;
    }
    @keyframes flash-hl {
      0% { box-shadow: 0 0 0 4px var(--accent-ring), var(--shadow-1); border-radius: var(--r-12); }
      100% { box-shadow: none; }
    }

    .day-head {
      display: flex;
      align-items: baseline;
      gap: 10px;
      margin-bottom: 10px;
    }
    .day-num {
      font-family: var(--font-mono);
      font-size: 10.5px;
      font-weight: 600;
      letter-spacing: 0.09em;
      text-transform: uppercase;
      color: var(--accent);
      background: var(--accent-soft);
      border: 1px solid var(--accent-ring);
      border-radius: 5px;
      padding: 2px 7px;
    }
    .day-date {
      font-size: 14.5px;
      font-weight: 600;
      color: var(--ink);
      font-variant-numeric: tabular-nums;
    }
    .day-count { font-size: 11px; color: var(--ink-4); font-family: var(--font-mono); }

    .day-body {
      border-left: 2px solid var(--border-strong);
      margin-left: 9px;
      padding-left: 16px;
      display: flex;
      flex-direction: column;
      gap: 5px;
    }

    .group {
      display: flex;
      align-items: center;
      gap: 11px;
      padding: 7px 12px;
      border-radius: var(--r-8);
      background: var(--surface);
      border: 1px solid var(--border-subtle);
      min-width: 0;
      cursor: pointer;
      transition: border-color var(--d-fast) var(--ease),
        transform var(--d-fast) var(--ease),
        box-shadow var(--d-fast) var(--ease),
        background var(--d-fast) var(--ease);
      animation: rise var(--d-slow) var(--ease) both;
      animation-delay: calc(var(--i) * 0.04s);
    }
    .group:hover {
      border-color: var(--border-strong);
      background: var(--surface-elev);
      transform: translateX(2px);
      box-shadow: var(--shadow-1);
    }
    .group:active { transform: scale(0.99); }

    @keyframes rise {
      from { opacity: 0; transform: translateY(6px); }
      to { opacity: 1; transform: none; }
    }

    .gutter { width: 4px; align-self: stretch; border-radius: 3px; flex-shrink: 0; }

    .type {
      font-size: 10px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      min-width: 92px;
      flex-shrink: 0;
    }

    .name {
      font-size: 13px;
      color: var(--ink);
      font-weight: 500;
      min-width: 170px;
      max-width: 240px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .no-label {
      font-size: 10px;
      color: var(--ink-4);
      margin-left: 6px;
      font-weight: 400;
      font-family: var(--font-mono);
    }

    .value {
      font-size: 13px;
      color: var(--accent);
      font-weight: 600;
      font-variant-numeric: tabular-nums;
      min-width: 0;
      max-width: 150px;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .unit { font-size: 11px; color: var(--ink-4); font-weight: 400; margin-left: 3px; }

    .summary {
      font-size: 11px;
      color: var(--ink-3);
      margin-left: auto;
      white-space: nowrap;
      font-variant-numeric: tabular-nums;
      min-width: 0;
      max-width: 220px;
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .count {
      font-size: 10.5px;
      font-weight: 600;
      color: var(--ink-3);
      background: var(--surface-sunken);
      border: 1px solid var(--border-subtle);
      border-radius: 4px;
      padding: 1px 6px;
      font-family: var(--font-mono);
      flex-shrink: 0;
    }

    .caret { color: var(--ink-5); font-size: 14px; flex-shrink: 0; }
    .group:hover .caret { color: var(--ink-3); }

    .muted { color: var(--ink-5); }

    .empty {
      color: var(--ink-4);
      padding: 40px 24px;
      text-align: center;
      background: var(--surface);
      border: 1px dashed var(--border-strong);
      border-radius: var(--r-12);
    }
    .empty i { font-size: 22px; }
    .empty p { margin: 8px 0 0; font-size: 13px; }
  `],
})
export class TimelineComponent implements OnChanges, AfterViewInit, OnDestroy {
  @Input() days: TimelineDay[] = [];
  @Input() patientId = '';

  detail: EventGroup | null = null;

  jumpDay = 1;
  flashIdx = -1;
  private flashTimer: number | undefined;
  @ViewChildren('dayEl') dayEls: QueryList<ElementRef<HTMLElement>> | null = null;

  private scrollRaf = 0;
  private dragging = false;
  private elsSub: Subscription | undefined;
  private readonly trackBand = 74;

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['days']) {
      this.jumpDay = 1;
      this.flashIdx = -1;
      this.scrollTop();
    }
  }

  /** Always start a freshly rendered timeline at the top of the page. */
  private scrollTop(): void {
    window.scrollTo({ top: 0, behavior: 'auto' });
  }

  /**
   * A tick for EVERY day — a thin unlabeled ruler line so the stay's length
   * and density stay visible — plus labeled (major) ticks sampled so at most
   * ~12 fit the rail: stride = ceil((n-1)/12), with D1 and D{n} always
   * labeled. The exact position is shown by .rail-pos and the readout.
   */
  get tickMarks(): { d: number; bottomPct: number; label: string; full: string; major: boolean }[] {
    const n = this.days.length;
    if (n <= 1) return [];
    const stride = Math.max(1, Math.ceil((n - 1) / 12));
    const marks: { d: number; bottomPct: number; label: string; full: string; major: boolean }[] = [];
    for (let d = 1; d <= n; d++) {
      const major = (d - 1) % stride === 0 || d === 1 || d === n;
      marks.push({ d, bottomPct: ((n - d) / (n - 1)) * 100, label: `D${d}`, full: this.days[d - 1].date, major });
    }
    return marks;
  }

  posPct(): number {
    const n = this.days.length;
    if (n <= 1) return 0;
    return ((n - this.jumpDay) / (n - 1)) * 100;
  }

  jumpToDay(d: number): void {
    if (!Number.isInteger(d) || d < 1 || d > this.days.length) return;
    this.jumpDay = d;
    this.onJumpCommit();
  }

  onJump(event: Event): void {
    const v = Number((event.target as HTMLInputElement).value);
    if (!Number.isInteger(v) || v < 1 || v > this.days.length) return;
    this.dragging = true;
    this.jumpDay = v;
    this.scrollToDay(v - 1, 'auto');
  }

  onJumpCommit(): void {
    this.dragging = false;
    this.scrollToDay(this.jumpDay - 1, 'smooth');
    this.flashIdx = this.jumpDay - 1;
    window.clearTimeout(this.flashTimer);
    this.flashTimer = window.setTimeout(() => (this.flashIdx = -1), 1700);
  }

  private scrollToDay(idx: number, behavior: ScrollBehavior): void {
    const el = this.dayEls?.get(idx)?.nativeElement;
    if (el) {
      el.scrollIntoView({ behavior, block: 'start' });
    }
  }

  ngAfterViewInit(): void {
    window.addEventListener('scroll', this.onWindowScroll, { passive: true });
    this.elsSub = this.dayEls?.changes.subscribe(() => this.scheduleTrack());
    this.scheduleTrack();
    this.scrollTop();
  }

  ngOnDestroy(): void {
    window.removeEventListener('scroll', this.onWindowScroll);
    this.elsSub?.unsubscribe();
    if (this.scrollRaf) cancelAnimationFrame(this.scrollRaf);
  }

  private onWindowScroll = (): void => {
    this.scheduleTrack();
  };

  private scheduleTrack(): void {
    if (this.scrollRaf) return;
    this.scrollRaf = requestAnimationFrame(() => {
      this.scrollRaf = 0;
      this.trackScroll();
    });
  }

  /**
   * Keep the rail in sync with free scrolling: the active day is the last one
   * whose top edge has crossed the topbar line. Updates are suppressed while
   * the slider is being dragged so the thumb never fights the finger.
   */
  private trackScroll(): void {
    if (this.dragging) return;
    const els = this.dayEls;
    if (!els || !els.length) return;
    let active = 0;
    els.forEach((el, i) => {
      if (el.nativeElement.getBoundingClientRect().top <= this.trackBand) active = i;
    });
    if (this.jumpDay !== active + 1) this.jumpDay = active + 1;
  }

  endDrag(): void {
    this.dragging = false;
    this.trackScroll();
  }

  typeLabel(t: string): string {
    return TYPE_LABELS[t] ?? t;
  }

  color(t: string): string {
    return TYPE_VARS[t] ?? 'var(--c-transfer)';
  }

  displayValue(g: EventGroup): string | null {
    if (g.value !== null && g.value !== undefined) return g.value;
    if (g.summary?.kind === 'numeric' && g.count === 1) return String(g.summary.min);
    if (g.summary?.kind === 'numeric' && g.count > 1) {
      return g.summary.min === g.summary.max ? String(g.summary.min) : `${g.summary.min}–${g.summary.max}`;
    }
    return null;
  }

  summaryText(s: GroupSummary): string {
    if (s.kind === 'numeric') {
      return `min ${s.min} · max ${s.max} · mean ${s.mean}`;
    }
    return `mode “${s.mode}” ×${s.mode_count}`;
  }

  flagTotal(g: EventGroup): number {
    return g.flags.reduce((a, f) => a + f.count, 0);
  }

  onGroupClick(g: EventGroup): void {
    this.detail = g;
  }
}
