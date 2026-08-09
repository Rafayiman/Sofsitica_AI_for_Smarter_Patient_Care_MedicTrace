import { Component, OnInit } from '@angular/core';
import { NgIf, NgFor } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ApiService } from './services/api.service';
import { TimelineResponse, Patient } from './models';
import { TimelineComponent } from './components/timeline/timeline.component';
import { QaPanelComponent } from './components/qa-panel/qa-panel.component';
import { SafetyBannerComponent } from './components/safety-banner/safety-banner.component';
import { DqDashboardComponent } from './components/dq-dashboard/dq-dashboard.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [NgIf, NgFor, FormsModule, TimelineComponent, QaPanelComponent, SafetyBannerComponent, DqDashboardComponent],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css',
})
export class AppComponent implements OnInit {
  patients: Patient[] = [];
  selectedId = '';
  searchId = '';
  showDashboard = false;
  selected: Patient | null = null;
  timeline: TimelineResponse | null = null;
  loading = false;
  error = '';
  dark = true;

  constructor(private api: ApiService) {}

  ngOnInit(): void {
    if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
    this.applyTheme(localStorage.getItem('theme') ?? 'light');
    this.dismissBootSplash();
    this.api.getPatients().subscribe({
      next: (res) => {
        this.patients = res.patients;
      },
      error: () => {
        this.error = 'Could not reach the backend API. Is it running?';
      },
    });
  }

  toggleTheme(): void {
    this.applyTheme(this.dark ? 'light' : 'dark');
  }

  private applyTheme(theme: string): void {
    this.dark = theme === 'dark';
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }

  private dismissBootSplash(): void {
    const el = document.getElementById('boot-splash');
    if (!el) return;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const hold = reduce ? 500 : 1500;
    setTimeout(() => {
      el.classList.add('boot-splash-hide');
      el.addEventListener('transitionend', () => el.remove(), { once: true });
      setTimeout(() => el.remove(), 1000);
    }, hold);
  }

  onSelect(): void {
    this.showDashboard = false;
    this.loadTimeline();
  }

  toggleDashboard(): void {
    this.showDashboard = !this.showDashboard;
  }

  onSearch(): void {
    const id = this.searchId.trim();
    if (!id) return;
    const found = this.patients.find((p) => p.patient_id === id);
    if (!found) {
      this.error = `Unknown patient ID "${id}" — pick an ID from the dropdown or the hint.`;
      return;
    }
    this.error = '';
    this.selectedId = found.patient_id;
    this.showDashboard = false;
    this.loadTimeline();
  }

  loadTimeline(): void {
    if (!this.selectedId) return;
    this.searchId = this.selectedId;
    this.loading = true;
    this.error = '';
    this.timeline = null;
    this.api.getTimeline(this.selectedId).subscribe({
      next: (res) => {
        this.timeline = res;
        this.selected = this.patients.find((p) => p.patient_id === this.selectedId) ?? null;
        this.loading = false;
      },
      error: () => {
        this.loading = false;
        this.error = 'Failed to load timeline';
      },
    });
  }

  totalEvents(): number {
    return this.timeline?.days.reduce((a, d) => a + d.groups.reduce((b, g) => b + g.count, 0), 0) ?? 0;
  }

  totalFlagged(): number {
    return (
      this.timeline?.days.reduce(
        (a, d) => a + d.groups.reduce((b, g) => b + g.flags.reduce((c, f) => c + f.count, 0), 0),
        0
      ) ?? 0
    );
  }
}
