import { Component, Input, ViewChild, ElementRef, AfterViewChecked } from '@angular/core';
import { NgIf, NgFor, NgClass } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from '../../services/api.service';
import { AskResponse, Citation } from '../../models';

interface Message {
  question: string;
  response: AskResponse;
  citesAll: boolean;
}

@Component({
  selector: 'app-qa-panel',
  standalone: true,
  imports: [NgIf, NgFor, NgClass, FormsModule],
  template: `
    <div class="panel">
      <div class="panel-head">
        <span class="title">Grounded Q&amp;A</span>
        <span class="hint">SELECT-only · answers cite source rows · never answers from memory</span>
      </div>

      <div class="messages" #scroll>
        <div *ngIf="!messages.length && !loading" class="welcome">
          <i class="ph ph-chat-circle" aria-hidden="true"></i>
          <p>
            Ask about this patient's records, e.g.
            <em>“What medications were given?”</em> or <em>“Show my creatinine values.”</em>
            If the data cannot support an answer, the tool says so.
          </p>
        </div>

        <div *ngFor="let m of messages" class="msg">
          <div class="q">You</div>
          <div class="q-text">{{ m.question }}</div>
          <div class="a" [ngClass]="'a-' + m.response.status">
            <ng-container *ngIf="m.response.status === 'answered'">
              <div class="answer-text">
                <span class="chip ai">AI-generated summary</span>
                <p class="prose">{{ m.response.answer_summary }}</p>
              </div>
              <div *ngIf="m.response.citations.length" class="cites">
                <div class="cites-label">Source rows — traceable to the timeline above</div>
                <div *ngFor="let c of visibleCites(m)" class="cite">
                  <span class="cite-value" *ngIf="citeValue(c) !== null">{{ citeValue(c) }}</span>
                  <span class="cite-field">{{ c.field }}</span>
                  <span class="cite-table">{{ c.table }}</span>
                  <span class="cite-ts">{{ c.timestamp ? c.timestamp.replace('T', ' ') : '' }}</span>
                  <span class="cite-id">{{ c.event_id }}</span>
                </div>
                <button
                  *ngIf="m.response.citations.length > 6"
                  class="cites-toggle"
                  (click)="m.citesAll = !m.citesAll"
                >
                  <i class="ph ph-caret-down" [class.rot]="m.citesAll" aria-hidden="true"></i>
                  {{ m.citesAll ? 'Show fewer' : 'Show all ' + m.response.citations.length + ' records' }}
                </button>
              </div>
            </ng-container>

            <ng-container *ngIf="m.response.status === 'not_found'">
              <i class="nf-icon ph ph-question" aria-hidden="true"></i>
              <div class="nf-text">
                <div class="nf-title">Not found in the data</div>
                <div>{{ m.response.answer_summary }}</div>
                <div class="nf-sub">The tool only answers from actual rows in this patient's records — no guessing.</div>
              </div>
            </ng-container>

            <ng-container *ngIf="m.response.status === 'out_of_scope'">
              <i class="nf-icon ph ph-shield-warning" aria-hidden="true"></i>
              <div class="nf-text">
                <div class="nf-title">Out of scope</div>
                <div>{{ m.response.answer_summary }}</div>
                <div class="nf-sub">This tool answers factual questions about the structured record only — no clinical judgment.</div>
              </div>
            </ng-container>

            <ng-container *ngIf="m.response.status === 'error'">
              <i class="nf-icon warn ph ph-warning-circle" aria-hidden="true"></i>
              <div class="nf-text">
                <div class="nf-title">Could not answer</div>
                <div>{{ m.response.answer_summary }}</div>
                <button class="retry-btn" (click)="retry(m)" [disabled]="loading">Retry</button>
              </div>
            </ng-container>
          </div>
        </div>

        <div *ngIf="loading" class="msg">
          <div class="q-text">…</div>
          <div class="a a-loading">
            <span class="bar"></span>
            <span class="bar short"></span>
            <span class="bar"></span>
          </div>
        </div>
      </div>

      <form class="input-row" (ngSubmit)="send()">
        <input
          type="text"
          [(ngModel)]="text"
          name="question"
          placeholder="Ask about this patient's records…"
          autocomplete="off"
          [disabled]="loading"
          aria-label="Question"
        />
        <button type="submit" [disabled]="loading || !text.trim()">
          <i class="ph ph-paper-plane-tilt" aria-hidden="true"></i>
          <span>Ask</span>
        </button>
      </form>
    </div>
  `,
  styles: [`
    .panel {
      display: flex;
      flex-direction: column;
      height: 100%;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--r-12);
      box-shadow: var(--shadow-1);
      overflow: hidden;
    }
    .panel-head { padding: 13px 16px 11px; border-bottom: 1px solid var(--border-subtle); }
    .title { font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.1em; color: var(--ink-3); }
    .hint {
      display: block;
      margin-top: 4px;
      font-size: 11px;
      color: var(--ink-4);
      font-family: var(--font-mono);
    }

    .messages {
      flex: 1;
      overflow-y: auto;
      padding: 18px;
      display: flex;
      flex-direction: column;
      gap: 14px;
      min-height: 340px;
      background: var(--bg);
    }

    .welcome {
      color: var(--ink-3);
      font-size: 12.5px;
      line-height: 1.6;
      padding: 18px 14px;
      text-align: center;
      border: 1px dashed var(--border-strong);
      border-radius: var(--r-12);
    }
    .welcome i { font-size: 20px; color: var(--ink-4); }
    .welcome p { margin: 8px 0 0; }
    .welcome em { color: var(--accent); font-style: normal; }

    .msg { display: flex; flex-direction: column; gap: 5px; }
    .q {
      font-size: 10px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--ink-4);
    }
    .q-text {
      font-size: 13px;
      font-weight: 500;
      color: var(--ink-2);
      background: var(--surface-elev);
      border: 1px solid var(--border-subtle);
      border-radius: var(--r-8);
      padding: 7px 11px;
      align-self: flex-start;
      max-width: 92%;
    }

    .a {
      border-radius: var(--r-12);
      padding: 12px 14px;
      font-size: 13px;
      line-height: 1.55;
      animation: pop var(--d-med) var(--ease) both;
    }
    @keyframes pop { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: none; } }

    .a-answered { background: var(--surface); border: 1px solid var(--border); }
    .a-not_found {
      background: var(--dq-soft);
      border: 1px dashed var(--dq);
      display: flex;
      gap: 11px;
      align-items: flex-start;
    }
    .a-out_of_scope {
      background: var(--surface-sunken);
      border: 1px dashed var(--warn);
      display: flex;
      gap: 11px;
      align-items: flex-start;
    }
    .a-error {
      background: var(--surface-sunken);
      border: 1px solid var(--border-strong);
      display: flex;
      gap: 11px;
      align-items: flex-start;
    }

    .a-loading { background: var(--surface); border: 1px solid var(--border); display: flex; flex-direction: column; gap: 7px; padding: 14px; }
    .bar {
      height: 9px;
      border-radius: 4px;
      background: var(--surface-sunken);
      animation: pulse 1.4s var(--ease) infinite;
      width: 88%;
    }
    .bar.short { width: 52%; animation-delay: 0.12s; }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }

    .chip {
      display: inline-block;
      font-size: 10px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      border-radius: 4px;
      padding: 2px 7px;
    }
    .chip.ai { background: var(--ai); color: var(--accent-ink); }

    .prose { margin: 9px 0 0; color: var(--ink); }

    .cites { margin-top: 12px; border-top: 1px solid var(--border-subtle); padding-top: 10px; }
    .cites-label {
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      color: var(--ink-4);
      margin-bottom: 7px;
      font-weight: 600;
    }
    .cite {
      display: flex;
      gap: 8px;
      align-items: baseline;
      font-size: 11.5px;
      padding: 5px 9px;
      margin-bottom: 4px;
      background: var(--surface-elev);
      border: 1px solid var(--border-subtle);
      border-radius: var(--r-8);
      cursor: default;
      font-variant-numeric: tabular-nums;
    }
    .cite-value {
      font-family: var(--font-mono);
      font-size: 11.5px;
      font-weight: 700;
      color: var(--accent);
      background: var(--accent-soft);
      border: 1px solid var(--accent);
      border-radius: 4px;
      padding: 0 6px;
      flex-shrink: 0;
    }
    .cite-table { font-weight: 600; color: var(--accent); font-family: var(--font-mono); font-size: 11px; }
    .cite-field { color: var(--ink); }
    .cite-ts { font-family: var(--font-mono); font-size: 10.5px; color: var(--ink-4); white-space: nowrap; margin-left: auto; }
    .cite-id { font-family: var(--font-mono); font-size: 10.5px; color: var(--ink-4); }
    .cites-toggle {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      margin-top: 2px;
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

    .nf-icon { font-size: 18px; color: var(--dq); line-height: 1.4; }
    .nf-icon.warn { color: var(--warn); }
    .nf-title { font-weight: 600; color: var(--ink-2); }
    .nf-text { font-size: 12.5px; color: var(--ink-3); }
    .nf-sub { margin-top: 5px; font-size: 11.5px; color: var(--ink-4); }

    .retry-btn {
      margin-top: 8px;
      border: 1px solid var(--border-strong);
      background: var(--surface-elev);
      color: var(--ink-2);
      border-radius: var(--r-6);
      padding: 4px 12px;
      font-size: 11.5px;
      font-weight: 600;
      font-family: var(--font-mono);
      cursor: pointer;
      transition: color var(--d-fast) var(--ease), border-color var(--d-fast) var(--ease);
    }
    .retry-btn:hover:not(:disabled) { color: var(--accent); border-color: var(--accent); }
    .retry-btn:disabled { opacity: 0.5; cursor: default; }

    .input-row {
      display: flex;
      gap: 8px;
      padding: 12px 14px;
      border-top: 1px solid var(--border-subtle);
      background: var(--surface);
    }
    .input-row input {
      flex: 1;
      padding: 9px 12px;
      border-radius: var(--r-8);
      border: 1px solid var(--border-strong);
      font-size: 13px;
      font-family: var(--font-sans);
      background: var(--surface-elev);
      color: var(--ink);
      outline: none;
      transition: border-color var(--d-fast) var(--ease), box-shadow var(--d-fast) var(--ease);
    }
    .input-row input::placeholder { color: var(--ink-4); }
    .input-row input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-ring); }
    .input-row input:disabled { opacity: 0.6; }

    .input-row button {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 9px 15px;
      border-radius: var(--r-8);
      border: none;
      background: var(--accent);
      color: var(--accent-ink);
      font-weight: 600;
      font-size: 13px;
      font-family: var(--font-sans);
      cursor: pointer;
      transition: opacity var(--d-fast) var(--ease), transform var(--d-fast) var(--ease);
    }
    .input-row button:hover:not(:disabled) { opacity: 0.9; }
    .input-row button:active:not(:disabled) { transform: scale(0.97); }
    .input-row button:disabled { opacity: 0.4; cursor: default; }
  `],
})
export class QaPanelComponent implements AfterViewChecked {
  @Input() patientId = '';

