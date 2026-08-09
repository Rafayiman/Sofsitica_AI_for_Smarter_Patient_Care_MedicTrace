import { Component, Input, OnInit } from '@angular/core';
import { NgIf, NgFor } from '@angular/common';
import { ApiService } from '../../services/api.service';
import { EvalReport, QualitySummary } from '../../models';

@Component({
  selector: 'app-dq-dashboard',
  standalone: true,
  imports: [NgIf, NgFor],
  template: `
    <div *ngIf="loading" class="dash skel" aria-label="Loading quality dashboard">
      <div class="s-head"></div>
      <div class="s-row"></div>
      <div class="s-row"></div>
      <div class="s-row"></div>
    </div>

    <div *ngIf="error" class="dash state-box err">{{ error }}</div>

    <div *ngIf="!loading && !error && summary" class="dash">
      <!-- scope tabs -->
      <div class="tabs" role="tablist" aria-label="Dashboard scope">
        <button
          class="tab"
          [class.on]="tab === 'overall'"
          (click)="setTab('overall')"
          role="tab"
          [attr.aria-selected]="tab === 'overall'"
        >
          Overall dataset
        </button>
        <button
          *ngIf="patientId"
          class="tab"
          [class.on]="tab === 'patient'"
          (click)="setTab('patient')"
          role="tab"
          [attr.aria-selected]="tab === 'patient'"
        >
          Patient MRN {{ patientId }}
        </button>
      </div>

      <div *ngIf="summary" class="scope-note" [class.muted]="!summary.patient_id">
        {{ summary.patient_id ? 'KPIs scoped to medical record number ' + summary.patient_id : 'KPIs computed across the whole ingested dataset' }}
      </div>

      <!-- KPI row -->
      <div class="kpis">
        <div class="kpi">
          <span class="kpi-num">{{ summary.total_events.toLocaleString() }}</span>
          <span class="kpi-lbl">unified events</span>
        </div>
        <div class="kpi">
          <span class="kpi-num">{{ summary.total_flags.toLocaleString() }}</span>
          <span class="kpi-lbl">quality flags</span>
        </div>
        <div class="kpi">
          <span class="kpi-num">{{ flagRate() }}</span>
          <span class="kpi-lbl">flag rate</span>
        </div>
      </div>

      <!-- Flags by rule -->
      <h3>Flags by rule</h3>
      <div class="table-scroll">
        <table class="dash-table">
          <thead>
            <tr><th>rule</th><th>minor</th><th>moderate</th><th>severe</th><th>total</th></tr>
          </thead>
          <tbody>
            <tr *ngFor="let r of summary.per_rule">
              <td class="mono">{{ r.rule_id }}</td>
              <td>{{ sev(r, 'minor') }}</td>
              <td>{{ sev(r, 'moderate') }}</td>
              <td>{{ sev(r, 'severe') }}</td>
              <td><b>{{ ruleTotal(r) }}</b></td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Coverage by source table -->
      <h3>Coverage by source table</h3>
      <div class="table-scroll">
        <table class="dash-table">
          <thead>
            <tr><th>source table</th><th class="num">rows</th><th class="num">flagged events</th><th class="num">flag rate</th></tr>
          </thead>
          <tbody>
            <tr *ngFor="let t of summary.per_table">
              <td class="mono">{{ t.source_table }}</td>
              <td class="num">{{ t.rows.toLocaleString() }}</td>
              <td class="num">{{ t.flagged_events.toLocaleString() }}</td>
              <td class="num">{{ pct(t.flagged_events, t.rows) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Unit variation -->
      <h3>Unit variation (subtypes with &gt;1 unit)</h3>
      <ul class="unit-list" *ngIf="summary.unit_variation.length">
        <li *ngFor="let u of summary.unit_variation" class="unit-item">
          <span class="mono">{{ u.event_subtype }}</span>
          <span class="unit-chips">
            <span class="chip" *ngFor="let unit of u.units">{{ unit }}</span>
          </span>
        </li>
      </ul>
      <div class="muted" *ngIf="!summary.unit_variation.length">No subtype appears with more than one distinct unit.</div>

      <p class="dash-note">
        Flags are additive and reversible — the source rows are never modified (SELECT-only read access).
        Structural rules (chronology, BP relationship) report 0 here because the demo subset contains
        no violating rows; their correctness is verified on seeded synthetic data in <code>eval/dq_quality.py</code>.
      </p>

      <!-- Eval & rubric evidence (overall tab only: engine-level, not patient-scoped) -->
      <div *ngIf="tab === 'overall'" class="eval">
        <h3>Eval &amp; rubric evidence</h3>

        <div *ngIf="evalLoading" class="muted">Loading eval report…</div>
        <div *ngIf="evalError" class="state-box err">{{ evalError }}</div>

        <div *ngIf="evalReport" class="eval-card">
          <div class="eval-top">
            <span class="eval-score"><b>{{ evalReport.passed }}</b>/{{ evalReport.total }}</span>
            <span class="eval-run">patient {{ evalReport.patient_id }} · {{ evalRunAt() }} · checks evidence-based</span>
          </div>

          <div class="eval-metrics">
            <div class="eval-metric" *ngFor="let ev of evalMetrics()">
              <span class="ev-label">{{ ev.label }}</span>
              <span class="ev-bar"><i [style.width]="ev.pct === 'n/a' ? '0%' : ev.pct"></i></span>
              <span class="ev-num">{{ ev.n }} / {{ ev.d }} · {{ ev.pct }}</span>
            </div>
          </div>

          <div class="eval-why">
            <b>What this is:</b> a 24-question automated evaluation of the grounded Q&amp;A engine
            (patient MRN {{ evalReport.patient_id }}; questions are hand-authored, labeled
            [SYNTHETIC], and kept separate from the dataset). Every check is evidence-based —
            response status + citation counts +, for the temporal question, the executed SQL —
            never wording matching.
            <br /><br />
            <b>Why it is displayed:</b> the challenge asks for named metrics in the evaluation
            report (AI &amp; Data Quality track) and an honest account of failures. The four
            measures above — fact, order, provenance, abstention — are that report, shown here
            so you can verify the Q&amp;A engine's claims directly from this dashboard, including
            that it refuses to answer unanswerable (u1–u4) and out-of-scope (c1–c4) questions.
            Full results and known limitations are in <code>EVAL.md</code>.
            <br /><br />
            <b>Caveats:</b> results are environment-dependent (Groq model/quota, this machine);
            latency below is supporting evidence only. Run <code>eval/run_eval.py</code> to refresh.
          </div>

          <button class="cites-toggle" (click)="evalOpen = !evalOpen">
            <i class="ph ph-caret-down" [class.rot]="evalOpen" aria-hidden="true"></i>
            {{ evalOpen ? 'Hide' : 'Show' }} per-question results ({{ evalReport.total }})
          </button>

          <div class="table-scroll">
            <table class="dash-table eval-table" *ngIf="evalOpen">
              <thead>
                <tr><th>#</th><th>category</th><th>question</th><th>status</th><th class="num">cites</th><th class="num">latency</th><th>verdict</th></tr>
              </thead>
              <tbody>
                <tr *ngFor="let q of evalReport.questions">
                  <td class="mono">{{ q.qid }}</td>
                  <td class="mono">{{ q.category }}</td>
                  <td class="ev-q">{{ q.question }}</td>
                  <td class="mono">{{ q.status }}</td>
                  <td class="num">{{ q.citations }}</td>
                  <td class="num">{{ q.latency_s }}s</td>
                  <td [class.ok]="q.pass" [class.bad]="!q.pass" class="ev-verdict"><b>{{ q.pass ? 'PASS' : 'FAIL' }}</b></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  `,
  styles: [
    `
    .dash { display: flex; flex-direction: column; gap: 6px; padding: 2px 0 20px; }

    .tabs { display: inline-flex; gap: 6px; }
    .tab {
      border: 1px solid var(--border-strong);
      background: var(--surface-elev);
      color: var(--ink-3);
      border-radius: var(--r-pill);
      padding: 6px 14px;
      font-size: 12px;
      font-weight: 600;
      font-family: var(--font-mono);
      cursor: pointer;
      transition: color var(--d-fast) var(--ease), border-color var(--d-fast) var(--ease),
        background var(--d-fast) var(--ease);
    }
    .tab:hover { color: var(--ink); border-color: var(--accent); }
    .tab.on { background: var(--accent-soft); color: var(--accent); border-color: var(--accent); }

    .scope-note { font-size: 11.5px; margin-top: 2px; color: var(--accent); font-family: var(--font-mono); }

    .kpis { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 14px; margin-bottom: 18px; }
    .kpi {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--r-12);
      padding: 14px 16px;
      display: flex;
      flex-direction: column;
      gap: 4px;
    }
    .kpi-num { font-size: 22px; font-weight: 700; font-family: var(--font-mono); color: var(--ink); letter-spacing: -0.02em; }
    .kpi-lbl { font-size: 11px; color: var(--ink-3); text-transform: uppercase; letter-spacing: 0.08em; }

    h3 {
      margin: 16px 0 8px;
      font-size: 12px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.1em;
      color: var(--ink-3);
    }

    .dash-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
    .table-scroll { overflow-x: auto; }
    .table-scroll .dash-table { min-width: 520px; }
    .table-scroll .eval-table { min-width: 720px; }
    .dash-table th {
      text-align: left;
      padding: 6px 10px;
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--ink-3);
      border-bottom: 1px solid var(--border);
    }
    .dash-table th.num { text-align: right; }
    .dash-table td {
      padding: 7px 10px;
      border-bottom: 1px solid var(--border-subtle);
      color: var(--ink-2);
    }
    .dash-table td.num { text-align: right; font-variant-numeric: tabular-nums; }
    .dash-table .mono { font-family: var(--font-mono); font-size: 12px; color: var(--ink); }
    .dash-table tr:hover td { background: var(--surface); }

    .unit-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
    .unit-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 7px 12px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--r-8);
      font-size: 12.5px;
      color: var(--ink-2);
    }
    .unit-item .mono { font-family: var(--font-mono); color: var(--ink); }
    .unit-chips { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
    .chip {
      font-family: var(--font-mono);
      font-size: 11px;
      color: var(--accent);
      background: var(--accent-soft, var(--surface-elev));
      border: 1px solid var(--accent);
      border-radius: var(--r-pill);
      padding: 2px 9px;
    }
    .muted { color: var(--ink-3); font-size: 12.5px; }

    .dash-note { margin-top: 18px; font-size: 11.5px; line-height: 1.6; color: var(--ink-3); max-width: 640px; }
    .dash-note code { font-family: var(--font-mono); color: var(--ink-2); }

    .eval { margin-top: 26px; border-top: 1px solid var(--border); padding-top: 4px; }
    .eval-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--r-12);
      padding: 14px 16px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .eval-top { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
    .eval-score { font-size: 26px; font-weight: 700; font-family: var(--font-mono); color: var(--ink); letter-spacing: -0.02em; }
    .eval-score b { color: var(--accent); }
    .eval-run { font-size: 11px; color: var(--ink-4); font-family: var(--font-mono); }

    .eval-metrics { display: flex; flex-direction: column; gap: 8px; }
    .eval-metric { display: grid; grid-template-columns: 230px 1fr 110px; gap: 12px; align-items: center; font-size: 12px; }
    .ev-label { color: var(--ink-2); font-weight: 500; }
    .ev-bar { height: 7px; background: var(--surface-sunken); border-radius: 4px; overflow: hidden; }
    .ev-bar i { display: block; height: 100%; background: var(--accent); border-radius: 4px; }
    .ev-num { font-family: var(--font-mono); font-size: 11.5px; color: var(--ink-3); text-align: right; font-variant-numeric: tabular-nums; }

    .eval-why { font-size: 11.5px; line-height: 1.6; color: var(--ink-3); max-width: 720px; }
    .eval-why b { color: var(--ink-2); }
    .eval-why code { font-family: var(--font-mono); color: var(--ink-2); }

    .cites-toggle {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      align-self: flex-start;
      border: none;
      background: none;
      color: var(--accent);
      font-size: 11.5px;
      font-weight: 600;
      font-family: var(--font-mono);
      cursor: pointer;
      padding: 3px 6px;
      border-radius: var(--r-6);
      transition: background var(--d-fast) var(--ease);
    }
    .cites-toggle:hover { background: var(--accent-soft); }
    .cites-toggle i { transition: transform var(--d-fast) var(--ease); }
    .cites-toggle i.rot { transform: rotate(180deg); }

    .eval-table .ev-q { color: var(--ink-3); font-size: 12px; max-width: 340px; }
    .ev-verdict b { font-size: 10.5px; font-family: var(--font-mono); letter-spacing: 0.04em; }
    .ev-verdict.ok b { color: var(--ok, var(--accent)); }
    .ev-verdict.bad b { color: var(--warn); }

    .skel { display: flex; flex-direction: column; gap: 14px; }
    .skel .s-head { width: 140px; height: 14px; border-radius: 4px; background: var(--surface-sunken); }
    .skel .s-row { height: 44px; border-radius: var(--r-8); background: var(--surface); border: 1px solid var(--border-subtle); animation: pulse 1.4s var(--ease) infinite; }
    .skel .s-row:nth-child(2) { animation-delay: 0.08s; }
    .skel .s-row:nth-child(3) { animation-delay: 0.16s; }
    .skel .s-row:nth-child(4) { animation-delay: 0.24s; }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.55; } }

    @media (max-width: 720px) { .kpis { grid-template-columns: 1fr; } .unit-item { flex-direction: column; align-items: flex-start; } }
    @media (max-width: 560px) {
      .eval-metric { grid-template-columns: 1fr; gap: 4px; }
      .ev-num { text-align: left; }
    }
    `,
  ],
})
export class DqDashboardComponent implements OnInit {
  @Input() patientId = '';

