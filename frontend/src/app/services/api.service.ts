import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import {
  AskResponse,
  EvalReport,
  GroupExpandResponse,
  Patient,
  QualitySummary,
  TimelineResponse,
} from '../models';
import { environment } from '../../environments/environment';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private base = environment.apiBase;

  constructor(private http: HttpClient) {}

  getPatients(): Observable<{ patients: Patient[] }> {
    return this.http.get<{ patients: Patient[] }>(`${this.base}/api/patients`);
  }

  getTimeline(patientId: string): Observable<TimelineResponse> {
    return this.http.get<TimelineResponse>(`${this.base}/api/timeline/${patientId}`);
  }

  getQualitySummary(patientId?: string): Observable<QualitySummary> {
    const q = patientId ? `?patient_id=${encodeURIComponent(patientId)}` : '';
    return this.http.get<QualitySummary>(`${this.base}/api/quality/summary${q}`);
  }

  getEvalReport(): Observable<EvalReport> {
    return this.http.get<EvalReport>(`${this.base}/api/eval/report`);
  }

  expandGroup(
    patientId: string,
    g: { date: string; event_type: string; event_subtype: string | null; source_table: string; encounter_id: string | null }
  ): Observable<GroupExpandResponse> {
    const params: string[] = [
      `date=${encodeURIComponent(g.date)}`,
      `event_type=${encodeURIComponent(g.event_type)}`,
      `event_subtype=${encodeURIComponent(g.event_subtype ?? '')}`,
      `source_table=${encodeURIComponent(g.source_table)}`,
    ];
    if (g.encounter_id !== null && g.encounter_id !== undefined) {
      params.push(`encounter_id=${encodeURIComponent(g.encounter_id)}`);
    }
    return this.http.get<GroupExpandResponse>(
      `${this.base}/api/group/${patientId}?${params.join('&')}`
    );
  }

  ask(patientId: string, question: string): Observable<AskResponse> {
    return this.http.post<AskResponse>(`${this.base}/api/ask`, {
      patient_id: patientId,
      question,
    });
  }
}
