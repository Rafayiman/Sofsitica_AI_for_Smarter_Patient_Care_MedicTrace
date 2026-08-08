import { Component } from '@angular/core';

@Component({
  selector: 'app-safety-banner',
  standalone: true,
  template: `
    <div class="safety-banner" role="note" aria-label="Safety notice">
      <i class="ph ph-shield-warning" aria-hidden="true"></i>
      <span>Research and educational prototype only. Not for clinical use. Do not use for diagnosis, treatment, triage, or emergency decisions.</span>
    </div>
  `,
  styles: [`
    .safety-banner {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 9px;
      padding: 5px 16px;
      background: var(--surface-sunken);
      color: var(--ink-3);
      border-bottom: 1px solid var(--border);
      font-size: 11px;
      font-family: var(--font-mono);
      letter-spacing: 0.01em;
      text-align: center;
    }
    .safety-banner i { font-size: 13px; color: var(--ink-4); flex-shrink: 0; }
    @media (max-width: 720px) {
      .safety-banner { font-size: 10px; padding: 5px 10px; }
    }
  `],
})
export class SafetyBannerComponent {}