  tab: 'overall' | 'patient' = 'overall';
  summary: QualitySummary | null = null;
  loading = true;
  error = '';
  evalReport: EvalReport | null = null;
  evalLoading = true;
  evalError = '';
  evalOpen = false;

  constructor(private api: ApiService) {}

  ngOnInit(): void {
    this.load();
    this.loadEval();
  }

  setTab(t: 'overall' | 'patient'): void {
    if (t === this.tab) return;
    this.tab = t;
    this.load();
  }

  private load(): void {
    this.loading = true;
    this.error = '';
    this.summary = null;
    this.api.getQualitySummary(this.tab === 'patient' ? this.patientId : undefined).subscribe({
      next: (res) => {
        this.summary = res;
        this.loading = false;
      },
      error: () => {
        this.loading = false;
        this.error = 'Could not load the data quality dashboard from the backend.';
      },
    });
  }

  sev(rule: { severity_counts: { severity: string | null; count: number }[] }, s: string): number {
    return rule.severity_counts.find((sc) => sc.severity === s)?.count ?? 0;
  }

  ruleTotal(rule: { severity_counts: { severity: string | null; count: number }[] }): number {
    return rule.severity_counts.reduce((a, sc) => a + sc.count, 0);
  }

  flagRate(): string {
    if (!this.summary || this.summary.total_events === 0) return '—';
    return ((this.summary.total_flags / this.summary.total_events) * 100).toFixed(3) + '%';
  }

