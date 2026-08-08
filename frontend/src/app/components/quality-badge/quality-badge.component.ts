import { Component, Input } from '@angular/core';
import { NgIf, NgFor } from '@angular/common';
import { Flag } from '../../models';

export interface BadgeFlag {
  rule_id: string;
  count?: number;
  description?: string;
  severity?: string | null;
}

const RULE_DESCRIPTIONS: Record<string, string> = {
  missing_value: 'Required field (value or event_timestamp) is missing on this row',
  duplicate: 'Identical event (same patient, type, subtype, timestamp, value) appears more than once',
  implausible_range: 'Value outside hardcoded plausible range (see PLAUSIBLE_RANGES in quality_rules.py)',
  temporal_misalignment: 'Event timestamp outside its encounter window by more than 2h (documentation-time lag)',
  chronology_violation: 'Discharge time precedes admission time (impossible chronology)',
  bp_relationship_invalid: 'Systolic lower than diastolic in the same reading',
};

@Component({
  selector: 'app-quality-badge',
  standalone: true,
  imports: [NgIf, NgFor],
  template: `
    <span
      class="badge"
      [class.has-tooltip]="flag || flags.length"
      [class.flip]="flip"
      [class.sev-minor]="flag?.severity === 'minor'"
      [class.sev-moderate]="flag?.severity === 'moderate'"
      [class.sev-severe]="flag?.severity === 'severe'"
      *ngIf="count > 0"
      role="img"
      [attr.aria-label]="tooltipLabel"
      (mouseenter)="onHover($event)"
    >
      <i class="ph ph-warning" aria-hidden="true"></i>
      <ng-container *ngIf="!flag">DQ · {{ count }}</ng-container>
      <ng-container *ngIf="flag">DQ · {{ ruleLabel(flag.rule_id) }}<span *ngIf="flag.severity" class="sev"> · {{ flag.severity }}</span></ng-container>

      <!-- single-flag tooltip (kept for callers passing one Flag) -->
      <span class="tooltip" *ngIf="flag">{{ flag.description }}</span>

      <!-- multi-flag tooltip: one line per rule with count and reason -->
      <span class="tooltip multi" *ngIf="!flag && flags.length">
        <span class="tip-line" *ngFor="let f of flags">
          <span class="tip-head">{{ ruleLabel(f.rule_id) }}<span *ngIf="f.count && f.count > 1" class="tip-count"> ×{{ f.count }}</span></span>
          <span class="tip-desc">{{ f.description || ruleDescription(f.rule_id) }}</span>
        </span>
      </span>
    </span>
  `,
  styles: [`
    .badge {
      position: relative;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      padding: 2px 9px;
      border-radius: var(--r-pill);
      background: var(--dq-soft);
      color: var(--dq);
      border: 1px solid var(--dq);
      font-size: 10.5px;
      font-weight: 600;
      letter-spacing: 0.02em;
      font-family: var(--font-mono);
      cursor: default;
      white-space: nowrap;
      flex-shrink: 0;
    }
    .badge i { font-size: 11px; }

    /* severity tiers: minor = subtle outline, moderate = default, severe = filled */
    .badge.sev-minor {
      background: transparent;
      border: 1px solid var(--border-strong);
      color: var(--ink-3);
      opacity: 0.85;
    }
    .badge.sev-severe {
      background: var(--warn);
      border-color: var(--warn);
      color: var(--warn-ink, var(--bg));
    }
    .sev { opacity: 0.85; }

    .has-tooltip:hover .tooltip {
      opacity: 1;
      pointer-events: auto;
      transform: translateY(0);
    }
    /* flip below the badge when there is no room above (rows near the top of the viewport) */
    .badge.flip .tooltip {
      bottom: auto;
      top: calc(100% + 8px);
    }
    .badge.flip .tooltip::after {
      top: auto;
      bottom: 100%;
      border-top-color: transparent;
      border-bottom-color: var(--ink);
    }
    .tooltip {
      position: absolute;
      bottom: calc(100% + 8px);
      left: auto;
      right: 0;
      width: 280px;
      max-width: calc(100vw - 16px);
      padding: 9px 11px;
      background: var(--ink);
      color: var(--bg);
      border-radius: var(--r-8);
      font-weight: 400;
      font-family: var(--font-sans);
      font-size: 11.5px;
      line-height: 1.5;
      white-space: normal;
      overflow-wrap: break-word;
      opacity: 0;
      pointer-events: none;
      transform: translateY(3px);
      transition: opacity var(--d-fast) var(--ease), transform var(--d-fast) var(--ease);
      z-index: 60;
      box-shadow: var(--shadow-2);
    }
    .tooltip.multi { width: 320px; max-width: calc(100vw - 16px); display: flex; flex-direction: column; gap: 7px; }
    .tooltip::after {
      content: '';
      position: absolute;
      top: 100%;
      right: 16px;
      left: auto;
      border: 5px solid transparent;
      border-top-color: var(--ink);
    }
    .tip-line { display: flex; flex-direction: column; gap: 1px; }
    .tip-head { font-weight: 600; font-family: var(--font-mono); font-size: 11px; }
    .tip-count { color: var(--accent); }
    .tip-desc { font-size: 11px; opacity: 0.85; }
  `],
})
export class QualityBadgeComponent {
  @Input() count = 0;
  @Input() flag: Flag | null = null;
  @Input() flags: BadgeFlag[] = [];

  flip = false;

  onHover(event: Event): void {
    const badge = event.currentTarget as HTMLElement;
    const tip = badge.querySelector('.tooltip') as HTMLElement | null;
    if (!tip) return;
    this.flip = tip.getBoundingClientRect().top < 12;
  }

  get tooltipLabel(): string {
    if (this.flags.length && !this.flag) {
      return this.flags
        .map((f) => `${this.ruleLabel(f.rule_id)}${f.count && f.count > 1 ? ` x${f.count}` : ''}: ${f.description || this.ruleDescription(f.rule_id)}`)
        .join('; ');
    }
    return this.flag
      ? `Data quality: ${this.ruleLabel(this.flag.rule_id)} — ${this.flag.description}`
      : `${this.count} quality flags`;
  }

  ruleLabel(rule: string): string {
    const map: Record<string, string> = {
      missing_value: 'missing value',
      duplicate: 'duplicate',
      implausible_range: 'implausible',
      temporal_misalignment: 'temporal',
      chronology_violation: 'chronology',
      bp_relationship_invalid: 'bp pair',
    };
    return map[rule] ?? rule;
  }

  ruleDescription(rule: string): string {
    return RULE_DESCRIPTIONS[rule] ?? 'Data quality flag';
  }
}