  text = '';
  messages: Message[] = [];
  loading = false;

  @ViewChild('scroll') scroll!: ElementRef;

  constructor(private api: ApiService) {}

  ngAfterViewChecked(): void {
    if (this.scroll) {
      this.scroll.nativeElement.scrollTop = this.scroll.nativeElement.scrollHeight;
    }
  }

  visibleCites(m: Message): Citation[] {
    return m.citesAll ? m.response.citations : m.response.citations.slice(0, 6);
  }

  citeValue(c: Citation): string | null {
    const raw = c.value !== null && c.value !== undefined ? String(c.value) : null;
    const MISSING = ['___', '', 'unknown', 'n/a', 'na', 'none', '-', 'null', 'nan'];
    const shown = raw !== null && !MISSING.includes(raw.trim().toLowerCase())
      ? raw
      : c.value_numeric !== null && c.value_numeric !== undefined
        ? String(c.value_numeric)
        : null;
    if (shown === null) return null;
    return c.unit ? `${shown} ${c.unit}` : shown;
  }

  send(): void {
    const q = this.text.trim();
    if (!q || this.loading || !this.patientId) return;
    this.text = '';
    this.ask(q);
  }

  retry(m: Message): void {
    if (this.loading || !this.patientId) return;
    this.ask(m.question);
  }

  private ask(q: string): void {
    this.loading = true;
    this.api.ask(this.patientId, q).subscribe({
      next: (res) => {
        this.messages.push({ question: q, response: res, citesAll: false });
        this.loading = false;
      },
      error: (err) => {
        this.messages.push({
          question: q,
          response: {
            status: 'error',
            answer_summary: `Request failed: ${err.status ?? 'network error'}. Is the backend running?`,
            citations: [],
            query: null,
          },
          citesAll: false,
        });
        this.loading = false;
      },
    });
  }
}