  pct(flagged: number, rows: number): string {
    if (rows === 0) return '—';
    return ((flagged / rows) * 100).toFixed(2) + '%';
  }

  private loadEval(): void {
    this.api.getEvalReport().subscribe({
      next: (r) => {
        this.evalReport = r;
        this.evalLoading = false;
      },
      error: (err) => {
        this.evalLoading = false;
        this.evalError =
          err.status === 404
            ? 'No eval report yet — run `.venv\\Scripts\\python ..\\eval\\run_eval.py` from backend/ to generate eval/report.json.'
            : 'Could not load the eval report from the backend.';
      },
    });
  }

  evalRunAt(): string {
    if (!this.evalReport) return '';
    return this.evalReport.generated_at.replace('T', ' ').slice(0, 19) + ' UTC';
  }

  evalMetrics(): { label: string; n: number; d: number; pct: string }[] {
    if (!this.evalReport) return [];
    const m = this.evalReport.metrics;
    const rows: [keyof typeof m, string][] = [
      ['fact', 'Structured-fact accuracy'],
      ['order', 'Temporal-order accuracy'],
      ['provenance', 'Source-provenance coverage'],
      ['abstention', 'Abstention accuracy'],
    ];
    return rows.map(([key, label]) => {
      const [n, d] = m[key];
      return { label, n, d, pct: d ? ((n / d) * 100).toFixed(0) + '%' : 'n/a' };
    });
  }
}
